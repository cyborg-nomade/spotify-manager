"""Independent decision scenarios for New Wine release and endpoint progression."""

from dataclasses import asdict
from dataclasses import replace

import pytest

from spotify_manager.application.new_wine_planner import WineDecision
from spotify_manager.application.new_wine_planner import WinePlanner
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.new_wine_values import NewWineError
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.listening_values import release_track
from tests.support.new_wine_memory import ALBUM
from tests.support.new_wine_memory import FOLLOWUP
from tests.support.new_wine_memory import SOURCE
from tests.support.new_wine_memory import TARGET
from tests.support.new_wine_memory import MemoryWine
from tests.support.new_wine_memory import dependencies


def _planner(
    memory: MemoryWine,
    *,
    endpoint: bool = False,
    progress: dict[str, object] | None = None,
) -> WinePlanner:
    deps = dependencies(memory)
    return WinePlanner(
        deps.observations,
        progress or {},
        deps.choose,
        deps.endpoint,
        endpoint,
        False,
        memory.checkpoint,
        deps.presentation,
    )


def _plan(decision: WineDecision) -> dict[str, object]:
    assert isinstance(decision, dict)
    return decision


def _single() -> PlaylistTrack:
    return replace(SOURCE, release=replace(ALBUM, release_type="Single"))


@pytest.mark.parametrize("liked", [False, True])
def test_prior_streak_uses_preceding_tracks_and_current_like(liked: bool) -> None:
    """A live like resets the streak; otherwise preceding unlikes accumulate.

    Args:
        liked: Current source membership.
    """
    memory = MemoryWine(liked={"source"} if liked else set())
    memory.release_tracks["album"] = (
        release_track("before"),
        release_track("source"),
        TARGET,
    )
    plan = _plan(_planner(memory).plan(SOURCE, {}))
    assert plan["consecutive_unliked"] == (0 if liked else 2)
    assert memory.events[:3] == [
        ("tracks", "album"),
        ("likes", ["source"]),
        ("likes", ["before"]),
    ]


@pytest.mark.parametrize("prior", [-4, True, 1])
def test_saved_integer_streak_skips_preceding_membership_reads(prior: int) -> None:
    """Historical boolean and negative integer streaks retain their original meaning.

    Args:
        prior: Previously persisted integer-compatible value.
    """
    memory = MemoryWine()
    plan = _plan(
        _planner(memory, progress={"source": {"prior_unliked_streak": prior}}).plan(
            SOURCE, {}
        )
    )
    assert plan["consecutive_unliked"] == prior + 1
    assert memory.events[:2] == [("tracks", "album"), ("likes", ["source"])]
    assert memory.counts["likes"] == 1


def test_unknown_source_mapping_starts_selected_release_at_first_track() -> None:
    """No title/ID match means no inferred preceding streak."""
    memory = MemoryWine(release_tracks={"album": (TARGET,)})
    plan = _plan(_planner(memory, endpoint=True).plan(SOURCE, {}))
    assert plan["target"] == asdict(TARGET) and plan["consecutive_unliked"] == 1
    assert "endpoint" not in memory.counts


@pytest.mark.parametrize("later_liked", [False, True])
def test_third_unliked_track_skips_to_next_like_or_drops(later_liked: bool) -> None:
    """Three unlikes trigger an album-wide observation before progression.

    Args:
        later_liked: Whether a later liked target exists.
    """
    memory = MemoryWine(liked={"target"} if later_liked else set())
    progress: dict[str, object] = {"source": {"prior_unliked_streak": 2}}
    plan = _plan(_planner(memory, progress=progress).plan(SOURCE, {}))
    assert plan["action"] == ("advance" if later_liked else "drop")
    if later_liked:
        assert plan["next_prior_unliked_streak"] == 0
        assert plan["advance_reason"] == "next_liked_track"
        return
    assert plan["should_unsave"] is True
    assert plan["drop_reason"] == "three_consecutive_unliked"


def test_single_without_current_year_releases_is_skipped() -> None:
    """An empty candidate observation cannot select a release."""
    memory = MemoryWine()
    result = _planner(memory).plan(_single(), {})
    assert isinstance(result, FlushResult) and result.action == "skip"
    assert "choose" not in memory.counts


def test_only_current_year_single_is_dropped_without_prompt() -> None:
    """A sole same-ID single uses the existing automatic drop reason."""
    source = _single()
    memory = MemoryWine(candidates=(source.release,))
    plan = _plan(_planner(memory).plan(source, {}))
    assert plan["action"] == "drop"
    assert plan["drop_reason"] == "only_current_year_single"
    assert "choose" not in memory.counts


