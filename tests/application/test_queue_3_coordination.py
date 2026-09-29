"""Queue 3 coordination preserves restart, pause, audit and checkpoint behavior."""

from dataclasses import asdict
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.queue_3_execution import Queue3Execution
from spotify_manager.application.queue_3_execution import Queue3LiveQueue
from spotify_manager.application.queue_3_planner import Queue3Planner
from spotify_manager.application.queue_3_planner import stable_release_order
from spotify_manager.application.queue_3_review import Queue3Observations
from spotify_manager.application.queue_3_review import Queue3Review
from spotify_manager.application.queue_3_run import Queue3Run
from spotify_manager.application.queue_3_run import run_summary
from spotify_manager.application.queue_3_values import AnnualImportResult
from spotify_manager.application.queue_3_values import FlushResult
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.domain.composers import OwnedPlaylist
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release
from tests.support.queue_3_memory import CoordinationMemory


RELEASE = studio_release("album", "Album")
SOURCE = playlist_track("source", RELEASE)
TARGET = release_track("target")
WORKS = OwnedPlaylist("works", "[CD] Johann Sebastian Bach Works", 2)
OTHER = OwnedPlaylist("other", "[CD] Johann Sebastian Bach Collection", 2)


def _plan() -> dict[str, object]:
    return {
        "action": "advance",
        "current_release": asdict(RELEASE),
        "target_release": asdict(RELEASE),
        "target": asdict(TARGET),
        "evaluation": None,
        "reason": None,
    }


def _entry(plan: object = None) -> dict[str, object]:
    return {
        "source": asdict(SOURCE),
        "artist_id": "artist",
        "artist_name": "Artist",
        "status": "pending",
        "plan": plan,
    }


def _state(entries: list[object]) -> dict[str, object]:
    return {
        "composer_routes": {},
        "release_orders": {},
        "annual_imports": {},
        "active_run": {
            "run_id": "saved",
            "playlist_id": "queue",
            "status": "active",
            "entries": entries,
        },
    }


def _queue() -> Queue3LiveQueue:
    return Queue3LiveQueue("queue", [SOURCE], {"source"})


def _review(
    memory: CoordinationMemory,
    state: dict[str, object],
    *,
    preview: bool = False,
    owned: tuple[OwnedPlaylist, ...] = (),
) -> Queue3Review:
    session = Queue3Run(state, memory, memory.now, preview)
    queue = _queue()
    snapshot = session.start(queue)
    ordering = ReleaseOrdering(stable_release_order, snapshot.orders, session.save)
    planner = Queue3Planner(
        memory.release_tracks, memory.evaluate, {}, ordering, memory.choose
    )
    execution = Queue3Execution(
        memory.append, memory.remove, memory.reconcile, memory, preview
    )
    observations = Queue3Observations(memory.catalog, memory.playlist)
    return Queue3Review(
        session,
        snapshot,
        queue,
        planner,
        execution,
        observations,
        owned,
        memory.choose_composer,
        memory.audit,
        memory,
    )


def _ordinary_memory() -> CoordinationMemory:
    return CoordinationMemory(
        catalogs={"artist": (RELEASE,)},
        tracks={"album": (release_track("source"), TARGET)},
    )


@pytest.mark.parametrize(
    "active",
    [
        None,
        False,
        {"status": "completed"},
        {"status": "active", "playlist_id": "other"},
    ],
)
def test_nonmatching_run_is_replaced_before_validation(active: object) -> None:
    """Queue 3 replaces unrelated or inactive runs instead of blocking the command.

    Args:
        active: Existing namespace's active-run value.
    """
    memory = CoordinationMemory()
    state = _state([])
    state["active_run"] = active
    session = Queue3Run(state, memory, memory.now, False)
    snapshot = session.start(_queue())
    assert snapshot.resumed is False and state["active_run"] is snapshot.record
    assert len(snapshot.entries) == 1 and len(memory.checkpoints) == 1
    assert [name for name, value in memory.events] == ["clock", "clock", "checkpoint"]


