"""Verify recovery orchestration without Spotify, files, or runtime services."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial

import pytest

from spotify_manager.application.album_recovery import recover_albums
from spotify_manager.application.recovery_values import RecoveryAlbum
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.application.recovery_values import RecoverySummary
from spotify_manager.application.recovery_values import RemovedAlbumRecord
from spotify_manager.domain.library import AlbumArtist


def _records() -> list[RemovedAlbumRecord]:
    return [RemovedAlbumRecord("album", "Album", "Artist")]


def _future() -> RecoveryAlbum:
    return RecoveryAlbum(
        "Live Album",
        "spotify:album:album",
        (AlbumArtist("artist", "Artist"), AlbumArtist("guest", "Guest")),
        "2027",
        "year",
    )


def _state() -> RecoveryState:
    return RecoveryState(set(), set())


def _observations() -> tuple[RecoveryAlbum | None, ...]:
    return (_future(),)


@dataclass
class MemoryRecovery:
    """In-memory observations, effects, presentation, and explicit clocks.

    Args:
        records: Original ordered removal history.
        observations: Original album batch observations.
        state: Restart progress shared across invocations.
        is_saved: Current saved-album membership.
        fail: Optional boundary to interrupt.
    """

    records: list[RemovedAlbumRecord] = field(default_factory=_records)
    observations: tuple[RecoveryAlbum | None, ...] = field(
        default_factory=_observations
    )
    state: RecoveryState = field(default_factory=_state)
    is_saved: bool = False
    fail: str | None = None
    effects: list[str] = field(default_factory=list, init=False)
    audits: list[dict[str, object]] = field(default_factory=list, init=False)

    def _effect(self, name: str) -> None:
        self.effects.append(name)
        if name == self.fail:
            raise RuntimeError(name)

    def load(self) -> tuple[list[RemovedAlbumRecord], RecoveryState]:
        """Load original history and bind checkpoint persistence.

        Returns:
            Records and shared restart state.
        """
        self._effect("load")
        self.state.persist = partial(self._effect, "checkpoint")
        return self.records, self.state

    def albums(
        self, records: list[RemovedAlbumRecord]
    ) -> tuple[RecoveryAlbum | None, ...]:
        """Return controlled metadata observations.

        Args:
            records: Requested original records.

        Returns:
            Configured observations, including any deliberate count mismatch.
        """
        self._effect("catalog")
        return self.observations

    def follow_artists(
        self, artists: list[AlbumArtist], state: RecoveryState, dry_run: bool
    ) -> tuple[int, int]:
        """Observe the credited artists before any album restoration.

        Args:
            artists: Gathered credits across the complete batch.
            state: Current completed-work state.
            dry_run: Whether the invocation previews effects.

        Returns:
            Fixture counts with one new follow when artists exist.
        """
        self._effect(f"follow:{len(artists)}:{dry_run}")
        return len(artists), int(bool(artists))

    def saved(self, record: RemovedAlbumRecord) -> bool:
        """Observe current saved status.

        Args:
            record: Original album identity.

        Returns:
            Current fixture membership.
        """
        self._effect("saved")
        return self.is_saved

    def restore(self, record: RemovedAlbumRecord) -> None:
        """Accept one remote restore.

        Args:
            record: Original album identity.
        """
        self._effect("restore")
        self.is_saved = True

    def record_album(self, album: RecoveryAlbum, record: RemovedAlbumRecord) -> bool:
        """Accept a mirror and statistics update.

        Args:
            album: Parsed observations.
            record: Original album identity.

        Returns:
            True for a newly mirrored album.
        """
        self._effect("mirror")
        return True

    def audit(self, event: dict[str, object]) -> None:
        """Accept the completed album event.

        Args:
            event: Original audit shape.
        """
        self._effect("audit")
        self.audits.append(event)

    def unavailable(self, record: RemovedAlbumRecord) -> None:
        """Present an unavailable album.

        Args:
            record: Original labels.
        """
        self._effect("unavailable")

    def credits(self, album: RecoveryAlbum, record: RemovedAlbumRecord) -> None:
        """Present multiple credited artists.

        Args:
            album: Parsed observations.
            record: Fallback labels.
        """
        self._effect("credits")

    def future(
        self, record: RemovedAlbumRecord, release_date: str | None, status: str
    ) -> None:
        """Present a future-release outcome.

        Args:
            record: Original labels.
            release_date: Observed date text.
            status: Expected outcome prefix.
        """
        self._effect(status)

    def finish(self, summary: RecoverySummary, dry_run: bool) -> None:
        """Present final counts.

        Args:
            summary: Completed outcomes.
            dry_run: Whether the invocation previewed effects.
        """
        self._effect("finish")

    def clock(self) -> datetime:
        """Read the per-album audit clock.

        Returns:
            Fixed aware timestamp.
        """
        self._effect("clock")
        return datetime(2026, 7, 14, tzinfo=UTC)

    def today(self) -> date:
        """Read the per-album date boundary.

        Returns:
            Fixed comparison date.
        """
        self._effect("today")
        return date(2026, 7, 14)

    def progress(self, completed: int, total: int) -> None:
        """Record progress and cancellation boundaries.

        Args:
            completed: Number completed, including prior progress.
            total: Original limit-adjusted count.
        """
        self._effect(f"progress:{completed}/{total}")


def test_recovery_orders_artist_and_album_effects() -> None:
    """Retain the full write, audit, checkpoint, and progress sequence."""
    fixture = MemoryRecovery()
    result = recover_albums(
        fixture, fixture, fixture.clock, fixture.today, progress=fixture.progress
    )
    assert fixture.effects == [
        "load",
        "progress:0/1",
        "catalog",
        "follow:2:False",
        "clock",
        "credits",
        "today",
        "saved",
        "restore",
        "mirror",
        "Restored future release",
        "audit",
        "checkpoint",
        "progress:1/1",
        "finish",
    ]
    assert result == RecoverySummary(1, 0, 1, 2, 1, 1, 1)
    assert fixture.audits[0]["restored"] is True
    assert fixture.state.processed_album_ids == {"album"}


@pytest.mark.parametrize("already_saved", [False, True])
def test_recovery_preview_preserves_reads_without_writes(already_saved: bool) -> None:
    """Preview counts remain sensitive to live membership.

    Args:
        already_saved: Whether the album is currently saved.
    """
    fixture = MemoryRecovery(is_saved=already_saved)
    result = recover_albums(
        fixture, fixture, fixture.clock, fixture.today, dry_run=True
    )
    assert result.albums_restored == int(not already_saved)
    assert fixture.state.processed_album_ids == {"album"}
    assert not {"restore", "mirror", "audit", "checkpoint"}.intersection(
        fixture.effects
    )
    assert "saved" in fixture.effects


def test_already_saved_future_release_still_updates_mirror() -> None:
    """Current remote membership does not skip the local repair boundary."""
    fixture = MemoryRecovery(is_saved=True)
    recover_albums(fixture, fixture, fixture.clock, fixture.today)
    assert "restore" not in fixture.effects
    assert fixture.effects[7:11] == [
        "mirror",
        "Future release already saved",
        "audit",
        "checkpoint",
    ]
    assert fixture.audits[0]["already_saved"] is True


@pytest.mark.parametrize(
    "album",
    [
        None,
        RecoveryAlbum(None, None, (), None, None),
        RecoveryAlbum("Old", None, (), "2000", "year"),
    ],
)
def test_nonfuture_albums_have_no_membership_or_restore(
    album: RecoveryAlbum | None,
) -> None:
    """Unavailable, undated, and past albums still complete and checkpoint.

    Args:
        album: Metadata observation to process.
    """
    fixture = MemoryRecovery(observations=(album,))
    result = recover_albums(fixture, fixture, fixture.clock, fixture.today)
    assert not {"saved", "restore", "mirror"}.intersection(fixture.effects)
    assert result.processed == 1
    assert result.unavailable == int(album is None)
    assert fixture.audits[0]["album"] == (
        album.name if album and album.name else "Album"
    )


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_preserves_python_slice_semantics(limit: int) -> None:
    """Zero and negative limits retain their original pending-record slice.

    Args:
        limit: Original CLI/API limit passed through to the use case.
    """
    fixture = MemoryRecovery()
    result = recover_albums(
        fixture,
        fixture,
        fixture.clock,
        fixture.today,
        limit=limit,
        progress=fixture.progress,
    )
    assert result.processed == 0
    assert fixture.effects == ["load", "progress:0/0", "finish"]


def test_restart_skips_completed_records() -> None:
    """Completed IDs survive a new use-case invocation without new observations."""
    fixture = MemoryRecovery(state=RecoveryState({"album"}, set()))
    result = recover_albums(
        fixture, fixture, fixture.clock, fixture.today, progress=fixture.progress
    )
    assert result.processed == 0
    assert fixture.effects == ["load", "progress:1/1", "finish"]


def test_excess_metadata_preserves_artist_effects_before_strict_zip_error() -> None:
    """An oversized response retains its legacy effects before raising."""
    fixture = MemoryRecovery(observations=(_future(), _future()))
    with pytest.raises(ValueError, match="zip"):
        recover_albums(fixture, fixture, fixture.clock, fixture.today)
    assert "follow:4:False" in fixture.effects
    assert fixture.state.processed_album_ids == {"album"}
    assert "finish" not in fixture.effects


@pytest.mark.parametrize(
    "failure", ["saved", "restore", "mirror", "audit", "checkpoint"]
)
def test_failed_recovery_retains_accepted_writes(failure: str) -> None:
    """Only accepted boundaries affect remote and completed-work state.

    Args:
        failure: Boundary to interrupt.
    """
    fixture = MemoryRecovery(fail=failure)
    with pytest.raises(RuntimeError, match=failure):
        recover_albums(fixture, fixture, fixture.clock, fixture.today)
    assert fixture.is_saved is (failure in {"mirror", "audit", "checkpoint"})
    assert bool(fixture.state.processed_album_ids) is (failure == "checkpoint")
    assert fixture.effects[-1] == failure