@pytest.mark.parametrize("choice", ["quit", "skip", "drop", "other", "missing"])
def test_single_release_choices_keep_original_outcomes(choice: str) -> None:
    """Single selection distinguishes pause, skip, drop, valid and unavailable IDs.

    Args:
        choice: Operator selection.
    """
    memory = MemoryWine(candidates=(FOLLOWUP,), choices=[choice])
    memory.release_tracks["other"] = (TARGET,)
    planner = _planner(memory)
    if choice == "missing":
        with pytest.raises(NewWineError, match="selected release"):
            planner.plan(_single(), {})
        return
    decision = planner.plan(_single(), {})
    if choice in {"quit", "skip"}:
        assert (
            decision is None if choice == "quit" else isinstance(decision, FlushResult)
        )
        return
    plan = _plan(decision)
    assert plan["action"] == ("drop" if choice == "drop" else "advance")
    expected = _single().release if choice == "drop" else FOLLOWUP
    assert plan["release"] == asdict(expected)


def test_selected_empty_release_is_skipped() -> None:
    """An accepted release with no playable tracks produces a skip result."""
    memory = MemoryWine(candidates=(FOLLOWUP,), choices=["other"])
    result = _planner(memory).plan(_single(), {})
    assert isinstance(result, FlushResult)
    assert (result.release, result.action) == ("Other", "skip")


@pytest.mark.parametrize("choice", ["quit", "skip", "drop", "finish", "other"])
def test_completed_album_continuation_choices(choice: str) -> None:
    """Follow-up choices preserve pause/skip and completion semantics.

    Args:
        choice: Operator follow-up response.
    """
    memory = MemoryWine(candidates=(ALBUM, FOLLOWUP), choices=[choice])
    memory.release_tracks = {"album": (release_track("source"),), "other": (TARGET,)}
    decision = _planner(memory).plan(SOURCE, {})
    if choice in {"quit", "skip"}:
        assert (
            decision is None if choice == "quit" else isinstance(decision, FlushResult)
        )
        return
    plan = _plan(decision)
    assert plan["action"] == "sauvignon"
    assert ("continuation_target" in plan) == (choice == "other")
    assert memory.counts["choose"] == 1


def test_empty_followup_preserves_primary_completion() -> None:
    """An empty follow-up release does not cancel the accepted Sauvignon transition."""
    memory = MemoryWine(candidates=(FOLLOWUP,), choices=["other"])
    memory.release_tracks["album"] = (release_track("source"),)
    plan = _plan(_planner(memory).plan(SOURCE, {}))
    assert plan["action"] == "sauvignon" and "continuation_target" not in plan
    assert any(name == "message:empty_continuation" for name, value in memory.events)


def test_single_selected_as_itself_can_complete_when_other_candidates_exist() -> None:
    """Automatic dropping requires a sole candidate; explicit selection can complete."""
    source = _single()
    memory = MemoryWine(candidates=(source.release, FOLLOWUP), choices=["album"])
    memory.release_tracks["album"] = (release_track("source"),)
    plan = _plan(_planner(memory).plan(source, {}))
    assert plan["action"] == "complete single" and plan["target"] is None


@pytest.mark.parametrize("mode", [False, True])
def test_saved_cutoff_is_reused_without_reprompting(mode: bool) -> None:
    """Saved cutoff limits selected tracks even when endpoint mode is now disabled.

    Args:
        mode: Current endpoint mode.
    """
    memory = MemoryWine(liked={"source"})
    plan = _plan(
        _planner(memory, endpoint=mode).plan(SOURCE, {"endpoint_choice": "cutoff"})
    )
    assert plan["action"] == "sauvignon"
    assert plan["album_total_tracks"] == 1
    assert plan["canonical_track_count"] == (1 if mode else 2)
    assert "endpoint" not in memory.counts


def test_cache_reuses_empty_catalog_observations_and_shared_likes() -> None:
    """Empty catalog responses are cached just like populated observations."""
    memory = MemoryWine(release_tracks={})
    observations = dependencies(memory).observations
    assert observations.tracks(ALBUM) == observations.tracks(ALBUM) == ()
    assert observations.releases("artist") == observations.releases("artist") == ()
    assert memory.counts["tracks"] == memory.counts["releases"] == 1
    observations.memberships((TARGET,))
    memory.liked.add("target")
    assert observations.source_liked("target") is False