def test_preview_ignores_saved_run_without_overwriting_working_active_record() -> None:
    """Preview snapshots current markers and retains the supplied namespace record."""
    memory = CoordinationMemory()
    state = _state([])
    original = state["active_run"]
    snapshot = Queue3Run(state, memory, memory.now, True).start(_queue())
    assert snapshot.resumed is False and len(snapshot.entries) == 1
    assert state["active_run"] is original and memory.checkpoints == []


@pytest.mark.parametrize("field", ["entries", "release_orders", "composer_routes"])
def test_resumed_container_validation_precedes_all_effects(field: str) -> None:
    """Each original validation error occurs before observations or checkpoints.

    Args:
        field: Invalid container in the resumed state.
    """
    memory = CoordinationMemory()
    state = _state([])
    target = (
        cast(dict[str, object], state["active_run"]) if field == "entries" else state
    )
    target[field] = False
    with pytest.raises(Queue3StateError):
        Queue3Run(state, memory, memory.now, False).start(_queue())
    assert memory.events == []


def test_new_snapshot_is_saved_before_release_order_validation() -> None:
    """Invalid remaining state does not undo the initial snapshot checkpoint."""
    memory = CoordinationMemory()
    state = _state([])
    state.update(active_run=None, release_orders=False)
    with pytest.raises(Queue3StateError, match="release-order"):
        Queue3Run(state, memory, memory.now, False).start(_queue())
    assert len(memory.checkpoints) == 1


@pytest.mark.parametrize("status", ["completed", "skipped"])
def test_acknowledged_entries_need_no_decodable_source_or_plan(status: str) -> None:
    """Resumed acknowledged entries consume no progress, observation or audit effects.

    Args:
        status: Original acknowledged entry status.
    """
    memory = CoordinationMemory()
    review = _review(memory, _state([{"status": status}]))
    assert review.run() == ((), False)
    assert memory.events == []
    review.session.finish(review.snapshot, False)
    assert [name for name, value in memory.events] == ["clock", "checkpoint"]


def test_invalid_entry_fails_before_decoding_or_progress() -> None:
    """Entry validation remains lazy until its original position is reached."""
    memory = CoordinationMemory()
    review = _review(memory, _state([False]))
    with pytest.raises(Queue3StateError, match="invalid entry"):
        review.run()
    assert memory.events == []


@pytest.mark.parametrize("saved", [False, True])
def test_ordinary_review_checkpoints_plan_then_audits_before_acknowledgment(
    saved: bool,
) -> None:
    """Saved plans suppress observations; new plans checkpoint before playlist changes.

    Args:
        saved: Whether the entry already has a durable accepted plan.
    """
    memory = _ordinary_memory()
    entry = _entry(_plan() if saved else None)
    review = _review(memory, _state([entry]))
    results, paused = review.run()
    assert paused is False and len(results) == 1 and results[0].action == "advance"
    expected = ["started"]
    if not saved:
        expected.extend(["catalog", "tracks", "checkpoint"])
    expected.extend(
        ["append", "added", "remove", "removed", "audit", "checkpoint", "finished"]
    )
    assert [name for name, value in memory.events] == expected
    assert entry["status"] == "completed"
    assert memory.checkpoints[-1]["active_run"] == review.snapshot.record


@pytest.mark.parametrize("preview", [False, True])
def test_release_quit_leaves_entry_pending_without_audit_or_acknowledgment(
    preview: bool,
) -> None:
    """A declined release boundary retains the pending original source and absent plan.

    Args:
        preview: Whether a fresh preview snapshot is used.
    """
    second = studio_release("second", "Second", "2021")
    memory = CoordinationMemory(
        catalogs={"artist": (RELEASE, second)},
        tracks={"album": (release_track("source"),)},
        response="quit",
    )
    review = _review(memory, _state([_entry()]), preview=preview)
    assert review.run() == ((), True)
    entry = cast(dict[str, object], review.snapshot.entries[0])
    assert entry["status"] == "pending" and entry["plan"] is None
    assert memory.events[-1][0] == "choice"
    assert not any(name == "audit" for name, value in memory.events)


