"""New Wine use cases preserve choices, observations and durable effect order."""

from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.new_wine import flush_new_wine
from spotify_manager.application.new_wine import new_run
from spotify_manager.application.new_wine_plans import progression_plan
from spotify_manager.application.new_wine_values import NewWineConfigError
from spotify_manager.application.new_wine_values import NewWineError
from spotify_manager.application.new_wine_values import NewWineStateError
from tests.support.listening_values import release_track
from tests.support.new_wine_memory import ALBUM
from tests.support.new_wine_memory import NOW
from tests.support.new_wine_memory import OPTIONS
from tests.support.new_wine_memory import SOURCE
from tests.support.new_wine_memory import TARGET
from tests.support.new_wine_memory import MemoryWine
from tests.support.new_wine_memory import dependencies


def _names(memory: MemoryWine) -> list[str]:
    return [name for name, value in memory.events]


def _run(memory: MemoryWine) -> dict[str, object]:
    return cast(dict[str, object], memory.stored["active_run"])


def _entries(memory: MemoryWine) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], _run(memory)["entries"])


def _pending(memory: MemoryWine, plan: dict[str, object] | None = None) -> None:
    memory.stored["active_run"] = new_run(OPTIONS, (SOURCE,), memory.clock)
    _entries(memory)[0]["plan"] = plan
    memory.events.clear()
    memory.counts.clear()


def test_advance_observes_source_then_checkpoints_before_mutation_and_audit() -> None:
    """A fresh run secures replacement before removal and completion before audit."""
    memory = MemoryWine()
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert (result.advanced, result.processed, result.resumed) == (1, 1, False)
    assert _names(memory) == [
        "playlist",
        "playlist",
        "load",
        "clock",
        "clock",
        "save",
        "progress",
        "tracks",
        "likes",
        "likes",
        "save",
        "append",
        "message:advanced",
        "remove",
        "message:removed",
        "clock",
        "save",
        "audit",
        "progress",
        "clock",
        "save",
    ]
    progress = cast(dict[str, dict[str, object]], memory.stored["track_progress"])
    assert progress["target"]["prior_unliked_streak"] == 1
    assert progress["target"]["updated_at"] == NOW.isoformat()
    assert _run(memory)["status"] == "completed"
    assert memory.playlists["new"] == [TARGET]


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("boundary", ["append", "remove"])
def test_restart_does_not_duplicate_accepted_marker_effects(
    boundary: str, accepted: bool
) -> None:
    """A saved plan reconciles live membership before retrying its effects.

    Args:
        boundary: Playlist effect to interrupt.
        accepted: Whether the interrupted effect already took place.
    """
    memory = MemoryWine(failure=boundary, accepted=accepted)
    with pytest.raises(RuntimeError, match=boundary):
        flush_new_wine(OPTIONS, dependencies(memory))
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert result.resumed and result.advanced == 1
    assert memory.playlists["new"] == [TARGET]
    assert memory.counts["tracks"] == 1
    assert memory.counts[boundary] == (1 if accepted else 2)


@pytest.mark.parametrize("accepted", [False, True])
def test_completion_checkpoint_failure_preserves_original_resume_semantics(
    accepted: bool,
) -> None:
    """Accepted completion suppresses repeated audit; unaccepted completion is retried.

    Args:
        accepted: Whether the completion checkpoint was durable before failure.
    """
    memory = MemoryWine(failure="save", occurrence=3, accepted=accepted)
    with pytest.raises(RuntimeError, match="save"):
        flush_new_wine(OPTIONS, dependencies(memory))
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert result.processed == (0 if accepted else 1)
    assert len(memory.audits) == (0 if accepted else 1)
    assert memory.playlists["new"] == [TARGET]


def test_audit_failure_after_completion_is_not_replayed() -> None:
    """The existing checkpoint-before-audit boundary can leave a missing log row."""
    memory = MemoryWine(failure="audit")
    with pytest.raises(RuntimeError, match="audit"):
        flush_new_wine(OPTIONS, dependencies(memory))
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert result.processed == 0
    assert memory.audits == []
    assert _run(memory)["status"] == "completed"


