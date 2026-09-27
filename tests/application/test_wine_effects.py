"""Album, continuation and restart effects of already accepted New Wine plans."""

from copy import deepcopy
from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.application.new_wine import flush_new_wine
from spotify_manager.application.new_wine import new_run
from spotify_manager.application.new_wine_execution import WineExecution
from spotify_manager.application.new_wine_plans import drop_plan
from spotify_manager.application.new_wine_plans import progression_plan
from spotify_manager.application.new_wine_plans import record_evaluation
from spotify_manager.application.release_evaluation import evaluate_release
from tests.support.listening_values import release_track
from tests.support.new_wine_memory import ALBUM
from tests.support.new_wine_memory import FOLLOWUP
from tests.support.new_wine_memory import OPTIONS
from tests.support.new_wine_memory import SOURCE
from tests.support.new_wine_memory import TARGET
from tests.support.new_wine_memory import MemoryWine
from tests.support.new_wine_memory import dependencies


def _saved_plan(memory: MemoryWine, plan: dict[str, object]) -> dict[str, object]:
    run = new_run(OPTIONS, (SOURCE,), memory.clock)
    entries = cast(list[dict[str, object]], run["entries"])
    entries[0]["plan"] = plan
    memory.stored["active_run"] = run
    memory.events.clear()
    memory.counts.clear()
    return entries[0]


def _completion(*, liked: bool = True) -> dict[str, object]:
    plan = progression_plan("sauvignon", ALBUM, release_track("source"), liked, 0)
    evaluation = evaluate_release(ALBUM, (release_track("source"),), {"source": liked})
    record_evaluation(plan, evaluation)
    return plan


def _drop() -> dict[str, object]:
    return drop_plan(
        ALBUM,
        evaluate_release(ALBUM, (TARGET,), {}),
        current_liked=False,
        consecutive_unliked=3,
        reason="three_consecutive_unliked",
    )


def _names(memory: MemoryWine) -> list[str]:
    return [name for name, value in memory.events]


def _executor(memory: MemoryWine, *, dry_run: bool = False) -> WineExecution:
    deps = dependencies(memory)
    return WineExecution(
        memory,
        deps.observations,
        "new",
        "sauvignon",
        {"source"},
        set(),
        memory.stored,
        {},
        dry_run,
        deps.presentation,
        deps.clock,
    )


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("source_present", [False, True])
def test_qualified_album_mirror_runs_even_when_source_already_removed(
    saved: bool, source_present: bool
) -> None:
    """Qualification effects precede the source-absence guard on resumed plans.

    Args:
        saved: Existing album membership.
        source_present: Whether source removal was previously accepted.
    """
    memory = MemoryWine(saved_albums={"album"} if saved else set())
    _saved_plan(memory, _completion())
    memory.playlists["new"] = [SOURCE] if source_present else []
    assert flush_new_wine(OPTIONS, dependencies(memory)).sent_to_sauvignon == 1
    assert memory.counts.get("save_album", 0) == (not saved)
    assert memory.counts["mirror"] == 1
    assert memory.counts.get("append", 0) == source_present
    assert memory.saved_albums == {"album"}


def test_rejected_completion_leaves_album_unsaved_but_still_routes_marker() -> None:
    """Sauvignon progression does not depend on satisfying the library keep rule."""
    memory = MemoryWine()
    _saved_plan(memory, _completion(liked=False))
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert result.sent_to_sauvignon == 1
    assert not {"saved", "save_album", "mirror"}.intersection(_names(memory))
    assert memory.playlists["sauvignon"] == [release_track("source")]


