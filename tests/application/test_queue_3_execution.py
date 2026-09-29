"""Saved Queue 3 plans retain playlist projections and accepted-effect ordering."""

from dataclasses import asdict
from dataclasses import replace

import pytest

from spotify_manager.application.queue_3_execution import Queue3Execution
from spotify_manager.application.queue_3_execution import Queue3LiveQueue
from spotify_manager.application.queue_3_execution import Queue3Transition
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release
from tests.support.queue_3_memory import ExecutionMemory


RELEASE = studio_release("album", "Album")
SOURCE = playlist_track("source", RELEASE)
TARGET = release_track("target")


def _service(memory: ExecutionMemory, preview: bool = False) -> Queue3Execution:
    return Queue3Execution(
        memory.append, memory.remove, memory.reconcile, memory, preview
    )


def _transition(action: str = "advance") -> Queue3Transition:
    return Queue3Transition(
        SOURCE,
        "artist",
        "Artist",
        {
            "action": action,
            "current_release": asdict(RELEASE),
            "target_release": asdict(RELEASE),
            "target": asdict(TARGET),
            "evaluation": None,
            "reason": None,
        },
    )


def _queue(tracks: list[PlaylistTrack]) -> Queue3LiveQueue:
    return Queue3LiveQueue("queue", tracks, {track.spotify_id for track in tracks})


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("action", ["advance", "composer_advance", "next_release"])
def test_replacement_preserves_append_message_remove_message_order(
    preview: bool,
    action: str,
) -> None:
    """Successful projection keeps the original fixed snapshot and live-ID changes.

    Args:
        preview: Whether to project without remote mutations.
        action: Accepted replacement action.
    """
    memory = ExecutionMemory(remote={"source"})
    queue = _queue([SOURCE])
    transition = _transition(action)
    assert _service(memory, preview).run(transition, queue) == (action, TARGET)
    assert queue.ids == {"target"} and queue.tracks == [SOURCE]
    assert memory.remote == ({"source"} if preview else {"target"})
    assert [name for name, value in memory.events] == (
        ["added", "removed"] if preview else ["append", "added", "remove", "removed"]
    )


@pytest.mark.parametrize("failure", ["append", "added", "remove", "removed"])
def test_playlist_failures_preserve_prior_projection_and_remote_acceptance(
    failure: str,
) -> None:
    """No later effect runs after an interrupted mutation or message.

    Args:
        failure: Failing effect boundary.
    """
    memory = ExecutionMemory(failure, remote={"source"})
    queue = _queue([SOURCE])
    with pytest.raises(OSError, match=failure):
        _service(memory).run(_transition(), queue)
    expected = {"source", "target"}
    if failure == "append":
        expected = {"source"}
    if failure == "removed":
        expected = {"target"}
    assert queue.ids == memory.remote == expected
    assert memory.events[-1][0] == failure


def test_library_reconciliation_precedes_missing_marker_guard() -> None:
    """Already accepted library effects survive an absent-source/replacement error."""
    memory = ExecutionMemory()
    transition = _transition()
    evaluation = evaluate_release(SOURCE.release, (TARGET,), {"target": True})
    transition.plan["evaluation"] = evaluation.model_dump(mode="json")
    with pytest.raises(Queue3StateError, match="both absent"):
        _service(memory).run(transition, _queue([]))
    assert memory.events[0][0] == "library" and len(memory.events) == 1


def test_existing_replacement_needs_no_saved_release_or_repeated_append() -> None:
    """An accepted target needs no source or release facts before ordinary cleanup."""
    memory = ExecutionMemory()
    transition = _transition()
    transition.plan.update(current_release=None, target_release=None)
    queue = _queue([playlist_track("target", RELEASE)])
    assert _service(memory).run(transition, queue) == ("advance", TARGET)
    assert [name for name, value in memory.events] == ["remove", "removed"]
    assert queue.ids == set()


def test_new_target_requires_a_saved_release_even_in_preview() -> None:
    """Preview keeps the same plan validation boundary as real mutation."""
    transition = _transition()
    transition.plan.update(current_release=None, target_release=None)
    with pytest.raises(Queue3StateError, match="no saved target release"):
        _service(ExecutionMemory(), True).run(transition, _queue([SOURCE]))


def test_source_fallback_uri_does_not_rewrite_original_projection_selection() -> None:
    """Logical-credit mismatch retains the original fallback-removal projection."""
    transition = replace(_transition(), artist_id="logical")
    memory = ExecutionMemory(remote={"source"})
    queue = _queue([SOURCE])
    _service(memory).run(transition, queue)
    assert memory.remote == {"target"} and queue.ids == {"source", "target"}
    append = memory.events[0][1]
    assert isinstance(append, tuple)
    assert append[1][0].primary_artist_id == "logical"


