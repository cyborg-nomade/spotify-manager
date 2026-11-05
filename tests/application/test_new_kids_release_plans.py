"""Durable explicit transfers, recovery and scrobble-independent progression."""

from copy import deepcopy
from dataclasses import asdict
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.new_kids_plan_records import plan_record
from spotify_manager.application.new_kids_plan_records import saved_plan
from spotify_manager.application.new_kids_plan_selection import NewKidsPlanSelection
from spotify_manager.application.new_kids_plan_selection import ReleasePlanStoppedError
from spotify_manager.application.new_kids_plan_transfers import (
    PlannedDiscoveryTransfers,
)
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.new_kids_planner import ReviewSource
from spotify_manager.application.new_kids_state import logical_artist
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.ports.new_kids_plans import ReleasePlanSubmission
from spotify_manager.domain.new_kids_plans import ReleasePlan
from spotify_manager.domain.new_kids_plans import plan_marker
from tests.support.discovery_values import release
from tests.support.discovery_values import track
from tests.support.new_kids_plan_memory import PlanMemory


def _memory() -> PlanMemory:
    memory = PlanMemory()
    ids = ("queue-album", "a", "b", "c", "d")
    catalog = tuple(release(identity) for identity in ids)
    memory.catalogs["artist"] = catalog
    for item in catalog:
        memory.releases[item.spotify_id] = (track(item.spotify_id + "-first"),)
    memory.playlists["queue"] = (plan_marker(catalog[0], track("source")),)
    memory.answers = [ReleasePlanSubmission("select", ("d", "b", "a", "c"))]
    return memory


def _transfer(memory: PlanMemory, preview: bool = False) -> PlannedDiscoveryTransfers:
    return PlannedDiscoveryTransfers(
        memory,
        memory,
        memory,
        "kids",
        "queue",
        10,
        preview,
        NewKidsPlanSelection(memory, memory),
        memory,
    )


async def test_transfer_pins_plan_before_writes_and_starts_first_chosen_record() -> (
    None
):
    """Queue album is optional and no mutation precedes the accepted checkpoint."""
    memory = _memory()
    state = await memory.load()
    current, results, remaining = await _transfer(memory).move([], state)
    assert current[0].release.spotify_id == "d" and current[0].spotify_id == "d-first"
    assert results[0].track == "d-first" and remaining == []
    artists = cast(dict[str, dict[str, object]], memory.persisted["artists"])
    pinned = saved_plan(artists["artist"])
    assert pinned is not None and [item.spotify_id for item in pinned.releases] == [
        "d",
        "b",
        "a",
        "c",
    ]
    events = [name for name, _value in memory.events]
    assert events.index("save") < events.index("append") < events.index("remove")
    assert memory.snapshots[0]["release_plan_transfers"]
    assert memory.persisted["release_plan_transfers"] == {}


@pytest.mark.parametrize("failure", ["append", "append_ack", "remove", "remove_ack"])
async def test_transfer_resumes_accepted_plan_without_duplicate_append(
    failure: str,
) -> None:
    """Reload both sides after an interrupted or unacknowledged effect.

    Args:
        failure: Effect boundary interrupted after accepted plan persistence.
    """
    memory = _memory()
    memory.fail_at = failure
    with pytest.raises(OSError, match=failure):
        await _transfer(memory).move([], await memory.load())
    current = list(await memory.playlist("kids"))
    resumed, results, remaining = await _transfer(memory).move(
        current, await memory.load()
    )
    assert len(resumed) == 1 and resumed[0].spotify_id == "d-first"
    assert len(memory.drafts) == 1 and remaining == [] and results[0].action == "moved"
    assert [name for name, _value in memory.events].count("append") == 1


async def test_checkpoint_failure_never_moves_an_unpersisted_plan() -> None:
    """A rejected first save retains the source and leaves destination untouched."""
    memory = _memory()
    memory.fail_at = "save"
    with pytest.raises(OSError, match="save"):
        await _transfer(memory).move([], await memory.load())
    assert (
        memory.playlists.get("kids", ()) == () and len(memory.playlists["queue"]) == 1
    )
    assert memory.persisted["artists"] == {}