@pytest.mark.parametrize("count", [None, -1, True, 0, 1, 2])
def test_old_sauvignon_plan_fills_missing_evaluation_at_existing_boundary(
    count: int | None,
) -> None:
    """Saved canonical counts retain Python slicing, including bool/negative values.

    Args:
        count: Optional historical canonical track count.
    """
    memory = MemoryWine(liked={"source", "target"})
    plan = progression_plan("sauvignon", ALBUM, TARGET, True, 0)
    plan["canonical_track_count"] = count
    _saved_plan(memory, plan)
    result = flush_new_wine(OPTIONS, dependencies(memory))
    expected = len((SOURCE, TARGET)[:count]) if isinstance(count, int) else 2
    assert result.results[0].album_total_tracks == expected
    names = _names(memory)
    assert names.index("tracks") < names.index("save") < names.index("append")


@pytest.mark.parametrize("boundary", ["save_album", "mirror"])
@pytest.mark.parametrize("accepted", [False, True])
def test_kept_album_retry_refreshes_mirror_before_playlist_changes(
    boundary: str, accepted: bool
) -> None:
    """Restart reobserves saved membership but retries mirror publication.

    Args:
        boundary: Album effect to interrupt.
        accepted: Whether acceptance preceded the interruption.
    """
    memory = MemoryWine(failure=boundary, accepted=accepted)
    _saved_plan(memory, _completion())
    with pytest.raises(RuntimeError, match=boundary):
        flush_new_wine(OPTIONS, dependencies(memory))
    assert memory.playlists["new"] == [SOURCE]
    flush_new_wine(OPTIONS, dependencies(memory))
    assert memory.saved_albums == {"album"}
    assert memory.counts["save_album"] == (
        2 if boundary == "save_album" and not accepted else 1
    )
    assert memory.counts["append"] == memory.counts["remove"] == 1


@pytest.mark.parametrize("saved", [False, True])
def test_drop_uses_unsave_then_mirror_then_recovery_audit_then_checkpoint(
    saved: bool,
) -> None:
    """Album deletion effects precede marker removal and final result audit.

    Args:
        saved: Whether the album currently needs removal.
    """
    memory = MemoryWine(saved_albums={"album"} if saved else set())
    _saved_plan(memory, _drop())
    result = flush_new_wine(OPTIONS, dependencies(memory))
    assert result.albums_unsaved == saved
    assert memory.saved_albums == set()
    names = _names(memory)
    if saved:
        start = names.index("unsave_album")
        assert names[start : start + 5] == [
            "unsave_album",
            "remove_mirror",
            "removed_audit",
            "save",
            "message:removed_album",
        ]
        return
    assert "unsave_album" not in names


@pytest.mark.parametrize(
    "boundary", ["unsave_album", "remove_mirror", "removed_audit", "save"]
)
@pytest.mark.parametrize("accepted", [False, True])
def test_unsave_interruption_retains_existing_partial_effect_behavior(
    boundary: str, accepted: bool
) -> None:
    """Already absent albums do not replay downstream removal effects on restart.

    Args:
        boundary: Removal-chain effect to interrupt.
        accepted: Whether the interruption followed acceptance.
    """
    memory = MemoryWine(saved_albums={"album"}, failure=boundary, accepted=accepted)
    _saved_plan(memory, _drop())
    with pytest.raises(RuntimeError, match=boundary):
        flush_new_wine(OPTIONS, dependencies(memory))
    result = flush_new_wine(OPTIONS, dependencies(memory))
    checkpointed = boundary == "save" and accepted
    retried_unsave = boundary == "unsave_album" and not accepted
    assert result.albums_unsaved == (checkpointed or retried_unsave)
    assert memory.saved_albums == set() and memory.playlists["new"] == []
    assert memory.counts["unsave_album"] == (2 if retried_unsave else 1)
    assert memory.counts.get("remove_mirror", 0) == (
        0 if boundary == "unsave_album" and accepted else 1
    )


