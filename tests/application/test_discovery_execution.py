"""Saved discovery plans preserve promotion, mutation and checkpoint boundaries."""

from dataclasses import asdict
from dataclasses import dataclass

import pytest

from spotify_manager.application.discovery_completion import DiscoveryCompletion
from spotify_manager.application.discovery_completion import ReviewArtist
from spotify_manager.application.discovery_library import DiscoveryLibraryReconciliation
from spotify_manager.application.new_kids_execution import NewKidsExecution
from spotify_manager.application.new_kids_state import assessment_from_record
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.release_evaluation import evaluate_catalog_release
from tests.support.discovery_effects import MemoryEffects
from tests.support.discovery_values import release
from tests.support.discovery_values import track
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
ARTIST = ReviewArtist("artist", "Artist")
ALBUM = release("album")
NEXT = release("next-release")
TARGET = track("next")


@dataclass
class ExecutionCase:
    """Explicit mutable state and effects for one saved review transition.

    Args:
        memory: Observed external effects.
        execution: Application executor under test.
        progress: Mutable artist progress in the namespace.
        entry: Mutable durable run entry.
    """

    memory: MemoryEffects
    execution: NewKidsExecution
    progress: dict[str, object]
    entry: dict[str, object]

    def run(self, plan: dict[str, object]) -> FlushResult:
        """Execute the original source using the supplied saved plan.

        Args:
            plan: Original persisted plan layout.

        Returns:
            Original public result.
        """
        self.entry["plan"] = plan
        return self.execution.execute(SOURCE, ARTIST, self.entry, self.progress, plan)


def _case(preview: bool = False) -> ExecutionCase:
    memory = MemoryEffects()
    progress: dict[str, object] = {
        "current_release_id": "album",
        "prior_unliked_streak": 1,
    }
    entry: dict[str, object] = {"status": "pending"}
    state: dict[str, object] = {
        "artists": {"artist": progress},
        "composer_routes": {"artist": {}},
        "active_run": {"entries": [entry]},
    }
    library = DiscoveryLibraryReconciliation(memory, memory, memory, preview)
    completion = DiscoveryCompletion(
        memory, memory, state, 2026, "newfoundland", "unlucky", preview
    )
    execution = NewKidsExecution(
        memory,
        memory,
        library,
        completion,
        memory,
        state,
        {"source"},
        "review",
        "New Kids",
        preview,
        memory.clock,
    )
    return ExecutionCase(memory, execution, progress, entry)


def _plan(action: str = "advance") -> dict[str, object]:
    return {
        "action": action,
        "current_release": asdict(ALBUM),
        "target": asdict(TARGET),
        "target_release": asdict(NEXT),
        "result_action": "advance",
        "next_prior_unliked_streak": 2,
    }


def _finish(
    *, qualifies: bool = True, top: bool = True, representative: bool = True
) -> dict[str, object]:
    plan = _plan("finish")
    plan["assessment"] = {
        "qualifies": qualifies,
        "top_liked_track": asdict(track("liked")) if top else None,
        "representative_track": asdict(track("popular")) if representative else None,
    }
    return plan


def _names(case: ExecutionCase) -> list[str]:
    return [name for name, value in case.memory.events]


def test_release_boundary_reconciles_before_playlist_then_checkpoints() -> None:
    """Library effects precede playlist changes; acknowledgment is last."""
    case = _case()
    plan = _plan("next_release")
    plan["evaluation"] = evaluate_catalog_release(
        ALBUM, (TARGET,), {"next": True}
    ).model_dump(mode="json")
    result = case.run(plan)
    assert _names(case) == [
        "saved",
        "save",
        "mirror",
        "audit",
        "message",
        "append",
        "marker_added",
        "remove_source",
        "marker_removed",
        "checkpoint",
    ]
    assert case.memory.events[5] == (
        "append",
        ("review", TARGET, "adding next to New Kids"),
    )
    assert case.execution.live_ids == {"next"}
    assert case.entry["status"] == "completed"
    assert case.progress == {
        "current_release_id": "next-release",
        "prior_unliked_streak": 2,
        "updated_at": "2026-09-27T00:00:00+00:00",
    }
    assert result.target_track == "next" and result.album_decision == "keep"


@pytest.mark.parametrize("preview", [False, True])
def test_absent_source_still_secures_a_missing_replacement(preview: bool) -> None:
    """Resume behavior retains destination repair even when the source was removed."""
    case = _case(preview)
    case.execution.live_ids.clear()
    case.run(_plan())
    expected = ["marker_added"] if preview else ["append", "marker_added", "checkpoint"]
    assert _names(case) == expected
    assert case.execution.live_ids == {"next"}