@pytest.mark.parametrize("action", ["skip", "quit"])
async def test_controls_leave_unaccepted_source_and_plan_unchanged(action: str) -> None:
    """Skipping or quitting cannot persist a plan or transfer the marker.

    Args:
        action: Explicit operator control.
    """
    memory = _memory()
    memory.answers = [ReleasePlanSubmission("skip" if action == "skip" else "quit")]
    state = await memory.load()
    if action == "quit":
        with pytest.raises(ReleasePlanStoppedError):
            await _transfer(memory).move([], state)
    else:
        current, results, remaining = await _transfer(memory).move([], state)
        assert current == [] and results[0].action == "skipped" and remaining
    assert memory.snapshots == [] and memory.playlists.get("kids", ()) == ()


async def test_preview_keeps_first_marker_without_repeating_transfer() -> None:
    """Prefill/refill share projected membership and leave the first track in place."""
    memory = _memory()
    state = await memory.load()
    before = deepcopy(memory.persisted)
    transfer = _transfer(memory, True)
    current, _results, _remaining = await transfer.move([], state)
    assert transfer.review_markers(current, state) == []
    current, refill, remaining = await transfer.move([], state)
    assert len(current) == 1 and refill == () and remaining == []
    assert memory.persisted == before and memory.snapshots == []
    assert (
        memory.playlists.get("kids", ()) == () and len(memory.playlists["queue"]) == 1
    )


async def _planned_context(memory: PlanMemory, position: int = 0) -> ReviewSource:
    chosen = tuple(release(identity) for identity in ("d", "b", "a", "c"))
    current = chosen[position]
    tracks = await memory.tracks(current)
    marker = plan_marker(current, tracks[0])
    progress: dict[str, object] = {
        "release_plan": plan_record(ReleasePlan(chosen, position))
    }
    return ReviewSource(
        marker, "artist", "Artist", progress, chosen, current, tracks, tracks, 0
    )


async def test_planned_boundary_uses_order_without_history_or_operator_choice() -> None:
    """Any scrobble completion evidence cannot skip the pinned next record."""
    memory = _memory()
    observations = DiscoveryObservations(
        memory, {("artist", "b"): frozenset({"all", "tracks"})}
    )
    planner = NewKidsPlanner(observations, memory, memory, memory, 2026, False)
    context = await _planned_context(memory)
    decision = await planner.plan(context)
    assert isinstance(decision, dict)
    target = decision["target_release"]
    assert isinstance(target, dict) and target["spotify_id"] == "b"
    assert decision["release_number"] == 2 and decision["release_plan_position"] == 1
    assert not any(
        name in {"choice", "message", "audit"} for name, _value in memory.events
    )


async def test_unavailable_pinned_release_stops_instead_of_substituting() -> None:
    """A missing next track list retains the plan and current marker."""
    memory = _memory()
    memory.releases["b"] = ()
    planner = NewKidsPlanner(
        DiscoveryObservations(memory, {}), memory, memory, memory, 2026, False
    )
    context = await _planned_context(memory)
    before = deepcopy(context.progress)
    with pytest.raises(NewKidsError, match="Planned release b"):
        await planner.plan(context)
    assert context.progress == before and not memory.choices


async def test_last_planned_record_uses_existing_artist_completion_criteria() -> None:
    """Plan exhaustion reaches the live assessment without a history choice."""
    memory = _memory()
    planner = NewKidsPlanner(
        DiscoveryObservations(memory, {}), memory, memory, memory, 2026, False
    )
    decision = await planner.plan(await _planned_context(memory, 3))
    assert isinstance(decision, dict) and decision["action"] == "finish"
    assert decision["result_action"] == "unfollowed"
    assert "assessment" in decision and "evaluation" in decision
    assert not any(
        name in {"choice", "message", "audit"} for name, _value in memory.events
    )


async def test_intra_album_progress_does_not_advance_plan_position() -> None:
    """Existing track/streak rules advance within the pinned album first."""
    memory = _memory()
    memory.releases["d"] = (track("first"), track("second"))
    planner = NewKidsPlanner(
        DiscoveryObservations(memory, {}), memory, memory, memory, 2026, False
    )
    decision = await planner.plan(await _planned_context(memory))
    assert isinstance(decision, dict) and decision["action"] == "advance"
    assert "release_plan_position" not in decision
    target = decision["target"]
    assert isinstance(target, dict) and target["spotify_id"] == "second"


