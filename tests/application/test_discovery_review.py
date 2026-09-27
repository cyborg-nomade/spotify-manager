"""Entry coordination preserves saved plans, composer choices and audit order."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace

import pytest

from spotify_manager.application.discovery_completion import DiscoveryCompletion
from spotify_manager.application.discovery_library import DiscoveryLibraryReconciliation
from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.discovery_review import DiscoveryReview
from spotify_manager.application.new_kids_execution import NewKidsExecution
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.composers import OwnedPlaylist
from tests.support.discovery_effects import MemoryEffects
from tests.support.discovery_memory import MemoryDiscovery
from tests.support.discovery_values import release
from tests.support.discovery_values import track
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
ALBUM = release("album")
WORKS = OwnedPlaylist("works", "[CD] Artist works", 2)
OTHER_WORKS = OwnedPlaylist("other-works", "[CD] Artist complete works", 2)


@dataclass
class ReviewCase:
    """One review entry with shared observation and effect traces.

    Args:
        review: Application entry coordinator.
        facts: Scripted live discovery observations and choices.
        effects: External effects and progress messages.
        entry: Mutable original run entry.
    """

    review: DiscoveryReview
    facts: MemoryDiscovery
    effects: MemoryEffects
    entry: dict[str, object]


def _case(
    *, preview: bool = False, owned: tuple[OwnedPlaylist, ...] = ()
) -> ReviewCase:
    effects = MemoryEffects()
    facts = MemoryDiscovery(
        catalogs={"artist": (ALBUM,)},
        releases={"album": (track("source"), track("next"))},
        playlists={"works": (SOURCE, replace(SOURCE, spotify_id="next"))},
        events=effects.events,
    )
    state: dict[str, object] = {"artists": {}, "composer_routes": {}}
    entry: dict[str, object] = {
        "source": asdict(SOURCE),
        "status": "pending",
        "plan": None,
    }
    library = DiscoveryLibraryReconciliation(effects, effects, effects, preview)
    completion = DiscoveryCompletion(
        effects, effects, state, 2026, "newfoundland", "unlucky", preview
    )
    execution = NewKidsExecution(
        effects,
        effects,
        library,
        completion,
        effects,
        state,
        {"source"},
        "review",
        "New Kids",
        preview,
        effects.clock,
    )
    planner = NewKidsPlanner(
        DiscoveryObservations(facts, {}), facts.choose, effects, facts, 2026, preview
    )
    review = DiscoveryReview(
        planner,
        execution,
        effects,
        effects,
        effects,
        owned,
        frozenset({"review"}),
        effects.clock,
        40,
        effects.progress,
    )
    return ReviewCase(review, facts, effects, entry)


def _plan() -> dict[str, object]:
    return {
        "action": "advance",
        "result_action": "advance",
        "current_release": asdict(ALBUM),
        "target": asdict(track("next")),
        "target_release": asdict(ALBUM),
    }


def _names(case: ReviewCase) -> list[str]:
    return [name for name, value in case.effects.events]


def test_plan_checkpoint_precedes_effects_and_completion_audit_follows_ack() -> None:
    """Ordinary progression preserves observation, planning and acknowledgment order."""
    case = _case()
    results, paused = case.review.review([case.entry], "run")
    assert not paused and results[0].target_track == "next"
    assert _names(case) == [
        "progress",
        "catalog",
        "tracks",
        "memberships",
        "memberships",
        "checkpoint",
        "append",
        "marker_added",
        "remove_source",
        "marker_removed",
        "checkpoint",
        "audit",
        "progress",
    ]
    assert case.effects.events[0] == ("progress", (0, 1, f"Artist - {SOURCE.name}"))
    assert case.effects.events[-1] == ("progress", (1, 1, "Completed Artist"))
    assert case.effects.events[-2] == (
        "audit",
        ("track_completed", {"run_id": "run", "result": asdict(results[0])}),
    )


def test_saved_ordinary_plan_still_observes_current_catalog_before_execution() -> None:
    """A saved plan skips decision work while retaining original source observations."""
    case = _case()
    case.entry["plan"] = _plan()
    results, paused = case.review.review([case.entry], None)
    assert not paused and len(results) == 1
    assert _names(case)[:3] == ["progress", "catalog", "tracks"]
    assert "memberships" not in _names(case)
    assert _names(case).count("checkpoint") == 1


@pytest.mark.parametrize("status", ["completed", "skipped"])
def test_completed_entries_skip_source_validation_and_progress(status: str) -> None:
    """Already acknowledged entries need no source, observation or callback."""
    case = _case()
    assert case.review.review([{"status": status}], "run") == ((), False)
    assert case.effects.events == []


@pytest.mark.parametrize("raw", [None, [], "invalid"])
def test_invalid_entry_retains_original_error_before_any_effect(raw: object) -> None:
    """Malformed entry containers fail before attempting source translation."""
    case = _case()
    with pytest.raises(NewKidsStateError, match="invalid entry"):
        case.review.review([raw], "run")
    assert case.effects.events == []


def test_missing_source_release_is_prepended_before_ordinary_planning() -> None:
    """A playlist release absent from the catalog remains a review candidate."""
    case = _case()
    case.facts.catalogs.clear()
    results, paused = case.review.review([case.entry], "run")
    assert not paused and results[0].action == "advance"
    assert _names(case)[:3] == ["progress", "catalog", "tracks"]


def test_source_fallback_does_not_duplicate_an_existing_release_identity() -> None:
    """Edition identity deduplication still uses the fallback source release."""
    case = _case()
    case.facts.catalogs["artist"] = (replace(ALBUM, spotify_id="alternate"),)
    results, paused = case.review.review([case.entry], "run")
    assert not paused and results[0].target_track == "next"
    assert ("tracks", "album") in case.effects.events


@pytest.mark.parametrize("preview", [False, True])
def test_ordinary_skip_audits_before_checkpoint_and_returns_public_result(
    preview: bool,
) -> None:
    """Ordinary skips differ from composer skips in both audit and result behavior."""
    case = _case(preview=preview)
    other = release("other")
    case.facts.catalogs["artist"] = (ALBUM, other)
    case.facts.releases.update(album=(track("source"),), other=(track("other"),))
    case.facts.choices.append("__skip__")
    results, paused = case.review.review([case.entry], "run")
    assert not paused and results[0].action == "skip"
    assert case.entry["status"] == "skipped"
    expected_tail = (
        ["choice", "audit"] if preview else ["choice", "audit", "checkpoint"]
    )
    assert _names(case)[-len(expected_tail) :] == expected_tail
    assert _names(case).count("progress") == 1


def test_ordinary_quit_leaves_pending_entry_and_does_not_process_later_entries() -> (
    None
):
    """Operator pause stops the snapshot immediately without accepting a plan."""
    case = _case()
    case.facts.catalogs["artist"] = (ALBUM, release("other"))
    case.facts.releases.update(album=(track("source"),), other=(track("other"),))
    case.facts.choices.append("__quit__")
    assert case.review.review([case.entry, None], "run") == ((), True)
    assert case.entry["status"] == "pending" and case.entry["plan"] is None
    assert "checkpoint" not in _names(case)


def test_composer_plan_is_checkpointed_before_the_ordinary_source_observations() -> (
    None
):
    """Works observations and their saved plan precede unconditional source reads."""
    case = _case(owned=(WORKS,))
    results, paused = case.review.review([case.entry], "run")
    assert not paused and results[0].composer_playlist == WORKS.name
    assert _names(case)[:6] == [
        "progress",
        "playlist",
        "memberships",
        "checkpoint",
        "catalog",
        "tracks",
    ]
    assert _names(case).count("playlist") == 1


def test_composer_completion_observes_artist_assessment_only_at_last_work() -> None:
    """Finished works retain the ordinary saved/top membership assessment rules."""
    case = _case(owned=(WORKS,))
    case.facts.playlists["works"] = (SOURCE,)
    results, paused = case.review.review([case.entry], "run")
    assert not paused and results[0].action == "unfollowed"
    assert "top" in _names(case) and "saved" in _names(case)
    assert _names(case).index("top") < _names(case).index("checkpoint")


@pytest.mark.parametrize("choice", ["__skip__", "__quit__"])
@pytest.mark.parametrize("preview", [False, True])
def test_composer_control_choices_skip_catalog_observation(
    choice: str, preview: bool
) -> None:
    """Composer controls resolve before catalog reads and never emit skip results."""
    case = _case(preview=preview, owned=(WORKS, OTHER_WORKS))
    case.facts.choices.append(choice)
    results, paused = case.review.review([case.entry], "run")
    assert results == () and paused == (choice == "__quit__")
    assert "catalog" not in _names(case) and "audit" not in _names(case)
    if choice == "__skip__":
        expected = (
            ["progress", "choice", "skipped"]
            if preview
            else ["progress", "choice", "checkpoint", "skipped"]
        )
        assert _names(case) == expected
        assert case.entry["status"] == "skipped"


def test_saved_valid_composer_plan_skips_new_route_and_works_reads() -> None:
    """Valid saved works plans execute after unconditional source catalog reads."""
    case = _case(owned=(WORKS,))
    plan = _plan()
    plan["composer_playlist_id"] = "works"
    case.entry["plan"] = plan
    case.review.review([case.entry], "run")
    assert "playlist" not in _names(case) and "choice" not in _names(case)
    assert "stale" not in _names(case)


def test_stale_composer_plan_is_discarded_before_checkpoint_and_replanning() -> None:
    """Invalid routing clears both saved plan and route before its original message."""
    case = _case()
    plan = _plan()
    plan["composer_playlist_id"] = "missing"
    case.entry["plan"] = plan
    case.review.execution.state["composer_routes"] = {
        "artist": {"playlist_id": "missing"}
    }
    case.review.review([case.entry], "run")
    assert _names(case)[:5] == ["progress", "stale", "checkpoint", "catalog", "tracks"]
    assert case.entry["plan"] != plan
    assert case.review.execution.state["composer_routes"] == {}


def test_stale_plan_with_malformed_routes_is_checkpointed_before_route_validation() -> (
    None
):
    """Malformed route containers retain the original delayed validation boundary."""
    case = _case()
    plan = _plan()
    plan["composer_playlist_id"] = "missing"
    case.entry["plan"] = plan
    case.review.execution.state["composer_routes"] = []
    with pytest.raises(NewKidsStateError, match="composer-route"):
        case.review.review([case.entry], "run")
    assert _names(case) == ["progress", "stale", "checkpoint"]
    assert case.entry["plan"] is None


def test_optional_progress_callback_does_not_change_effect_order() -> None:
    """An absent progress callback simply suppresses its notifications."""
    case = _case()
    review = replace(case.review, progress_callback=None)
    results, paused = review.review([case.entry], "run")
    assert len(results) == 1 and not paused
    assert "progress" not in _names(case)


def test_completion_audit_failure_retains_acknowledged_entry_without_end_progress() -> (
    None
):
    """Successful execution is checkpointed before a completion audit can fail."""
    case = _case()
    case.effects.fail_at = "audit"
    with pytest.raises(OSError, match="audit"):
        case.review.review([case.entry], "run")
    assert case.entry["status"] == "completed"
    assert _names(case)[-2:] == ["checkpoint", "audit"]
    assert _names(case).count("progress") == 1