def test_preview_ignores_active_run_and_audits_without_remote_or_durable_writes() -> (
    None
):
    """Preview uses fresh markers and projects refill membership after progression."""
    memory = MemoryWine()
    _pending(memory, {"invalid": True})
    original = deepcopy(memory.stored)
    options = replace(OPTIONS, dry_run=True, cellar="cellar", no_discovery=True)
    result = flush_new_wine(options, replace(dependencies(memory), progress=None))
    assert result.dry_run and not result.resumed and result.advanced == 1
    assert memory.stored == original and memory.playlists["new"] == [SOURCE]
    assert len(memory.audits) == 1
    assert not {"save", "append", "remove", "progress"}.intersection(_names(memory))
    assert ("refill", ("cellar", True, True, {"target"})) in memory.events


@pytest.mark.parametrize("choice", ["skip", "quit"])
def test_endpoint_skip_and_pause_have_distinct_audit_and_completion(
    choice: str,
) -> None:
    """Neither choice persists an endpoint; only skip produces an audited result.

    Args:
        choice: Operator endpoint response.
    """
    memory = MemoryWine(endpoints=[choice])
    result = flush_new_wine(
        replace(OPTIONS, endpoint_mode=True, cellar="cellar"), dependencies(memory)
    )
    assert result.paused == (choice == "quit")
    assert result.skipped == (choice == "skip")
    assert memory.playlists["new"] == [SOURCE]
    assert _entries(memory)[0]["endpoint_choice"] is None
    assert memory.counts.get("progress") == 1
    assert memory.counts.get("refill", 0) == (choice == "skip")
    assert len(memory.audits) == (choice == "skip")


def test_skip_audit_failure_leaves_entry_pending_for_restart() -> None:
    """Unlike completed effects, skipped entries are checkpointed after their audit."""
    memory = MemoryWine(endpoints=["skip", "skip"], failure="audit")
    options = replace(OPTIONS, endpoint_mode=True)
    with pytest.raises(RuntimeError, match="audit"):
        flush_new_wine(options, dependencies(memory))
    assert _entries(memory)[0]["status"] == "pending"
    assert flush_new_wine(options, dependencies(memory)).skipped == 1
    assert memory.counts["endpoint"] == 2


def test_cutoff_checkpoint_precedes_canonical_evaluation() -> None:
    """A chosen endpoint limits album evaluation and persists in the result."""
    memory = MemoryWine(endpoints=["cutoff"], liked={"source"})
    result = flush_new_wine(replace(OPTIONS, endpoint_mode=True), dependencies(memory))
    assert result.sent_to_sauvignon == 1
    assert result.results[0].album_total_tracks == 1
    assert result.results[0].canonical_cutoff_track == "source"
    assert memory.playlists["sauvignon"] == [release_track("source")]
    assert _entries(memory)[0]["endpoint_choice"] == "cutoff"
    names = _names(memory)
    assert names[names.index("endpoint") + 1] == "save"
    assert names.index("save_album") < names.index("mirror") < names.index("append")


@pytest.mark.parametrize("endpoint", ["continue", "bogus"])
def test_endpoint_validation_preserves_current_marker(endpoint: str) -> None:
    """Accepted continue advances; unsupported answers raise before mutations.

    Args:
        endpoint: Operator response to validate.
    """
    memory = MemoryWine(endpoints=[endpoint])
    options = replace(OPTIONS, endpoint_mode=True)
    if endpoint == "bogus":
        with pytest.raises(NewWineError, match="endpoint choice"):
            flush_new_wine(options, dependencies(memory))
        assert memory.playlists["new"] == [SOURCE]
        return
    assert flush_new_wine(options, dependencies(memory)).advanced == 1
    assert _entries(memory)[0]["endpoint_choice"] == "continue"


