"""Exercise studio tie ordering and candidate scanning without external services."""

from dataclasses import replace

import pytest

from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.application.slow_listening_plan import StudioObservations
from spotify_manager.application.slow_listening_plan import TrackSelection
from spotify_manager.application.slow_listening_state import release_from_record
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.domain.catalog import DiscographyRelease
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release
from tests.support.slow_listening_memory import FIRST
from tests.support.slow_listening_memory import SECOND
from tests.support.slow_listening_memory import SOURCE
from tests.support.slow_listening_memory import MemorySlowListening


class Choices(MemorySlowListening):
    """Record ordering checkpoints and declined candidate IDs through memory ports."""

    def persist(self) -> None:
        """Checkpoint the current preferences using the shared failure machinery."""
        self.save(self.state)

    def decline(self, spotify_id: str) -> None:
        """Record one new declined candidate before scanning the next.

        Args:
            spotify_id: Candidate just declined by the operator.
        """
        self.events.append(("decline", spotify_id))


def _ordering(memory: Choices) -> ReleaseOrdering:
    orders: dict[str, object] = {}
    memory.state["release_orders"] = orders
    return ReleaseOrdering(memory.order, orders, memory.persist)


def _selection(memory: Choices) -> TrackSelection:
    return TrackSelection(
        SOURCE,
        memory.releases,
        StudioObservations(memory),
        _ordering(memory),
        memory.choose,
        set(),
        memory.decline,
    )


@pytest.mark.parametrize(
    "stored", [None, [], ["first", "first"], "first", ["other", "first"]]
)
def test_invalid_saved_tie_order_prompts_and_checkpoints_once(stored: object) -> None:
    """Only a complete permutation can suppress the operator's ordering choice.

    Args:
        stored: Missing or malformed prior preference.
    """
    memory = Choices(order_ids=("second", "first"))
    ordering = _ordering(memory)
    tied = replace(SECOND, chronology_date=FIRST.chronology_date)
    key = f"{FIRST.primary_artist_id}:{FIRST.chronology_date}"
    ordering.saved[key] = stored
    assert ordering.ordered(FIRST.primary_artist_id, (FIRST, tied)) == (tied, FIRST)
    assert ordering.saved[key] == ["second", "first"]
    assert [event[0] for event in memory.events] == ["order", "save"]
    assert ordering.ordered(FIRST.primary_artist_id, (FIRST, tied)) == (tied, FIRST)
    assert memory.counts["order"] == 1


@pytest.mark.parametrize(
    "choice", [("first",), ("first", "first"), ("first", "unknown")]
)
def test_incomplete_operator_order_fails_without_saving(
    choice: tuple[str, ...],
) -> None:
    """Reject missing, repeated or unknown options before modifying preferences.

    Args:
        choice: Invalid callback result.
    """
    memory = Choices(order_ids=choice)
    ordering = _ordering(memory)
    with pytest.raises(SlowListeningError, match="include every option"):
        ordering.ordered("artist", (FIRST, SECOND))
    assert ordering.saved == {}
    assert memory.counts.get("save", 0) == 0


def test_preference_changes_before_failed_checkpoint() -> None:
    """Do not roll back an accepted in-memory ordering when persistence fails."""
    memory = Choices(failure="save")
    ordering = _ordering(memory)
    with pytest.raises(RuntimeError, match="save interrupted"):
        ordering.ordered("artist", (FIRST, SECOND))
    assert list(ordering.saved.values()) == [["first", "second"]]


def test_same_date_successor_and_next_date_ordering_are_lazy() -> None:
    """Only the current group and the reached successor group request ordering."""
    memory = Choices()
    ordering = _ordering(memory)
    tied = replace(SECOND, chronology_date=FIRST.chronology_date)
    third = studio_release("third", "Third", "2022")
    fourth = replace(third, spotify_id="fourth")
    releases = (FIRST, tied, third, fourth)
    assert ordering.following(FIRST, releases) == tied
    assert memory.counts["order"] == 1
    assert ordering.following(tied, releases) == third
    assert memory.counts["order"] == 2
    assert ordering.following(fourth, releases) is None


@pytest.mark.parametrize(
    "current",
    [replace(FIRST, chronology_date="1999"), replace(FIRST, spotify_id="absent")],
)
def test_absent_current_date_or_edition_has_no_successor(
    current: DiscographyRelease,
) -> None:
    """A missing date or ID cannot accidentally advance a different release.

    Args:
        current: Source edition absent from the catalog or its date group.
    """
    assert _ordering(Choices()).following(current, (FIRST, SECOND)) is None


@pytest.mark.parametrize("empty", [False, True])
def test_cross_release_advance_or_empty_release_skip(empty: bool) -> None:
    """The next edition is read only after exhausting the current edition.

    Args:
        empty: Whether the successor has no playable tracks.
    """
    memory = Choices(release_tracks={"first": (release_track("source"),)})
    memory.release_tracks["second"] = () if empty else (release_track("next"),)
    plan = _selection(memory).plan()
    assert plan is not None
    assert plan["action"] == ("skip" if empty else "advance")
    assert release_from_record(plan["target_release"]) == SECOND
    assert memory.counts["tracks"] == 2
    assert memory.counts.get("choose", 0) == int(not empty)


def test_all_remaining_candidates_skipped_completes_with_exact_reason() -> None:
    """Skipped labels and IDs are retained when no later studio track remains."""
    memory = Choices(releases=(FIRST,), choices=["skip"])
    selection = _selection(memory)
    plan = selection.plan()
    assert plan is not None
    assert plan["reason"] == "all remaining studio tracks were skipped"
    assert plan["skipped_candidates"] == ["target (First)"]
    assert selection.skipped_ids == {"target"}
    assert ("decline", "target") in memory.events


def test_unmapped_source_is_skipped_before_any_track_choice() -> None:
    """An absent ID and nonmatching title must not choose an arbitrary successor."""
    memory = Choices(release_tracks={"first": (release_track("different"),)})
    plan = _selection(memory).plan()
    assert plan is not None
    assert (
        plan["reason"] == "current track could not be mapped to the preferred edition"
    )
    assert "choose" not in memory.counts


def test_invalid_track_choice_fails_before_recording_a_skip() -> None:
    """Unknown callback answers are errors, not implicit declines."""
    memory = Choices(choices=["invalid"])
    with pytest.raises(SlowListeningError, match="add, skip candidate, or quit"):
        _selection(memory).plan()
    assert not any(event[0] == "decline" for event in memory.events)


def test_cached_empty_catalog_and_tracks_are_not_refetched() -> None:
    """An empty observation remains a completed read for the current invocation."""
    memory = Choices(releases=(), release_tracks={})
    observations = StudioObservations(memory)
    assert (
        observations.discography("artist") == observations.discography("artist") == ()
    )
    assert (
        observations.release_tracks(FIRST) == observations.release_tracks(FIRST) == ()
    )
    assert memory.counts["catalog"] == memory.counts["tracks"] == 1


def test_saved_order_stringifies_legacy_identifiers() -> None:
    """The original string conversion of persisted IDs remains a boundary rule."""
    memory = Choices()
    ordering = _ordering(memory)
    first = replace(FIRST, spotify_id="1")
    second = replace(FIRST, spotify_id="2")
    ordering.saved[f"artist:{FIRST.chronology_date}"] = [2, 1]
    assert ordering.ordered("artist", (first, second)) == (second, first)
    assert memory.events == []
