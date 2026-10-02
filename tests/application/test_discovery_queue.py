"""Queue transfers preserve capacity, logical artists and accepted-effect ordering."""

from dataclasses import replace

import pytest

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.discovery_effects import MemoryQueue
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


FIRST = playlist_track("one", studio_release("album", "Album"))
SECOND = replace(
    FIRST,
    spotify_id="two",
    uri="spotify:track:two",
    primary_artist_id="other",
    primary_artist_name="Other",
)


def _service(
    memory: MemoryQueue, *, preview: bool = False, capacity: int = 10
) -> DiscoveryQueueTransfer:
    return DiscoveryQueueTransfer(
        memory, memory, memory, "kids", "queue", capacity, preview
    )


def _names(memory: MemoryQueue) -> list[str]:
    return [name for name, value in memory.events]


def test_transfer_reads_then_adds_removes_projects_and_audits() -> None:
    """Successful transfers mutate the caller's list only after both remote effects."""
    memory = MemoryQueue(queued=(FIRST,))
    current: list[PlaylistTrack] = []
    updated, results, remaining = _service(memory).move(current, {})
    assert updated is current and current == [FIRST]
    assert results[0].action == "moved" and remaining == []
    assert _names(memory) == ["playlist", "append", "remove", "audit", "moved"]
    assert memory.events[1] == ("append", ("kids", FIRST, "adding Artist to New Kids"))
    assert memory.events[2] == (
        "remove",
        ("queue", FIRST, "removing Artist from Queue 2"),
    )
    assert memory.events[3] == (
        "audit",
        (
            "queue_2_moved",
            {
                "artist": "Artist",
                "artist_id": "artist",
                "track": FIRST.name,
                "track_id": "one",
                "dry_run": False,
            },
        ),
    )


@pytest.mark.parametrize("preview", [False, True])
def test_existing_logical_artist_is_reconciled_without_audit_or_message(
    preview: bool,
) -> None:
    """Duplicate artist markers are removed without consuming destination capacity."""
    memory = MemoryQueue()
    duplicate = replace(FIRST, spotify_id="different")
    current = [FIRST]
    updated, results, remaining = _service(memory, preview=preview).move(
        current, {}, [duplicate]
    )
    assert updated == [FIRST] and remaining == []
    assert results[0].action == "reconciled"
    expected = (
        []
        if preview
        else [
            (
                "remove",
                ("queue", duplicate, "removing reconciled Queue 2 marker for Artist"),
            )
        ]
    )
    assert memory.events == expected


def test_preview_projects_transfer_and_still_writes_audit() -> None:
    """Preview transfer audit and messages survive without remote writes."""
    memory = MemoryQueue()
    updated, results, remaining = _service(memory, preview=True).move([], {}, [FIRST])
    assert updated == [FIRST] and results[0].action == "moved" and remaining == []
    assert _names(memory) == ["audit", "moved"]
    assert memory.events[-1] == ("moved", ("Artist", True))


def test_explicit_empty_queue_does_not_trigger_a_live_read() -> None:
    """An empty supplied observation differs from an omitted queue."""
    memory = MemoryQueue(queued=(FIRST,))
    assert _service(memory).move([], {}, []) == ([], (), [])
    assert memory.events == []


def test_capacity_is_checked_before_reconciling_duplicates() -> None:
    """A full destination retains the entire remaining queue, including duplicates."""
    memory = MemoryQueue()
    current = [FIRST]
    updated, results, remaining = _service(memory, capacity=1).move(
        current, {}, [FIRST, SECOND]
    )
    assert updated is current and results == () and remaining == [FIRST, SECOND]
    assert memory.events == []


def test_new_transfers_stop_at_capacity_and_preserve_queue_suffix_order() -> None:
    """Capacity counts destination entries and leaves later source entries untouched."""
    memory = MemoryQueue()
    updated, results, remaining = _service(memory, capacity=1).move(
        [], {}, [FIRST, SECOND, FIRST]
    )
    assert updated == [FIRST] and len(results) == 1 and remaining == [SECOND, FIRST]
    assert _names(memory) == ["append", "remove", "audit", "moved"]


def test_existing_track_with_different_artist_retains_duplicate_entry() -> None:
    """Same-ID markers with different credits retain the destination list duplicate."""
    memory = MemoryQueue()
    different_credit = replace(
        FIRST, primary_artist_id="other", primary_artist_name="Other"
    )
    updated, results, remaining = _service(memory).move([FIRST], {}, [different_credit])
    assert updated == [FIRST, different_credit]
    assert results[0].action == "moved" and remaining == []
    assert _names(memory) == ["remove", "audit", "moved"]


def test_projected_artist_membership_reconciles_later_queue_duplicates() -> None:
    """A newly moved artist suppresses later markers without requiring another read."""
    memory = MemoryQueue()
    duplicate = replace(FIRST, spotify_id="duplicate")
    updated, results, remaining = _service(memory).move(
        [], {}, [FIRST, duplicate, SECOND]
    )
    assert updated == [FIRST, SECOND] and remaining == []
    assert [result.action for result in results] == ["moved", "reconciled", "moved"]
    assert _names(memory).count("append") == 2 and _names(memory).count("remove") == 3


def test_saved_composer_credit_controls_transfer_deduplication() -> None:
    """Composer routes retain their logical identity during queue transfers."""
    memory = MemoryQueue()
    state: dict[str, object] = {
        "composer_routes": {
            "composer": {"artist_name": "Composer", "current_track_id": "one"}
        }
    }
    current = [replace(SECOND, primary_artist_id="composer")]
    updated, results, remaining = _service(memory).move(current, state, [FIRST])
    assert updated is current and len(updated) == 1 and remaining == []
    assert results[0].artist == "Composer" and results[0].action == "reconciled"


@pytest.mark.parametrize("boundary", ["append", "remove", "audit", "moved"])
def test_transfer_failure_preserves_original_projection_boundary(boundary: str) -> None:
    """The destination list changes after queue removal and before audit."""
    memory = MemoryQueue(fail_at=boundary)
    current: list[PlaylistTrack] = []
    effects = ["append", "remove", "audit", "moved"]
    with pytest.raises(OSError, match=boundary):
        _service(memory).move(current, {}, [FIRST])
    assert _names(memory) == effects[: effects.index(boundary) + 1]
    assert current == ([FIRST] if boundary in {"audit", "moved"} else [])