def test_missing_endpoint_reader_fails_after_initial_checkpoint() -> None:
    """Configuration validation keeps the original state/read ordering."""
    memory = MemoryWine()
    with pytest.raises(NewWineConfigError, match="choice reader"):
        flush_new_wine(
            replace(OPTIONS, endpoint_mode=True),
            replace(dependencies(memory), endpoint=None),
        )
    assert _names(memory) == ["playlist", "playlist", "load", "clock", "clock", "save"]
    assert _run(memory)["status"] == "active"


@pytest.mark.parametrize(
    "entries,progress,error",
    [(None, {}, "entries"), ([], None, "progress"), ([None], {}, "entry")],
)
def test_invalid_saved_records_fail_at_their_original_boundary(
    entries: object, progress: object, error: str
) -> None:
    """Durable outer record validation precedes source processing.

    Args:
        entries: Saved entry sequence.
        progress: Saved streak records.
        error: Existing diagnostic fragment.
    """
    memory = MemoryWine()
    _pending(memory)
    _run(memory)["entries"] = entries
    memory.stored["track_progress"] = progress
    with pytest.raises(NewWineStateError, match=error):
        flush_new_wine(OPTIONS, dependencies(memory))
    assert memory.playlists["new"] == [SOURCE]


@pytest.mark.parametrize(
    "active",
    [None, [], {"status": "completed"}, {"status": "active", "playlist_id": "other"}],
)
def test_nonmatching_active_run_is_replaced(active: object) -> None:
    """Only active runs for the same playlist are resumable.

    Args:
        active: Non-resumable saved value.
    """
    memory = MemoryWine()
    memory.stored["active_run"] = active
    assert not flush_new_wine(OPTIONS, dependencies(memory)).resumed


def test_saved_refill_settings_take_precedence() -> None:
    """Restart retains saved cellar and eligibility settings, including false."""
    memory = MemoryWine()
    _pending(memory)
    _run(memory).update(wine_cellar_playlist_id="saved-cellar", no_discovery=False)
    result = flush_new_wine(
        replace(OPTIONS, cellar="configured", no_discovery=True), dependencies(memory)
    )
    assert result.refill is not None
    assert ("refill", ("saved-cellar", False, False, None)) in memory.events


def test_old_run_missing_refill_settings_uses_current_configuration() -> None:
    """Older durable layouts retain their fallback behavior."""
    memory = MemoryWine()
    _pending(memory)
    del _run(memory)["no_discovery"]
    _run(memory)["wine_cellar_playlist_id"] = 17
    flush_new_wine(
        replace(OPTIONS, cellar="configured", no_discovery=True), dependencies(memory)
    )
    assert ("refill", ("configured", True, False, None)) in memory.events


def test_legacy_unknown_plan_action_still_removes_source_and_preserves_result() -> None:
    """Refactoring does not tighten the existing tolerant durable action decoder."""
    memory = MemoryWine()
    plan = progression_plan("future-action", ALBUM, None, False, 1)
    _pending(memory, plan)
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert str(result.results[0].action) == "future-action"
    assert memory.playlists["new"] == []
    assert "tracks" not in _names(memory)


def test_invalid_non_dictionary_saved_plan_is_replanned() -> None:
    """Legacy non-null scalar plans retain the original fallback to planning."""
    memory = MemoryWine()
    _pending(memory)
    _entries(memory)[0]["plan"] = "not a plan"
    assert flush_new_wine(OPTIONS, dependencies(memory)).advanced == 1


def test_source_absent_does_not_validate_or_recreate_missing_replacement() -> None:
    """Resume retains New Wine's original tolerance of missing replacements."""
    memory = MemoryWine()
    _pending(memory, progression_plan("advance", ALBUM, TARGET, False, 1))
    memory.playlists["new"] = []
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert result.advanced == 1 and memory.playlists["new"] == []
    assert "message:resumed" in _names(memory)
    assert "append" not in _names(memory)