def test_existing_target_avoids_duplicate_addition() -> None:
    """A resumed replacement is reused before removing the original marker."""
    case = _case()
    case.execution.live_ids.add("next")
    case.run(_plan())
    assert _names(case) == ["remove_source", "marker_removed", "checkpoint"]


def test_preview_projects_markers_without_acknowledging_durable_progress() -> None:
    """Dry execution updates only in-memory playlist projections and messages."""
    case = _case(True)
    case.run(_plan("next_release"))
    assert _names(case) == ["marker_added", "marker_removed"]
    assert case.entry["status"] == "pending"
    assert case.progress == {"current_release_id": "album", "prior_unliked_streak": 1}
    assert case.memory.clock_reads == 0


@pytest.mark.parametrize("action", ["advance", "next_release", "unknown"])
def test_missing_optional_targets_retain_source_removal_and_progress(
    action: str,
) -> None:
    """Unknown actions and absent targets retain the original tolerant execution."""
    case = _case()
    plan = _plan(action)
    plan.update(target=None, target_release=None, next_prior_unliked_streak=True)
    case.run(plan)
    assert _names(case) == ["remove_source", "marker_removed", "checkpoint"]
    assert case.progress["current_release_id"] == "album"
    assert case.progress["prior_unliked_streak"] == 0


def test_composer_progress_uses_a_separate_clock_read() -> None:
    """Artist progress and route progress retain separate accepted timestamps."""
    case = _case()
    plan = _plan()
    plan["composer_playlist_id"] = "works"
    case.run(plan)
    assert case.memory.clock_reads == 2
    assert case.execution.state["composer_routes"] == {
        "artist": {
            "current_track_id": "next",
            "updated_at": "2026-09-27T00:00:01+00:00",
        }
    }


@pytest.mark.parametrize("routes", [None, {}, {"artist": None}])
def test_missing_or_malformed_composer_routes_remain_untouched(routes: object) -> None:
    """Execution does not manufacture a route absent from the saved namespace."""
    case = _case()
    case.execution.state["composer_routes"] = routes
    plan = _plan()
    plan["composer_playlist_id"] = "works"
    case.run(plan)
    assert case.execution.state["composer_routes"] is routes
    assert case.memory.clock_reads == 1


def test_composer_route_without_replacement_retains_its_marker() -> None:
    """A saved composer plan without a target cannot advance the route."""
    case = _case()
    plan = _plan()
    plan.update(composer_playlist_id="works", target=None)
    case.run(plan)
    assert case.execution.state["composer_routes"] == {"artist": {}}
    assert case.memory.clock_reads == 1


def test_promotion_secures_both_destinations_before_forgetting_artist() -> None:
    """Promotion adds Great Discoveries before Newfoundland and source removal."""
    case = _case()
    case.run(_finish())
    assert _names(case) == [
        "great",
        "membership",
        "append",
        "artist_added",
        "membership",
        "append",
        "artist_added",
        "remove_source",
        "marker_removed",
        "checkpoint",
    ]
    assert (
        case.memory.remote_ids["great"]
        == case.memory.remote_ids["newfoundland"]
        == {"popular"}
    )
    assert (
        case.execution.state["artists"] == case.execution.state["composer_routes"] == {}
    )
    assert case.memory.clock_reads == 0


@pytest.mark.parametrize("qualifies", [False, True])
def test_missing_liked_top_track_unfollows_even_a_qualifying_artist(
    qualifies: bool,
) -> None:
    """The absence of a liked marker takes precedence over promotion eligibility."""
    case = _case()
    case.run(_finish(qualifies=qualifies, top=False))
    assert _names(case) == [
        "followed",
        "unfollow",
        "artist_mirror",
        "artist_unfollowed",
        "remove_source",
        "marker_removed",
        "checkpoint",
    ]


@pytest.mark.parametrize("preview", [False, True])
def test_unlucky_destination_precedes_follow_observation(preview: bool) -> None:
    """A nonqualifying liked artist receives a marker before follow evaluation."""
    case = _case(preview)
    case.run(_finish(qualifies=False))
    expected = [
        "membership",
        "artist_added",
        "followed",
        "artist_unfollowed",
        "marker_removed",
    ]
    if not preview:
        expected = [
            "membership",
            "append",
            "artist_added",
            "followed",
            "unfollow",
            "artist_mirror",
            "artist_unfollowed",
            "remove_source",
            "marker_removed",
            "checkpoint",
        ]
    assert _names(case) == expected
    assert case.execution.completion.memberships["unlucky"] == ({"artist"}, {"liked"})


