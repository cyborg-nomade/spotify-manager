"""Discovery reconciliation preserves recovery, mirror and preview boundaries."""

import pytest

from spotify_manager.application.discovery_library import DiscoveryLibraryReconciliation
from spotify_manager.application.release_evaluation import evaluate_catalog_release
from spotify_manager.models.lookups import AlbumEvaluation
from tests.support.discovery_effects import MemoryLibrary
from tests.support.discovery_values import release
from tests.support.discovery_values import track


ALBUM = release("album")


def _evaluation(keep: bool) -> AlbumEvaluation:
    return evaluate_catalog_release(ALBUM, (track("one"),), {"one": keep})


def _service(
    memory: MemoryLibrary, preview: bool = False
) -> DiscoveryLibraryReconciliation:
    return DiscoveryLibraryReconciliation(memory, memory, memory, preview)


@pytest.mark.parametrize(
    ("saved", "keep", "preview", "action", "effects"),
    [
        (False, True, False, "saved", ["saved", "save", "mirror", "audit", "message"]),
        (True, True, False, "kept", ["saved", "mirror", "audit", "message"]),
        (False, False, False, "absent", ["saved", "mirror", "audit", "message"]),
        (
            True,
            False,
            False,
            "removed",
            ["saved", "remove", "recovery", "mirror", "audit", "message"],
        ),
        (False, True, True, "would save", ["saved", "audit", "message"]),
        (True, True, True, "kept", ["saved", "audit", "message"]),
        (False, False, True, "absent", ["saved", "audit", "message"]),
        (True, False, True, "would remove", ["saved", "audit", "message"]),
    ],
)
def test_reconciliation_effect_order(
    saved: bool, keep: bool, preview: bool, action: str, effects: list[str]
) -> None:
    """Every membership/decision/preview combination retains its original effects."""
    memory = MemoryLibrary(saved)
    evaluation = _evaluation(keep)
    assert _service(memory, preview).reconcile(ALBUM, evaluation) == action
    assert [name for name, value in memory.events] == effects
    assert memory.is_saved == (saved if preview else keep)
    assert memory.events[-2] == (
        "audit",
        (
            "release_library_checked",
            {
                "artist": "Artist",
                "release": "album",
                "release_id": "album",
                "liked_tracks": int(keep),
                "total_tracks": 1,
                "decision": evaluation.decision,
                "action": action,
                "dry_run": preview,
            },
        ),
    )
    assert memory.events[-1] == ("message", (ALBUM, evaluation, action, preview))


@pytest.mark.parametrize(
    "boundary", ["saved", "remove", "recovery", "mirror", "audit", "message"]
)
def test_removal_failure_stops_later_effects(boundary: str) -> None:
    """An interrupted removal never advances to a later effect boundary."""
    memory = MemoryLibrary(True, boundary)
    expected = ["saved", "remove", "recovery", "mirror", "audit", "message"]
    with pytest.raises(OSError, match=boundary):
        _service(memory).reconcile(ALBUM, _evaluation(False))
    assert [name for name, value in memory.events] == expected[
        : expected.index(boundary) + 1
    ]


def test_save_failure_leaves_mirror_and_audits_untouched() -> None:
    """A failed remote save does not project success into local files."""
    memory = MemoryLibrary(False, "save")
    with pytest.raises(OSError, match="save"):
        _service(memory).reconcile(ALBUM, _evaluation(True))
    assert memory.events == [("saved", ALBUM), ("save", ALBUM)]
    assert not memory.is_saved


def test_restarted_removal_repairs_mirror_without_repeating_recovery_record() -> None:
    """A lost recovery write after removal retains the legacy absent-on-retry path."""
    memory = MemoryLibrary(True, "recovery")
    service = _service(memory)
    with pytest.raises(OSError, match="recovery"):
        service.reconcile(ALBUM, _evaluation(False))
    assert not memory.is_saved
    memory.fail_at = None
    memory.events.clear()
    assert service.reconcile(ALBUM, _evaluation(False)) == "absent"
    assert [name for name, value in memory.events] == [
        "saved",
        "mirror",
        "audit",
        "message",
    ]


def test_unknown_decision_retains_removal_semantics() -> None:
    """Only the exact keep decision grants saved membership."""
    memory = MemoryLibrary(True)
    evaluation = _evaluation(True).model_copy(update={"decision": "unknown"})
    assert _service(memory).reconcile(ALBUM, evaluation) == "removed"
    assert not memory.is_saved