@pytest.mark.parametrize("composer", [False, True])
def test_cleanup_restricts_composer_routes_to_the_original_source(
    composer: bool,
) -> None:
    """Ordinary cleanup removes all live artist markers; composer cleanup removes one.

    Args:
        composer: Whether the durable plan has a works-playlist route.
    """
    other = replace(SOURCE, spotify_id="other", uri="spotify:track:other")
    unrelated = replace(other, spotify_id="unrelated", primary_artist_id="unrelated")
    memory = ExecutionMemory(remote={"source", "other", "unrelated"})
    queue = _queue([SOURCE, other, unrelated])
    queue.ids.discard("unrelated")
    transition = _transition()
    transition.plan["composer_playlist_id"] = "works" if composer else None
    _service(memory).run(transition, queue)
    assert queue.ids == ({"other", "target"} if composer else {"target"})


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("present", [False, True])
def test_completion_always_reports_after_optional_marker_cleanup(
    preview: bool, present: bool
) -> None:
    """An already absent final marker still produces the original completion message.

    Args:
        preview: Whether remote mutation is suppressed.
        present: Whether a final artist marker remains live.
    """
    memory = ExecutionMemory(remote={"source"} if present else set())
    queue = _queue([SOURCE] if present else [])
    transition = _transition("complete")
    _service(memory, preview).run(transition, queue)
    assert queue.ids == set()
    assert memory.events[-1] == ("completed", ("Artist", preview))
    assert len(memory.events) == (2 if present and not preview else 1)


@pytest.mark.parametrize("action", ["skip", "unknown", "advance"])
def test_skip_and_tolerated_incomplete_actions_do_not_mutate_playlist(
    action: str,
) -> None:
    """An absent target retains original no-op behavior for an otherwise advance action.

    Args:
        action: Skip, unknown, or incomplete replacement action.
    """
    memory = ExecutionMemory()
    transition = _transition(action)
    transition.plan.update(target=None, reason=False)
    queue = _queue([SOURCE])
    assert _service(memory).run(transition, queue) == (action, None)
    assert queue.ids == {"source"}
    assert memory.events == (
        [("skipped", ("Artist", False))] if action == "skip" else []
    )


def test_composer_resume_without_source_leaves_other_artist_markers_untouched() -> None:
    """A completed composer replacement never falls back to performer-wide cleanup."""
    queue = _queue([playlist_track("target", RELEASE)])
    transition = _transition()
    transition.plan["composer_playlist_id"] = "works"
    memory = ExecutionMemory()
    _service(memory).run(transition, queue)
    assert memory.events == []


def test_evaluation_without_current_release_does_not_reconcile_library() -> None:
    """Legacy optional release decoding suppresses reconciliation without a release."""
    transition = _transition("skip")
    transition.plan["current_release"] = None
    evaluation = evaluate_release(SOURCE.release, (), {})
    transition.plan["evaluation"] = evaluation.model_dump(mode="json")
    memory = ExecutionMemory()
    _service(memory).run(transition, _queue([]))
    assert [name for name, value in memory.events] == ["skipped"]


def test_target_marker_falls_back_to_current_release_and_logical_credit() -> None:
    """A missing target release retains the original current-release fallback."""
    transition = replace(_transition(), artist_name="Logical Name")
    transition.plan["target_release"] = None
    memory = ExecutionMemory()
    _service(memory).run(transition, _queue([SOURCE]))
    payload = memory.events[0][1]
    assert isinstance(payload, tuple)
    marker = payload[1][0]
    assert (
        marker.release == SOURCE.release
        and marker.primary_artist_name == "Logical Name"
    )


@pytest.mark.parametrize("field", ["current_release", "target_release", "target"])
def test_saved_records_are_decoded_before_library_reconciliation(field: str) -> None:
    """Malformed target facts cannot trigger partial library effects.

    Args:
        field: Saved record corrupted before execution.
    """
    transition = _transition()
    transition.plan[field] = False
    transition.plan["evaluation"] = evaluate_release(SOURCE.release, (), {}).model_dump(
        mode="json"
    )
    memory = ExecutionMemory()
    with pytest.raises(Queue3StateError):
        _service(memory).run(transition, _queue([SOURCE]))
    assert memory.events == []


def test_library_failure_prevents_all_playlist_effects() -> None:
    """Playlist mutations wait for completed-release reconciliation to succeed."""
    transition = _transition()
    transition.plan["evaluation"] = evaluate_release(SOURCE.release, (), {}).model_dump(
        mode="json"
    )
    memory = ExecutionMemory(failure="library")
    queue = _queue([SOURCE])
    with pytest.raises(OSError, match="library"):
        _service(memory).run(transition, queue)
    assert queue.ids == {"source"}
    assert [name for name, value in memory.events] == ["library"]
