"""Verify refill capacity, pending-transfer recovery and eligibility ordering."""

from copy import deepcopy
from dataclasses import asdict
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.wine_cellar import CellarOptions
from spotify_manager.application.wine_cellar import refill_cellar
from tests.support.cellar_memory import MemoryCellar
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


RELEASE = studio_release("release", "Release")
SOURCE = playlist_track("source", RELEASE)
OTHER = playlist_track("other", RELEASE)


def _run(
    memory: MemoryCellar,
    *,
    dry_run: bool = False,
    no_discovery: bool = False,
    projected: set[str] | None = None,
    target_size: int = 10,
) -> CellarRefillSummary:
    state = deepcopy(memory.stored)
    run = cast(
        dict[str, object],
        state.setdefault("active_run", {"run_id": "run", "refill_pending": None}),
    )
    options = CellarOptions(
        "new", "cellar", no_discovery, dry_run, target_size, projected
    )
    return refill_cellar(memory, options, state, run, memory.moved)


def _pending(memory: MemoryCellar, liked: object = None, albums: object = None) -> None:
    memory.stored = {
        "active_run": {
            "run_id": "run",
            "refill_pending": {
                "source": asdict(SOURCE),
                "liked_tracks": liked,
                "saved_albums": albums,
            },
        }
    }


@pytest.mark.parametrize("dry_run", [False, True])
def test_refill_keeps_transfer_checkpoint_and_audit_order(dry_run: bool) -> None:
    """Secure the destination before removing the source or clearing its intent.

    Args:
        dry_run: Whether to suppress mutations and checkpoints while keeping audits.
    """
    memory = MemoryCellar({"new": [], "cellar": [SOURCE]})
    result = _run(memory, dry_run=dry_run)
    expected = ["playlist", "playlist"]
    expected += [] if dry_run else ["save", "append", "remove"]
    expected += ["moved"] + ([] if dry_run else ["save"]) + ["audit"]
    assert [event[0] for event in memory.events] == expected
    assert (result.before, result.after, result.added, result.removed_from_cellar) == (
        0,
        1,
        1,
        1,
    )
    assert len(memory.audits) == 1
    assert memory.playlists["cellar"] == ([SOURCE] if dry_run else [])
    assert memory.playlists["new"] == ([] if dry_run else [SOURCE])


def test_full_destination_avoids_cellar_and_inventory_reads() -> None:
    """Capacity is based on unique observed destination IDs before any refill reads."""
    memory = MemoryCellar({"new": [SOURCE, SOURCE, OTHER], "cellar": []})
    result = _run(memory, target_size=2, no_discovery=True)
    assert (result.before, result.after, result.added) == (2, 2, 0)
    assert memory.events == [("playlist", "new")]


def test_projected_preview_membership_avoids_destination_read() -> None:
    """Preview capacity uses the preceding flush's projected IDs, not stale live IDs."""
    memory = MemoryCellar({"new": [OTHER], "cellar": [SOURCE]})
    result = _run(memory, dry_run=True, projected=set())
    assert (result.before, result.after) == (0, 1)
    assert memory.events[0] == ("playlist", "cellar")
    assert memory.playlists == {"new": [OTHER], "cellar": [SOURCE]}


def test_preview_stops_after_reaching_target_size() -> None:
    """Do not inspect or transfer later cellar entries once capacity is filled."""
    memory = MemoryCellar({"new": [], "cellar": [SOURCE, OTHER]})
    result = _run(memory, dry_run=True, target_size=1)
    assert result.added == 1
    assert [result.source_track for result in result.results] == [SOURCE.name]


def test_duplicate_cellar_marker_is_removed_once_without_duplicate_append() -> None:
    """Remove repeated cellar markers without duplicating a destination track."""
    memory = MemoryCellar({"new": [SOURCE], "cellar": [SOURCE, SOURCE, OTHER]})
    result = _run(memory)
    assert [item.action for item in result.results] == ["already present", "moved"]
    assert result.added == 1 and result.removed_from_cellar == 2
    assert memory.calls["append"] == 1
    assert memory.playlists["new"] == [SOURCE, OTHER]
    assert memory.playlists["cellar"] == []