def test_persisted_unsave_flag_prevents_repeated_remote_removal() -> None:
    """Even inconsistent saved membership does not override accepted removal intent."""
    memory = MemoryWine(saved_albums={"album"})
    plan = _drop()
    plan["album_unsaved"] = True
    _saved_plan(memory, plan)
    assert flush_new_wine(OPTIONS, dependencies(memory)).albums_unsaved == 1
    assert "unsave_album" not in _names(memory)


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_continuation_is_secured_before_source_removal_and_owns_next_streak(
    dry_run: bool, existing: bool
) -> None:
    """Follow-up intent supersedes the primary target's progress record.

    Args:
        dry_run: Whether only membership projections should change.
        existing: Whether the follow-up marker is already present.
    """
    memory = MemoryWine()
    plan = progression_plan("advance", ALBUM, release_track("primary"), False, 2)
    plan.update(
        continuation_release=asdict(FOLLOWUP), continuation_target=asdict(TARGET)
    )
    entry = _saved_plan(memory, plan)
    execution = _executor(memory, dry_run=dry_run)
    if existing:
        execution.destination_ids.add("target")
    result = execution.execute(SOURCE, entry, plan)
    assert result.continuation_track == "target"
    assert execution.destination_ids == {"primary", "target"}
    assert memory.counts.get("append", 0) == (0 if dry_run else 2 - existing)
    assert entry["status"] == ("pending" if dry_run else "completed")
    if not dry_run:
        assert set(execution.progress) == {"target"}
        assert (
            cast(dict[str, object], execution.progress["target"])[
                "prior_unliked_streak"
            ]
            == 0
        )


def test_absent_source_suppresses_continuation_but_preserves_progress_record() -> None:
    """Resume does not recreate any markers after the original source is gone."""
    memory = MemoryWine()
    plan = _completion(liked=False)
    plan.update(
        continuation_release=asdict(FOLLOWUP), continuation_target=asdict(TARGET)
    )
    entry = _saved_plan(memory, plan)
    execution = _executor(memory)
    execution.destination_ids.clear()
    execution.execute(SOURCE, entry, plan)
    assert memory.counts.get("append", 0) == 0
    assert set(execution.progress) == {"target"}


@pytest.mark.parametrize("action", ["advance", "sauvignon", "drop"])
def test_preview_effects_keep_remote_state_and_checkpoints_untouched(
    action: str,
) -> None:
    """Preview still observes album membership and returns unsave eligibility.

    Args:
        action: Accepted plan category.
    """
    memory = MemoryWine(saved_albums={"album"})
    plans = {
        "advance": progression_plan("advance", ALBUM, TARGET, False, 1),
        "sauvignon": _completion(),
        "drop": _drop(),
    }
    plan = plans[action]
    entry = _saved_plan(memory, plan)
    original = deepcopy(memory.stored)
    result = _executor(memory, dry_run=True).execute(SOURCE, entry, plan)
    assert result.dry_run and result.album_unsaved == (action == "drop")
    assert memory.stored == original
    assert memory.saved_albums == {"album"} and memory.playlists["new"] == [SOURCE]
    assert not {
        "save",
        "append",
        "remove",
        "mirror",
        "unsave_album",
        "save_album",
    }.intersection(_names(memory))


def test_duplicate_primary_markers_are_not_appended_again() -> None:
    """Live projected membership prevents repeated primary writes."""
    memory = MemoryWine()
    plan = progression_plan("advance", ALBUM, TARGET, False, 1)
    entry = _saved_plan(memory, plan)
    execution = _executor(memory)
    execution.destination_ids.add("target")
    execution.execute(SOURCE, entry, plan)
    assert "append" not in _names(memory)


def test_existing_sauvignon_marker_is_retained_without_duplicate_append() -> None:
    """Album qualification still runs when the destination marker is already present."""
    memory = MemoryWine()
    plan = _completion()
    entry = _saved_plan(memory, plan)
    execution = _executor(memory)
    execution.sauvignon_ids.add("source")
    execution.execute(SOURCE, entry, plan)
    assert "append" not in _names(memory) and memory.saved_albums == {"album"}
