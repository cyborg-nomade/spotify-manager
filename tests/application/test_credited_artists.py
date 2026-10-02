"""Protect duplicate, batch, and partial-write semantics of credited-artist recovery."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from functools import partial

import pytest

from spotify_manager.application.credited_artists import CreditedArtistDependencies
from spotify_manager.application.credited_artists import follow_credited_artists
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.domain.library import AlbumArtist


@dataclass
class MemoryCredits:
    """In-memory remote membership, mirrors, audits, and effect failures.

    Args:
        followed: Current remote membership.
        response: Optional malformed membership response override.
        fail: Optional boundary to interrupt before acceptance.
    """

    followed: set[str] = field(default_factory=set)
    response: list[bool] | None = None
    fail: str | None = None
    effects: list[str] = field(default_factory=list, init=False)
    batches: list[list[AlbumArtist]] = field(default_factory=list, init=False)
    events: list[dict[str, object]] = field(default_factory=list, init=False)

    def effect(self, name: str) -> None:
        """Record an effect boundary and optionally interrupt it.

        Args:
            name: Boundary name.

        Raises:
            RuntimeError: The configured boundary is reached.
        """
        self.effects.append(name)
        if name == self.fail:
            raise RuntimeError(name)

    def statuses(self, artists: list[AlbumArtist]) -> list[bool]:
        """Read current membership in the supplied order.

        Args:
            artists: Batch to observe.

        Returns:
            Current membership, or a configured malformed response.
        """
        self.effect("statuses")
        self.batches.append(list(artists))
        if self.response is not None:
            return self.response
        return [artist.spotify_id in self.followed for artist in artists]

    def follow(self, artists: list[AlbumArtist]) -> None:
        """Accept the requested follows.

        Args:
            artists: Ordered missing artists.
        """
        self.effect("follow")
        self.followed.update(artist.spotify_id for artist in artists)

    def record(self, artists: list[AlbumArtist]) -> set[str]:
        """Accept mirror publication for all checked artists.

        Args:
            artists: Complete batch, including already-followed artists.

        Returns:
            IDs newly recorded by this fixture.
        """
        self.effect("mirror")
        return {artist.spotify_id for artist in artists}

    def audit(self, events: list[dict[str, object]]) -> None:
        """Accept the original artist event documents.

        Args:
            events: Ordered completed artist observations.
        """
        self.effect("audit")
        self.events.extend(events)

    def clock(self) -> datetime:
        """Observe the per-batch timestamp boundary.

        Returns:
            Fixed aware timestamp.
        """
        self.effect("clock")
        return datetime(2026, 9, 24, tzinfo=UTC)

    def announce(self, artist: AlbumArtist, dry_run: bool) -> None:
        """Record follow or preview output.

        Args:
            artist: Newly followed or previewed artist.
            dry_run: Whether effects are being previewed.
        """
        self.effect(f"announce:{artist.spotify_id}:{dry_run}")

    def dependencies(self) -> CreditedArtistDependencies:
        """Bind this fixture to the application service.

        Returns:
            Explicit integration, clock, and presentation dependencies.
        """
        return CreditedArtistDependencies(self, self.clock, self.announce)


def test_credits_keep_last_duplicate_name_first_position_and_forty_id_batches() -> None:
    """Retain stable dictionary deduplication, completed IDs, and batch boundaries."""
    fixture = MemoryCredits(followed={"2"})
    artists = [AlbumArtist(str(index), f"Artist {index}") for index in range(42)]
    artists.append(AlbumArtist("0", "Last observed name"))
    state = RecoveryState(set(), {"1"}, partial(fixture.effect, "checkpoint"))
    result = follow_credited_artists(fixture.dependencies(), artists, state, False)
    assert result == (41, 40)
    assert [len(batch) for batch in fixture.batches] == [40, 1]
    assert fixture.batches[0][0] == AlbumArtist("0", "Last observed name")
    assert fixture.events[0]["artist"] == "Last observed name"
    assert fixture.events[1]["was_followed"] is True
    assert fixture.events[1]["recorded_locally"] is True
    assert fixture.effects.count("checkpoint") == 2
    assert fixture.effects[:4] == ["statuses", "follow", "mirror", "clock"]


def test_credit_preview_marks_checked_without_persisting_or_writing() -> None:
    """Preview retains run-local deduplication and clocks but omits durable effects."""
    fixture = MemoryCredits()
    state = RecoveryState(set(), set(), partial(fixture.effect, "checkpoint"))
    result = follow_credited_artists(
        fixture.dependencies(), [AlbumArtist("a", "A")], state, True
    )
    assert result == (1, 1)
    assert fixture.effects == ["statuses", "clock", "announce:a:True"]
    assert state.checked_artist_ids == {"a"}
    assert fixture.followed == set()


@pytest.mark.parametrize("response", [[], [True, False]])
def test_credit_membership_length_fails_before_any_write(response: list[bool]) -> None:
    """Do not guess missing or excess follow statuses.

    Args:
        response: Too few or too many statuses for one artist.
    """
    fixture = MemoryCredits(response=response)
    state = RecoveryState(set(), set())
    with pytest.raises(RuntimeError, match="incomplete artist-follow response"):
        follow_credited_artists(
            fixture.dependencies(), [AlbumArtist("a", "A")], state, False
        )
    assert fixture.effects == ["statuses"]
    assert not state.checked_artist_ids


def test_credit_publication_failure_retains_follow_for_restart() -> None:
    """A retry observes an accepted remote follow before publishing its local record."""
    fixture = MemoryCredits(fail="mirror")
    state = RecoveryState(set(), set())
    artists = [AlbumArtist("a", "A")]
    with pytest.raises(RuntimeError, match="mirror"):
        follow_credited_artists(fixture.dependencies(), artists, state, False)
    assert fixture.followed == {"a"}
    assert state.checked_artist_ids == set()
    fixture.fail = None
    assert follow_credited_artists(fixture.dependencies(), artists, state, False) == (
        1,
        0,
    )
    assert fixture.effects.count("follow") == 1
    assert fixture.events[0]["followed_now"] is False


def test_credit_audit_failure_retains_in_memory_check_before_checkpoint() -> None:
    """Audit failure occurs after marking checked but before durable persistence."""
    fixture = MemoryCredits(fail="audit")
    state = RecoveryState(set(), set(), partial(fixture.effect, "checkpoint"))
    with pytest.raises(RuntimeError, match="audit"):
        follow_credited_artists(
            fixture.dependencies(), [AlbumArtist("a", "A")], state, False
        )
    assert state.checked_artist_ids == {"a"}
    assert "checkpoint" not in fixture.effects


def test_completed_credits_skip_all_observations() -> None:
    """An entirely completed batch performs no work and returns zero counts."""
    fixture = MemoryCredits()
    state = RecoveryState(set(), {"a"})
    assert follow_credited_artists(
        fixture.dependencies(), [AlbumArtist("a", "A")], state, False
    ) == (0, 0)
    assert fixture.effects == []
