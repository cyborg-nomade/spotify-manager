"""Verify interactive Requeue selection before fresh observations and effects."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.requeue import RequeueDependencies
from spotify_manager.application.requeue import flush_requeue
from spotify_manager.application.requeue_result import RequeueForADreamChangedError
from spotify_manager.application.requeue_result import RequeueForADreamError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from tests.application.test_requeue import FIRST
from tests.application.test_requeue import SECOND
from tests.application.test_requeue import SOURCE
from tests.application.test_requeue import TARGET
from tests.application.test_requeue import MemoryRequeue
from tests.support.listening_values import studio_release


THIRD = studio_release("third", "Third", "2022")
FOURTH = studio_release("fourth", "Fourth", "2023")


@dataclass
class AlbumDecisions:
    """Script decisions while observing their order beside external effects.

    Args:
        memory: Current simulated external resources.
        choices: Explicit actions in proposal order.
        offered: Recorded release identities.
    """

    memory: MemoryRequeue
    choices: list[str]
    offered: list[str] = field(default_factory=list)

    async def choose_album(
        self, source: PlaylistTrack, release: DiscographyRelease
    ) -> str:
        """Record the proposal and consume one explicit decision.

        Args:
            source: Original source marker.
            release: Proposed eligible successor.

        Returns:
            Next scripted operator action.
        """
        assert source == SOURCE
        self.memory.events.append(("album", release.spotify_id))
        self.offered.append(release.spotify_id)
        return self.choices.pop(0)


def _dependencies(
    memory: MemoryRequeue, choices: list[str]
) -> tuple[RequeueDependencies, AlbumDecisions]:
    reader = AlbumDecisions(memory, choices)
    return replace(memory.dependencies(), album_reader=reader), reader


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("skips", [0, 1, 2])
async def test_accept_successor_after_repeated_skips(preview: bool, skips: int) -> None:
    """Skipped releases have no track reads or effects; acceptance keeps effect order.

    Args:
        preview: Suppress final freshness checks, mutations and audits.
        skips: Number of complete successor albums to reject.
    """
    releases = (FIRST, SECOND, THIRD, FOURTH)
    memory = MemoryRequeue([SOURCE], releases=releases)
    dependencies, reader = _dependencies(memory, ["skip"] * skips + ["accept"])
    result = await flush_requeue(dependencies, "p", dry_run=preview)
    selected = releases[skips + 1]
    assert reader.offered == [item.spotify_id for item in releases[1 : skips + 2]]
    assert result.action == "advance" and result.target_release == selected.name
    assert [event[1] for event in memory.events if event[0] == "tracks"] == [
        selected.spotify_id
    ]
    effects = [
        event[0] for event in memory.events if event[0] in {"append", "remove", "audit"}
    ]
    assert effects == ([] if preview else ["append", "remove", "audit"])
    assert memory.reads == (1 if preview else 2)


@pytest.mark.parametrize("preview", [False, True])
async def test_cancel_after_skip_leaves_marker_and_audit_unchanged(
    preview: bool,
) -> None:
    """Abandoned selections are not applied or logged as completed transitions.

    Args:
        preview: Whether cancellation occurs in a preview.
    """
    memory = MemoryRequeue([SOURCE], releases=(FIRST, SECOND, THIRD))
    dependencies, reader = _dependencies(memory, ["skip", "cancel"])
    result = await flush_requeue(dependencies, "p", dry_run=preview)
    assert result.action == "cancel"
    assert result.playlist_length_before == result.playlist_length_after == 1
    assert reader.offered == ["second", "third"]
    assert memory.playlist == [SOURCE] and memory.audits == []
    assert not any(
        event[0] in {"append", "remove", "tracks"} for event in memory.events
    )
    assert memory.reads == 1


@pytest.mark.parametrize("preview", [False, True])
async def test_exhaustion_retains_completion_policy(preview: bool) -> None:
    """Rejecting every successor completes the artist using the original drop policy.

    Args:
        preview: Suppress removal and audit while previewing completion.
    """
    memory = MemoryRequeue([SOURCE], releases=(FIRST, SECOND, THIRD))
    dependencies, reader = _dependencies(memory, ["skip", "skip"])
    result = await flush_requeue(dependencies, "p", dry_run=preview)
    assert reader.offered == ["second", "third"]
    assert result.action == "drop" and result.playlist_length_after == 0
    assert result.reason == "all remaining eligible albums were skipped"
    assert memory.playlist == ([SOURCE] if preview else [])
    assert len(memory.audits) == int(not preview)
    assert not any(event[0] in {"tracks", "append"} for event in memory.events)


@pytest.mark.parametrize("choices", [["accept"], ["skip"]])
@pytest.mark.parametrize("head", [(), (TARGET,)])
async def test_changed_head_after_interaction_prevents_all_writes(
    choices: list[str], head: tuple[PlaylistTrack, ...]
) -> None:
    """Both accepted transitions and exhaustion recheck the head after interaction.

    Args:
        choices: Acceptance or exhaustion decision.
        head: Concurrently changed playlist head.
    """
    memory = MemoryRequeue([SOURCE], changed_head=head)
    dependencies, _reader = _dependencies(memory, list(choices))
    with pytest.raises(RequeueForADreamChangedError):
        await flush_requeue(dependencies, "p")
    assert memory.playlist == [SOURCE] and memory.audits == []
    assert not any(event[0] in {"append", "remove", "clock"} for event in memory.events)


@pytest.mark.parametrize("was_present", [False, True])
async def test_duplicate_observation_is_refreshed_after_acceptance(
    was_present: bool,
) -> None:
    """A concurrent non-head edit cannot cause a duplicate or omit the replacement.

    Args:
        was_present: Whether the target was present before operator interaction.
    """
    initial = [SOURCE, TARGET] if was_present else [SOURCE]
    fresh = (SOURCE,) if was_present else (SOURCE, TARGET)
    memory = MemoryRequeue(initial, changed_head=fresh)
    dependencies, _reader = _dependencies(memory, ["accept"])
    result = await flush_requeue(dependencies, "p")
    assert result.target_already_present is not was_present
    assert result.playlist_length_before == len(fresh)
    assert result.playlist_length_after == 1
    assert any(event[0] == "append" for event in memory.events) is was_present
    assert [event[0] for event in memory.events].index("album") < [
        event[0] for event in memory.events
    ].index("tracks")


async def test_invalid_album_decision_fails_before_track_reads_or_effects() -> None:
    """A malformed interaction cannot silently accept or complete an artist."""
    memory = MemoryRequeue([SOURCE])
    dependencies, _reader = _dependencies(memory, ["invalid"])
    with pytest.raises(RequeueForADreamError, match="Album choice must"):
        await flush_requeue(dependencies, "p")
    assert memory.playlist == [SOURCE] and not memory.audits
    assert not any(
        event[0] in {"tracks", "append", "remove"} for event in memory.events
    )


@pytest.mark.parametrize("releases", [(FIRST,), (SECOND,)])
async def test_no_successor_does_not_invent_an_album_prompt(
    releases: tuple[DiscographyRelease, ...],
) -> None:
    """Keep final-release completion and ineligible-source handling without a proposal.

    Args:
        releases: Catalog with no successor or no eligible current match.
    """
    memory = MemoryRequeue([SOURCE], releases=releases)
    dependencies, reader = _dependencies(memory, [])
    result = await flush_requeue(dependencies, "p", dry_run=True)
    assert result.action == ("drop" if releases == (FIRST,) else "skip")
    assert reader.offered == []