def test_eligibility_leaves_ineligible_sources_and_caches_normalized_artist() -> None:
    """Only qualifying sources move; repeated artist names reuse their live counts."""
    low = replace(SOURCE, primary_artist_name="Low")
    high = replace(OTHER, primary_artist_name=" High ")
    repeated = replace(high, spotify_id="third", primary_artist_name="HIGH")
    memory = MemoryCellar(
        {"new": [], "cellar": [low, high, repeated]},
        eligibility={"high": (None, 3, True)},
    )
    result = _run(memory, no_discovery=True)
    assert [item.action for item in result.results] == ["ineligible", "moved", "moved"]
    assert result.ineligible == 1 and result.added == 2
    assert memory.calls["counts"] == 2
    assert memory.playlists["cellar"] == [low]
    assert [item.saved_albums for item in result.results] == [0, 3, 3]


@pytest.mark.parametrize("liked,albums", [(True, False), ("1", []), (18, 2)])
def test_pending_transfer_preserves_count_parsing_and_bypasses_eligibility(
    liked: object, albums: object
) -> None:
    """Resume the accepted intent even when current counts would reject the artist.

    Args:
        liked: Stored liked-track count with legacy bool-as-int semantics.
        albums: Stored saved-album count with legacy bool-as-int semantics.
    """
    memory = MemoryCellar({"new": [], "cellar": [SOURCE]})
    _pending(memory, liked, albums)
    result = _run(memory, no_discovery=True, target_size=1)
    assert result.added == 1
    assert "inventory" not in memory.calls and "counts" not in memory.calls
    assert result.results[0].liked_tracks == (liked if isinstance(liked, int) else None)
    assert result.results[0].saved_albums == (
        albums if isinstance(albums, int) else None
    )


def test_pending_duplicate_is_reconciled_even_when_destination_is_full() -> None:
    """Do not let the capacity guard strand a previously accepted transfer."""
    memory = MemoryCellar({"new": [SOURCE], "cellar": [SOURCE, OTHER]})
    _pending(memory)
    result = _run(memory, target_size=1)
    assert result.added == 0 and result.removed_from_cellar == 1
    assert memory.playlists["cellar"] == [OTHER]
    assert result.results[0].action == "already present"


def test_pending_source_already_removed_only_clears_checkpoint_and_audits() -> None:
    """A lost deletion response does not trigger another append or removal."""
    memory = MemoryCellar({"new": [SOURCE], "cellar": []})
    _pending(memory)
    result = _run(memory)
    assert result.added == result.removed_from_cellar == 0
    assert "append" not in memory.calls and "remove" not in memory.calls
    assert len(memory.audits) == 1


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize(
    "boundary,occurrence",
    [("append", 1), ("remove", 1), ("save", 1), ("save", 2), ("audit", 1)],
)
def test_partial_failure_preserves_remote_and_checkpoint_recovery(
    boundary: str, occurrence: int, accepted: bool
) -> None:
    """Resume from accepted writes without introducing rollback or duplicate markers.

    Args:
        boundary: Effect interrupted once.
        occurrence: Which pending checkpoint or effect is interrupted.
        accepted: Whether acceptance precedes failure.
    """
    memory = MemoryCellar(
        {"new": [], "cellar": [SOURCE]},
        failure=boundary,
        occurrence=occurrence,
        accepted=accepted,
    )
    with pytest.raises(RuntimeError, match=f"{boundary} interrupted"):
        _run(memory)
    _run(memory)
    assert memory.playlists == {"new": [SOURCE], "cellar": []}
    assert memory.calls["append"] == (2 if boundary == "append" and not accepted else 1)
    assert len(memory.audits) <= 1


def test_preview_pending_transfer_does_not_clear_existing_checkpoint() -> None:
    """The standalone preview path retains its supplied pending state."""
    memory = MemoryCellar({"new": [], "cellar": [SOURCE]})
    _pending(memory)
    before = deepcopy(memory.stored)
    result = _run(memory, dry_run=True)
    assert result.added == result.removed_from_cellar == 1
    assert memory.stored == before
    assert "save" not in memory.calls


def test_empty_cellar_has_zero_results() -> None:
    """No sources means no mutation, presentation or audit."""
    memory = MemoryCellar({"new": [], "cellar": []})
    result = _run(memory)
    assert result.results == ()
    assert (result.before, result.after) == (0, 0)
