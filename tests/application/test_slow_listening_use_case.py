"""Exercise resumable Slow Listening execution against explicit memory ports."""

from copy import deepcopy
from dataclasses import asdict
from dataclasses import replace
from datetime import datetime
from typing import cast

import pytest

from spotify_manager.application.slow_listening import _finished
from spotify_manager.application.slow_listening import flush_slow_listening
from spotify_manager.application.slow_listening import new_run
from spotify_manager.application.slow_listening_values import SlowListeningStateError
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.slow_listening_memory import FIRST
from tests.support.slow_listening_memory import NOW
from tests.support.slow_listening_memory import SOURCE
from tests.support.slow_listening_memory import TARGET
from tests.support.slow_listening_memory import MemorySlowListening


def _clock() -> datetime:
    return NOW


def _resume(memory: MemorySlowListening, plan: object = None) -> dict[str, object]:
    run = new_run("slow", (SOURCE,), _clock)
    entries = cast(list[dict[str, object]], run["entries"])
    entries[0]["plan"] = plan
    memory.state["active_run"] = run
    return entries[0]


def _plan(action: str = "advance") -> dict[str, object]:
    return {
        "action": action,
        "target": asdict(TARGET),
        "target_release": asdict(FIRST),
        "reason": None,
        "skipped_candidates": [],
    }


def _event_names(memory: MemorySlowListening) -> list[str]:
    return [event[0] for event in memory.events]


@pytest.mark.parametrize("dry_run", [False, True])
def test_complete_effect_order_and_preview_audit(dry_run: bool) -> None:
    """Preserve every observation, effect, message and checkpoint boundary.

    Args:
        dry_run: Whether to preview while still writing the original audit.
    """
    memory = MemorySlowListening([SOURCE])
    result = flush_slow_listening("slow", memory.dependencies(), dry_run=dry_run)
    expected = ["playlist", "load", "clock", "clock"]
    expected += [] if dry_run else ["save"]
    expected += ["progress", "catalog", "tracks", "choose"]
    expected += [] if dry_run else ["save", "append"]
    expected += ["added"] + ([] if dry_run else ["remove"]) + ["removed", "audit"]
    expected += [] if dry_run else ["save"]
    expected += ["progress"] + ([] if dry_run else ["clock", "save"])
    assert _event_names(memory) == expected
    assert (result.total, result.processed, result.advanced, result.resumed) == (
        1,
        1,
        1,
        False,
    )
    assert len(memory.audits) == 1
    assert [track.spotify_id for track in memory.live] == (
        ["source"] if dry_run else ["target"]
    )