def test_composer_quit_does_not_observe_catalog_or_acknowledge_route() -> None:
    """Ambiguous route cancellation pauses before clock, playlist or catalog reads."""
    memory = CoordinationMemory(composer_response="quit")
    entry = _entry()
    entry.update(artist_name="Johann Sebastian Bach", artist_id="bach")
    review = _review(memory, _state([entry]), owned=(WORKS, OTHER))
    assert review.run() == ((), True)
    assert [name for name, value in memory.events] == ["started", "composer_choice"]


def test_stale_plan_is_cleared_before_message_and_checkpoint() -> None:
    """Stale-route removal remains accepted when its explanatory message fails."""
    memory = CoordinationMemory(failure="stale")
    plan = _plan()
    plan["composer_playlist_id"] = "unowned"
    entry = _entry(plan)
    state = _state([entry])
    state["composer_routes"] = {"artist": {"playlist_id": "unowned"}}
    review = _review(memory, state)
    with pytest.raises(OSError, match="stale"):
        review.run()
    assert entry["plan"] is None and state["composer_routes"] == {}
    assert [name for name, value in memory.events] == ["started", "stale"]


def test_stale_plan_rebuild_checkpoints_before_new_observations() -> None:
    """Stale removal has its own checkpoint before selecting a replacement plan."""
    memory = _ordinary_memory()
    plan = _plan()
    plan["composer_playlist_id"] = "unowned"
    review = _review(memory, _state([_entry(plan)]))
    results, paused = review.run()
    assert len(results) == 1 and paused is False
    assert [name for name, value in memory.events][:5] == [
        "started",
        "stale",
        "checkpoint",
        "catalog",
        "tracks",
    ]


@pytest.mark.parametrize("saved", [False, True])
def test_composer_advance_updates_route_only_after_transition_audit(
    saved: bool,
) -> None:
    """Accepted composer routes use separate selection and acknowledgment timestamps.

    Args:
        saved: Whether the composer plan and route were saved by an earlier attempt.
    """
    next_marker = playlist_track("target", RELEASE)
    memory = CoordinationMemory(works={"works": (SOURCE, next_marker)})
    plan = _plan()
    plan.update(action="composer_advance", composer_playlist_id="works")
    entry = _entry(plan if saved else None)
    entry.update(artist_id="bach", artist_name="Johann Sebastian Bach")
    state = _state([entry])
    if saved:
        state["composer_routes"] = {"bach": {"playlist_id": "works"}}
    review = _review(memory, state, owned=(WORKS,))
    results, paused = review.run()
    assert not paused and results[0].action == "composer playlist"
    names = [name for name, value in memory.events]
    assert names[-4:] == ["audit", "clock", "checkpoint", "finished"]
    assert ("works" in names) == (not saved)
    route = cast(dict[str, object], review.snapshot.routes["bach"])
    assert route["current_track_id"] == "target"


def test_empty_composer_playlist_skips_and_acknowledges_without_catalog_fallback() -> (
    None
):
    """An unmapped composer marker produces a skip, not an ordinary studio lookup."""
    memory = CoordinationMemory()
    entry = _entry()
    entry.update(artist_id="bach", artist_name="Johann Sebastian Bach")
    review = _review(memory, _state([entry]), owned=(WORKS,))
    results, paused = review.run()
    assert not paused and results[0].action == "skip" and entry["status"] == "skipped"
    assert "catalog" not in [name for name, value in memory.events]


def test_observation_cache_retains_empty_catalogs_and_works_playlists() -> None:
    """Repeated entries do not refetch empty observations within one review."""
    memory = CoordinationMemory()
    observations = Queue3Observations(memory.catalog, memory.playlist)
    for _attempt in range(2):
        assert observations.catalog("artist") == ()
        assert observations.playlist("works") == ()
    assert memory.events == [("catalog", "artist"), ("works", "works")]