async def test_unexpected_current_album_cannot_reset_or_skip_the_saved_plan() -> None:
    """A manually replaced marker requires resolution before any new decision."""
    memory = _memory()
    planner = NewKidsPlanner(
        DiscoveryObservations(memory, {}), memory, memory, memory, 2026, False
    )
    context = await _planned_context(memory)
    context = replace(context, source=plan_marker(release("other"), track("other")))
    with pytest.raises(NewKidsError, match="current marker"):
        await planner.plan(context)
    assert not any(name == "memberships" for name, _value in memory.events)


async def test_exact_pinned_track_can_carry_another_albums_metadata() -> None:
    """Track membership retains explicit release identity across relinked metadata."""
    memory = _memory()
    planner = NewKidsPlanner(
        DiscoveryObservations(memory, {}), memory, memory, memory, 2026, False
    )
    context = await _planned_context(memory)
    other = plan_marker(release("different-album"), track("d-first"))
    decision = await planner.plan(replace(context, source=other))
    assert isinstance(decision, dict) and decision["action"] == "next_release"
    current = decision["current_release"]
    assert isinstance(current, dict) and current["spotify_id"] == "d"


async def test_unknown_track_cannot_complete_the_current_planned_album() -> None:
    """A disappeared current track cannot silently advance the pinned cursor."""
    memory = _memory()
    planner = NewKidsPlanner(
        DiscoveryObservations(memory, {}), memory, memory, memory, 2026, False
    )
    context = replace(await _planned_context(memory), source_index=None)
    with pytest.raises(NewKidsError, match="current marker"):
        await planner.plan(context)


async def test_invalid_short_selection_is_reoffered_before_persisting() -> None:
    """A shorter order cannot transfer until the operator explicitly confirms it."""
    memory = _memory()
    memory.answers = [
        ReleasePlanSubmission("select", ("a",)),
        ReleasePlanSubmission("select", ("a",), True),
    ]
    await _transfer(memory).move([], await memory.load())
    assert len(memory.drafts) == 2 and "shorter" in memory.drafts[1].notice
    assert len(memory.snapshots) == 2


async def test_missing_both_pending_transfer_markers_requires_resolution() -> None:
    """Recovery cannot manufacture an unexpected marker after manual removal."""
    memory = _memory()
    memory.fail_at = "append"
    with pytest.raises(OSError):
        await _transfer(memory).move([], await memory.load())
    memory.playlists["queue"] = ()
    with pytest.raises(NewKidsStateError, match="Neither side"):
        await _transfer(memory).move([], await memory.load())
    assert memory.playlists.get("kids", ()) == () and len(memory.drafts) == 1


def test_refill_preview_preserves_logical_composer_credit_after_advancing() -> None:
    """Projected performer markers retain their logical composer during refill."""
    memory = _memory()
    transfer = _transfer(memory, True)
    source = plan_marker(release("works"), track("source"))
    target = track("following")
    transfer.preview.tracks = [source]
    route = {"artist_name": "Composer", "current_track_id": "source"}
    state: dict[str, object] = {"composer_routes": {"composer": route}}
    plan = {
        "target": asdict(target),
        "target_release": asdict(release("works")),
        "composer_playlist_id": "works",
    }
    run: dict[str, object] = {"entries": [{"artist_id": "composer", "plan": plan}]}
    transfer.project_review(run, {"following"}, state)
    assert transfer.preview.tracks[0].spotify_id == "following"
    assert logical_artist(state, transfer.preview.tracks[0]) == ("composer", "Composer")


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"version": 1, "releases": [], "position": 0},
        {"version": 1, "releases": [], "position": True},
    ],
)
def test_malformed_saved_plan_never_falls_back_to_history(raw: object) -> None:
    """An existing invalid plan key requires operator repair.

    Args:
        raw: Corrupt or unsupported saved plan.
    """
    with pytest.raises(NewKidsStateError):
        saved_plan({"release_plan": raw})
