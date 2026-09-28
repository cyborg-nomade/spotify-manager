"""Freeze Queue 3 planning branches before moving the chronological planner."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.routines import queue_3
from tests.routines.test_queue_3 import FakeSpotify
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


CURRENT = studio_release("current", "Current", "2020")
FOLLOWING = studio_release("following", "Following", "2021")
SOURCE = playlist_track("source", CURRENT)


@dataclass
class PlanChoices:
    """Record boundary prompts and ordering checkpoints without external effects.

    Args:
        response: Operator response at a release boundary.
        events: Ordered choice and checkpoint observations.
    """

    response: str = "advance"
    events: list[tuple[str, object]] = field(default_factory=list)

    def choose(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
    ) -> str:
        """Record a boundary decision before any target-track read.

        Args:
            source: Original marker.
            current: Completed or ineligible source release.
            following: Proposed successor.

        Returns:
            Configured operator response.
        """
        self.events.append(("choose", (source, current, following)))
        return self.response

    def save(self) -> None:
        """Record a release-order checkpoint before the subsequent prompt."""
        self.events.append(("save", None))


def _retry(operation: Callable[[], object], _description: str) -> object:
    return operation()


def _plan(
    catalog: tuple[DiscographyRelease, ...],
    tracks: tuple[ReleaseTrack, ...],
    choices: PlanChoices,
    *,
    source: PlaylistTrack = SOURCE,
    target: tuple[ReleaseTrack, ...] = (release_track("next"),),
) -> dict[str, object] | None:
    cache = {"current": tracks, "following": target}
    return queue_3._build_plan(
        cast(Spotify, FakeSpotify()),
        source,
        catalog,
        _retry,
        cache,
        {},
        {},
        choices.save,
        choices.choose,
    )


@pytest.mark.parametrize(
    "tracks,action,target,reason",
    [
        ((), "complete", None, "current eligible release has no playable tracks"),
        (
            (release_track("different"),),
            "advance",
            "different",
            "restarted the preferred edition at its first track",
        ),
        ((release_track("source"), release_track("second")), "advance", "second", None),
        (
            (release_track("source"),),
            "complete",
            None,
            "last track of the final studio release",
        ),
    ],
)
def test_original_current_release_plans(
    tracks: tuple[ReleaseTrack, ...],
    action: str,
    target: str | None,
    reason: str | None,
) -> None:
    """Missing, intermediate and final markers retain original plan shapes.

    Args:
        tracks: Observed preferred-edition tracks.
        action: Expected durable action.
        target: Expected replacement ID, if any.
        reason: Original explanatory reason.
    """
    choices = PlanChoices()
    plan = _plan((CURRENT,), tracks, choices)
    assert plan is not None
    assert plan["action"] == action and plan["reason"] == reason
    record = plan["target"]
    assert (record["spotify_id"] if isinstance(record, dict) else None) == target
    assert bool(plan["evaluation"]) == (
        reason == "last track of the final studio release"
    )
    assert choices.events == []


@pytest.mark.parametrize("response", ["advance", "quit", "invalid"])
def test_original_boundary_choice_controls_target_loading(response: str) -> None:
    """A quit leaves no plan and invalid choices retain the original error.

    Args:
        response: Operator response at the successor boundary.
    """
    choices = PlanChoices(response)
    if response == "invalid":
        with pytest.raises(
            queue_3.Queue3Error, match="Release transition must be advance or quit"
        ):
            _plan((CURRENT, FOLLOWING), (release_track("source"),), choices)
        return
    plan = _plan((CURRENT, FOLLOWING), (release_track("source"),), choices)
    assert choices.events == [("choose", (SOURCE, CURRENT, FOLLOWING))]
    assert (plan is None) == (response == "quit")
    if plan is not None:
        assert plan["action"] == "next_release" and plan["evaluation"] is not None


def test_original_accepted_empty_target_raises_after_choice() -> None:
    """An accepted successor must have a playable marker."""
    choices = PlanChoices()
    with pytest.raises(queue_3.Queue3Error, match="Following has no playable tracks"):
        _plan((CURRENT, FOLLOWING), (release_track("source"),), choices, target=())
    assert choices.events == [("choose", (SOURCE, CURRENT, FOLLOWING))]


@pytest.mark.parametrize("catalog", [(), (FOLLOWING,)])
def test_original_ineligible_source_completes_or_prompts_first_release(
    catalog: tuple[DiscographyRelease, ...],
) -> None:
    """Ineligible markers either finish immediately or ask to enter the first release.

    Args:
        catalog: Empty or eligible observed catalog.
    """
    choices = PlanChoices()
    plan = _plan(catalog, (), choices)
    assert plan is not None and plan["evaluation"] is None
    assert plan["action"] == ("next_release" if catalog else "complete")
    assert plan["reason"] == (
        "moved from an ineligible marker to the first studio release"
        if catalog
        else "artist has no eligible studio album or EP"
    )


def test_original_equal_date_order_checkpoints_before_transition() -> None:
    """Queue 3 accepts catalog tie order without adding another operator prompt."""
    following = replace(FOLLOWING, chronology_date=CURRENT.chronology_date)
    choices = PlanChoices()
    plan = _plan((CURRENT, following), (release_track("source"),), choices)
    assert plan is not None and plan["action"] == "next_release"
    assert choices.events == [("save", None), ("choose", (SOURCE, CURRENT, following))]