def test_two_marker_limit_and_run_scoped_catalog_cache() -> None:
    """Duplicate markers share observations while the third marker is untouched."""
    third = replace(SOURCE, spotify_id="third")
    memory = MemorySlowListening([SOURCE, SOURCE, third])
    result = flush_slow_listening("slow", memory.dependencies(progress=False))
    assert (result.total, result.processed, result.advanced) == (2, 2, 2)
    assert memory.counts["catalog"] == memory.counts["tracks"] == 1
    assert memory.counts["append"] == memory.counts["remove"] == 1
    assert "resumed" in _event_names(memory)
    assert [track.spotify_id for track in memory.live] == ["third", "target"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_skipped_source_audits_before_output_and_has_no_completion_progress(
    dry_run: bool,
) -> None:
    """An ineligible source retains its playlist marker and original audit timing.

    Args:
        dry_run: Whether to omit namespace writes.
    """
    memory = MemorySlowListening([SOURCE], releases=())
    result = flush_slow_listening("slow", memory.dependencies(), dry_run=dry_run)
    assert result.skipped == 1
    assert memory.live == [SOURCE]
    assert memory.counts["progress"] == 1
    assert _event_names(memory).index("audit") < _event_names(memory).index("skipped")
    assert len(memory.audits) == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_final_track_acknowledges_and_refreshes_only_during_real_execution(
    dry_run: bool,
) -> None:
    """The completion callback may edit the playlist before the next entry.

    Args:
        dry_run: Whether to suppress the callback and fresh playlist read.
    """
    memory = MemorySlowListening(
        [SOURCE],
        releases=(FIRST,),
        release_tracks={"first": (release_track("source"),)},
    )
    memory.replacement = [playlist_track("replacement", FIRST)]
    result = flush_slow_listening("slow", memory.dependencies(), dry_run=dry_run)
    assert result.completed_artists == 1
    assert memory.counts.get("complete", 0) == int(not dry_run)
    assert memory.counts["playlist"] == (1 if dry_run else 2)
    assert [track.spotify_id for track in memory.live] == (
        ["source"] if dry_run else ["replacement"]
    )
    assert result.results[0].reason == "last track of the last studio release"


def test_pause_saves_skips_then_resumes_without_asking_them_again() -> None:
    """A declined candidate persists before a later quit and is not asked twice."""
    memory = MemorySlowListening([SOURCE], choices=["skip", "quit"])
    memory.release_tracks["first"] += (release_track("last"),)
    first = flush_slow_listening("slow", memory.dependencies())
    assert first.paused and first.processed == 0
    assert memory.counts["save"] == 2
    assert not memory.audits
    second = flush_slow_listening("slow", memory.dependencies())
    assert second.resumed and not second.paused
    assert second.results[0].target_track == "last"
    assert second.results[0].skipped_candidates == ("target (First)",)
    assert memory.counts["choose"] == 3


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("boundary", ["append", "remove", "audit", "save"])
def test_resume_after_accepted_or_rejected_effect(
    boundary: str, accepted: bool
) -> None:
    """Restart from the last accepted checkpoint and live effects, avoiding duplicates.

    Args:
        boundary: Effect to interrupt once.
        accepted: Whether the effect is accepted before the response fails.
    """
    memory = MemorySlowListening([SOURCE], failure=boundary, accepted=accepted)
    memory.occurrence = 3 if boundary == "save" else 1
    with pytest.raises(RuntimeError, match=f"{boundary} interrupted"):
        flush_slow_listening("slow", memory.dependencies())
    result = flush_slow_listening("slow", memory.dependencies())
    assert result.resumed
    assert [track.spotify_id for track in memory.live] == ["target"]
    assert memory.counts["append"] == (
        2 if boundary == "append" and not accepted else 1
    )
    assert result.processed == (0 if boundary == "save" and accepted else 1)


@pytest.mark.parametrize(
    "boundary", ["playlist", "load", "catalog", "tracks", "choose", "progress", "clock"]
)
def test_read_choice_and_cancellation_failures_do_not_mutate_playlist(
    boundary: str,
) -> None:
    """Errors before a decision stop execution before remote writes.

    Args:
        boundary: Observation or callback to interrupt.
    """
    memory = MemorySlowListening([SOURCE], failure=boundary)
    with pytest.raises(RuntimeError, match=f"{boundary} interrupted"):
        flush_slow_listening("slow", memory.dependencies())
    assert memory.live == [SOURCE]
    assert not memory.audits


def test_saved_acknowledgement_survives_refresh_failure() -> None:
    """An acknowledged completion survives failure of the subsequent freshness read."""
    memory = MemorySlowListening(
        [SOURCE],
        releases=(FIRST,),
        release_tracks={"first": (release_track("source"),)},
        failure="playlist",
        occurrence=2,
    )
    with pytest.raises(RuntimeError, match="playlist interrupted"):
        flush_slow_listening("slow", memory.dependencies())
    result = flush_slow_listening("slow", memory.dependencies())
    assert result.resumed and result.completed_artists == 1
    assert memory.counts["complete"] == 1
    assert memory.live == []


def test_lost_completion_response_repeats_unacknowledged_callback() -> None:
    """Preserve the original retry exposure when acknowledgement itself fails."""
    memory = MemorySlowListening(
        [SOURCE],
        releases=(FIRST,),
        release_tracks={"first": (release_track("source"),)},
        failure="complete",
        accepted=True,
    )
    with pytest.raises(RuntimeError, match="complete interrupted"):
        flush_slow_listening("slow", memory.dependencies())
    flush_slow_listening("slow", memory.dependencies())
    assert memory.counts["complete"] == 2
    assert memory.counts["remove"] == 1


def test_missing_source_and_missing_replacement_is_an_error() -> None:
    """A saved advance cannot silently complete when neither marker remains."""
    memory = MemorySlowListening()
    _resume(memory, _plan())
    with pytest.raises(
        SlowListeningStateError, match="absent but its planned replacement"
    ):
        flush_slow_listening("slow", memory.dependencies())
    assert not memory.audits


def test_existing_replacement_is_not_appended_again() -> None:
    """Existing target membership is preserved while removing the source."""
    memory = MemorySlowListening([SOURCE, playlist_track("target", FIRST)])
    _resume(memory, _plan())
    result = flush_slow_listening("slow", memory.dependencies())
    assert result.advanced == 1
    assert "append" not in _event_names(memory)
    assert "added" not in _event_names(memory)
    assert [track.spotify_id for track in memory.live] == ["target"]


@pytest.mark.parametrize("action", ["unknown", "advance"])
def test_saved_action_without_target_keeps_tolerant_legacy_behavior(
    action: str,
) -> None:
    """Do not add stricter plan validation while moving the application boundary.

    Args:
        action: Persisted action with no target.
    """
    memory = MemorySlowListening([SOURCE])
    plan = _plan(action)
    plan.update(
        target=None, target_release=None, skipped_candidates=[1, "Kept"], reason=7
    )
    _resume(memory, plan)
    result = flush_slow_listening("slow", memory.dependencies())
    assert memory.live == [SOURCE]
    assert result.results[0].skipped_candidates == ("Kept",)
    assert result.results[0].reason == "7"


def test_non_null_non_mapping_plan_is_recomputed_without_overwriting_saved_field() -> (
    None
):
    """Preserve the legacy distinction between missing and malformed saved plans."""
    memory = MemorySlowListening([SOURCE])
    _resume(memory, "legacy-invalid-plan")
    result = flush_slow_listening("slow", memory.dependencies())
    run = cast(dict[str, object], memory.state["active_run"])
    entry = cast(list[dict[str, object]], run["entries"])[0]
    assert result.advanced == 1
    assert entry["plan"] == "legacy-invalid-plan"


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("entries", None, "invalid entries"),
        ("entries", [None], "invalid entry"),
        ("release_orders", None, "release orders are invalid"),
    ],
)
def test_invalid_saved_run_fails_without_losing_its_checkpoint(
    field: str, value: object, message: str
) -> None:
    """Retain validation timing and preserve the saved namespace on failure.

    Args:
        field: Run or namespace field to corrupt.
        value: Invalid durable value.
        message: Original error text fragment.
    """
    memory = MemorySlowListening([SOURCE])
    _resume(memory)
    parent = (
        memory.state
        if field == "release_orders"
        else cast(dict[str, object], memory.state["active_run"])
    )
    parent[field] = value
    before = deepcopy(memory.state)
    with pytest.raises(SlowListeningStateError, match=message):
        flush_slow_listening("slow", memory.dependencies())
    assert memory.state == before