@pytest.mark.parametrize("failure", ["audit", "checkpoint", "finished"])
def test_saved_entry_failure_preserves_audit_before_acknowledgment(
    failure: str,
) -> None:
    """Status changes happen after audit but before checkpoint and final progress.

    Args:
        failure: First failing post-execution boundary.
    """
    memory = CoordinationMemory(failure=failure)
    entry = _entry(_plan())
    review = _review(memory, _state([entry]))
    with pytest.raises(OSError, match=failure):
        review.run()
    assert entry["status"] == ("pending" if failure == "audit" else "completed")
    assert memory.events[-1][0] == failure


@pytest.mark.parametrize(
    "preview,paused,entries",
    [
        (True, False, []),
        (False, True, []),
        (False, False, [False]),
        (False, False, [{"status": "pending"}]),
    ],
)
def test_finish_suppresses_unacknowledged_paused_or_preview_completion(
    preview: bool,
    paused: bool,
    entries: list[object],
) -> None:
    """Overall completion requires all real entries to be acknowledged.

    Args:
        preview: Whether durable writes are suppressed.
        paused: Whether review was paused.
        entries: Original run's remaining entry records.
    """
    memory = CoordinationMemory()
    session = Queue3Run(_state(entries), memory, memory.now, False)
    snapshot = session.start(_queue())
    replace(session, dry_run=preview).finish(snapshot, paused)
    assert memory.events == [] and snapshot.record["status"] == "active"


@pytest.mark.parametrize("route", [None, False, {}])
def test_composer_acknowledgment_only_updates_existing_route_records(
    route: object,
) -> None:
    """Acknowledgment never invents a missing or malformed composer route.

    Args:
        route: Existing logical artist route value.
    """
    memory = CoordinationMemory()
    session = Queue3Run(_state([]), memory, memory.now, False)
    entry = _entry()
    routes = {"artist": route}
    session.acknowledge(entry, "composer_advance", TARGET, "artist", routes)
    assert entry["status"] == "completed"
    assert memory.clock_reads == (1 if isinstance(route, dict) else 0)


def test_preview_acknowledgment_leaves_entry_and_route_unchanged() -> None:
    """Preview effects do not acknowledge durable entries or routes."""
    memory = CoordinationMemory()
    session = Queue3Run(_state([]), memory, memory.now, True)
    entry = _entry()
    routes: dict[str, object] = {"artist": {}}
    session.acknowledge(entry, "composer_advance", TARGET, "artist", routes)
    session.save()
    assert entry["status"] == "pending" and routes == {"artist": {}}
    assert memory.events == []


def test_summary_counts_only_new_results_and_preserves_annual_decisions() -> None:
    """Resume metadata and action counts stay distinct from total entries."""
    memory = CoordinationMemory()
    session = Queue3Run(_state([{}, {}, {}, {}, {}, {}]), memory, memory.now, False)
    snapshot = session.start(_queue())
    base = FlushResult("Artist", "source", "Album", "advance")
    results = (
        base,
        replace(base, action="composer playlist"),
        replace(base, action="next release"),
        replace(base, action="complete"),
        replace(base, action="skip"),
    )
    annual = (AnnualImportResult("Artist", "source", 2025, "added"),)
    summary = run_summary(snapshot, results, annual, True, False)
    assert summary.total == 6 and summary.processed == 5 and summary.advanced == 2
    assert summary.changed_releases == summary.completed_artists == summary.skipped == 1
    assert summary.annual_import == annual and summary.paused and summary.resumed


def test_memory_rejects_unexpected_namespace_reload() -> None:
    """The test port exposes accidental duplicate state loads explicitly."""
    with pytest.raises(AssertionError, match="already prepared"):
        CoordinationMemory().load()