def test_already_unfollowed_artist_skips_mirror_removal() -> None:
    """An absent remote follow intentionally does not repair the artist mirror."""
    case = _case()
    case.memory.following = False
    case.execution.state["composer_routes"] = None
    case.run(_finish(top=False))
    assert _names(case) == ["followed", "remove_source", "marker_removed", "checkpoint"]


@pytest.mark.parametrize("qualifies", [False, True])
def test_composer_marker_overrides_regular_completion_targets(qualifies: bool) -> None:
    """Both promotion and Unlucky Ones retain the first composer work marker."""
    case = _case()
    plan = _finish(qualifies=qualifies, representative=False)
    plan["composer_destination_track"] = asdict(track("work"))
    case.run(plan)
    destination = "great" if qualifies else "unlucky"
    assert case.memory.remote_ids[destination] == {"work"}


def test_promotion_without_representative_fails_before_destination_reads() -> None:
    """Missing promotion markers leave playlist and progress effects untouched."""
    case = _case()
    with pytest.raises(NewKidsError, match="qualifies for promotion"):
        case.run(_finish(representative=False))
    assert case.memory.events == []
    assert case.entry["status"] == "pending"


def test_creation_preview_skips_missing_destination_membership() -> None:
    """A future playlist gets a descriptive preview without an invalid read."""
    case = _case(True)
    case.memory.great = None
    case.run(_finish())
    assert _names(case) == [
        "great",
        "future_artist_added",
        "membership",
        "artist_added",
        "marker_removed",
    ]
    assert case.memory.events[1] == (
        "future_artist_added",
        ("Artist", "Great Discoveries 2026", "popular"),
    )


def test_destination_artist_memberships_deduplicate_and_reuse_projected_reads() -> None:
    """Repeated completion reuses run-local membership including accepted additions."""
    case = _case()
    case.memory.destinations["great"] = ({"artist"}, {"different"})
    case.execution.completion.finish(ARTIST, _finish())
    case.execution.completion.finish(ARTIST, _finish())
    assert _names(case) == [
        "great",
        "membership",
        "membership",
        "append",
        "artist_added",
        "great",
    ]
    assert case.execution.completion.memberships["newfoundland"] == (
        {"artist"},
        {"popular"},
    )


@pytest.mark.parametrize("boundary", ["append", "remove_source", "checkpoint"])
def test_interrupted_marker_execution_stops_before_later_effects(boundary: str) -> None:
    """Accepted writes are not followed by later effects after a boundary fails."""
    case = _case()
    case.memory.fail_at = boundary
    effects = [
        "append",
        "marker_added",
        "remove_source",
        "marker_removed",
        "checkpoint",
    ]
    with pytest.raises(OSError, match=boundary):
        case.run(_plan())
    assert _names(case) == effects[: effects.index(boundary) + 1]
    assert case.entry["status"] == (
        "completed" if boundary == "checkpoint" else "pending"
    )


@pytest.mark.parametrize("boundary", ["unfollow", "artist_mirror"])
def test_unfollow_failure_leaves_source_pending(boundary: str) -> None:
    """Follow failures preserve the source marker and omit completion acknowledgment."""
    case = _case()
    case.memory.fail_at = boundary
    with pytest.raises(OSError, match=boundary):
        case.run(_finish(top=False))
    assert case.execution.live_ids == {"source"}
    assert case.entry["status"] == "pending"
    assert "checkpoint" not in _names(case)


def test_completed_artist_requires_an_artist_record_container() -> None:
    """Malformed artist state still fails after accepted source effects."""
    case = _case()
    case.execution.state["artists"] = None
    with pytest.raises(AssertionError):
        case.run(_finish(top=False))
    assert case.execution.live_ids == set()
    assert case.entry["status"] == "pending"


@pytest.mark.parametrize("raw", [None, [], "invalid"])
def test_completion_requires_an_assessment_record(raw: object) -> None:
    """A malformed saved assessment fails before any completion effect."""
    case = _case()
    plan = _finish()
    plan["assessment"] = raw
    with pytest.raises(NewKidsStateError, match="lacks assessment"):
        case.run(plan)
    assert case.memory.events == []


def test_assessment_translation_retains_original_coercions() -> None:
    """Booleans are rejected as counts while iterable reasons retain coercion."""
    result = assessment_from_record(
        {"liked_tracks": True, "saved_releases": 3, "reasons": "ab", "qualifies": "yes"}
    )
    assert result.liked_tracks == 0 and result.saved_releases == 3
    assert result.reasons == ("a", "b") and result.qualifies
    assert result.top_liked_track is None
    with pytest.raises(TypeError):
        assessment_from_record({"reasons": None})