@pytest.mark.parametrize("skipped", [None, [1]])
def test_invalid_skipped_records_stop_before_catalog_reads(skipped: object) -> None:
    """Only persisted string IDs can suppress interactive candidates.

    Args:
        skipped: Malformed saved skipped-candidate value.
    """
    memory = MemorySlowListening([SOURCE])
    _resume(memory)["skipped_candidates"] = skipped
    with pytest.raises(SlowListeningStateError, match="invalid skipped candidates"):
        flush_slow_listening("slow", memory.dependencies())
    assert "catalog" not in _event_names(memory)


@pytest.mark.parametrize(
    "status,playlist_id", [("completed", "slow"), ("active", "other")]
)
def test_incompatible_run_starts_a_fresh_snapshot(
    status: str, playlist_id: str
) -> None:
    """Only an active run for the same playlist is resumed.

    Args:
        status: Existing durable run status.
        playlist_id: Existing durable destination.
    """
    memory = MemorySlowListening([SOURCE])
    _resume(memory)
    run = cast(dict[str, object], memory.state["active_run"])
    run.update(status=status, playlist_id=playlist_id)
    assert not flush_slow_listening("slow", memory.dependencies()).resumed


@pytest.mark.parametrize(
    "entries,finished",
    [
        ([], True),
        ([None], False),
        ([{"status": "pending"}], False),
        ([{"status": "skipped"}], True),
    ],
)
def test_completion_requires_all_original_entries_to_be_finished(
    entries: list[object], finished: bool
) -> None:
    """Retain the original completion guard over durable records.

    Args:
        entries: Current run records.
        finished: Whether every entry is complete or skipped.
    """
    assert _finished(entries) is finished
