"""Queue 3 chronology preserves observations, choices and checkpoint boundaries."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.queue_3_planner import Queue3Planner
from spotify_manager.application.queue_3_planner import stable_release_order
from spotify_manager.application.queue_3_values import Queue3Error
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


FIRST = studio_release("first", "First", "2000")
SECOND = studio_release("second", "Second", "2001")
SOURCE = playlist_track("source", FIRST)
TARGET = release_track("target")


@dataclass
class PlannerMemory:
    """Supply catalogs and observe choices, evaluation and ordering writes.

    Args:
        observed: Track lists returned for each requested release.
        choice: Operator response at a release boundary.
        failure: Boundary to fail before accepting its effect.
        events: Ordered external boundary observations.
    """

    observed: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=dict)
    choice: str = "advance"
    failure: str | None = None
    events: list[tuple[str, object]] = field(default_factory=list)

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if self.failure == name:
            raise OSError(name)

    def read(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Observe a track read.

        Args:
            release: Requested selected edition.

        Returns:
            Configured ordered tracks, defaulting to an empty release.
        """
        self._record("read", release.spotify_id)
        return self.observed.get(release.spotify_id, ())

    def evaluate(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...]
    ) -> AlbumEvaluation:
        """Observe live evaluation before ordering or prompting a successor.

        Args:
            release: Completed selected edition.
            tracks: Complete observed tracks.

        Returns:
            A live all-unliked evaluation with the original public model.
        """
        self._record("evaluate", release.spotify_id)
        return evaluate_release(playlist_track("unused", release).release, tracks, {})

    def choose(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
    ) -> str:
        """Observe the original release-boundary choice.

        Args:
            source: Original marker.
            current: Completed or ineligible source release.
            following: Proposed successor.

        Returns:
            Configured operator response.
        """
        self._record("choice", (source, current, following))
        return self.choice

    def save(self) -> None:
        """Observe an accepted same-date ordering checkpoint."""
        self._record("checkpoint", None)


def _planner(memory: PlannerMemory) -> Queue3Planner:
    ordering = ReleaseOrdering(stable_release_order, {}, memory.save)
    return Queue3Planner(memory.read, memory.evaluate, {}, ordering, memory.choose)


@pytest.mark.parametrize("cached", [False, True])
def test_within_release_advance_needs_no_likes_or_choice(cached: bool) -> None:
    """The next playable marker uses one shared observation across repeated plans.

    Args:
        cached: Whether observations were supplied by an earlier entry.
    """
    tracks = (release_track("source"), TARGET)
    memory = PlannerMemory({"first": tracks})
    planner = _planner(memory)
    if cached:
        planner.tracks["first"] = tracks
    plan = planner.plan(SOURCE, (FIRST, SECOND))
    assert plan == {
        "action": "advance",
        "current_release": asdict(FIRST),
        "target_release": asdict(FIRST),
        "target": asdict(TARGET),
        "evaluation": None,
        "reason": None,
    }
    assert planner.plan(SOURCE, (FIRST, SECOND)) == plan
    assert memory.events == ([] if cached else [("read", "first")])


@pytest.mark.parametrize("tracks", [(), (TARGET,)])
def test_unmapped_marker_restarts_or_completes_without_live_evaluation(
    tracks: tuple[ReleaseTrack, ...],
) -> None:
    """An empty edition and an edition with no matching marker retain distinct reasons.

    Args:
        tracks: Empty or unmatched preferred-edition observations.
    """
    memory = PlannerMemory({"first": tracks})
    planner = _planner(memory)
    plan = planner.plan(SOURCE, (FIRST,))
    assert plan is not None and plan["evaluation"] is None
    assert plan["action"] == ("advance" if tracks else "complete")
    assert plan["reason"] == (
        "restarted the preferred edition at its first track"
        if tracks
        else "current eligible release has no playable tracks"
    )
    assert planner.plan(SOURCE, (FIRST,)) == plan
    assert memory.events == [("read", "first")]


@pytest.mark.parametrize("catalog", [(), (SECOND,)])
def test_ineligible_source_starts_at_first_eligible_release(
    catalog: tuple[DiscographyRelease, ...],
) -> None:
    """Ineligible sources avoid unnecessary current-release and liked-status reads.

    Args:
        catalog: Empty or eligible observed catalog.
    """
    memory = PlannerMemory({"second": (TARGET,)})
    plan = _planner(memory).plan(SOURCE, catalog)
    assert plan is not None and plan["evaluation"] is None
    assert plan["action"] == ("next_release" if catalog else "complete")
    assert [name for name, value in memory.events] == (
        ["choice", "read"] if catalog else []
    )


def test_last_track_of_final_release_has_evaluation_and_no_target() -> None:
    """Final completion keeps the live album decision without another prompt."""
    memory = PlannerMemory({"first": (release_track("source"),)})
    plan = _planner(memory).plan(SOURCE, (FIRST,))
    assert plan is not None
    assert plan["action"] == "complete" and plan["target"] is None
    assert plan["reason"] == "last track of the final studio release"
    evaluation = plan["evaluation"]
    assert isinstance(evaluation, dict) and evaluation["decision"] == "remove"
    assert memory.events == [("read", "first"), ("evaluate", "first")]


@pytest.mark.parametrize("choice", ["advance", "quit", "invalid"])
def test_boundary_evaluates_then_checkpoints_order_before_choice(choice: str) -> None:
    """An equal-date successor prompts only after saving the deterministic tie order.

    Args:
        choice: Scripted boundary response.
    """
    second = replace(SECOND, chronology_date=FIRST.chronology_date)
    memory = PlannerMemory(
        {"first": (release_track("source"),), "second": (TARGET,)}, choice
    )
    planner = _planner(memory)
    if choice == "invalid":
        with pytest.raises(
            Queue3Error, match="Release transition must be advance or quit"
        ):
            planner.plan(SOURCE, (FIRST, second))
        assert memory.events[-1][0] == "choice"
        return
    plan = planner.plan(SOURCE, (FIRST, second))
    assert (plan is None) == (choice == "quit")
    assert [name for name, value in memory.events] == (
        ["read", "evaluate", "checkpoint", "choice", "read"]
        if choice == "advance"
        else ["read", "evaluate", "checkpoint", "choice"]
    )
    assert planner.ordering.saved == {"artist:2000": ["first", "second"]}


def test_accepted_empty_successor_retains_cached_empty_observation() -> None:
    """A failed transition never refetches a known empty release in the same run."""
    memory = PlannerMemory()
    planner = _planner(memory)
    for _attempt in range(2):
        with pytest.raises(Queue3Error, match="Second has no playable tracks"):
            planner.transition(SOURCE, FIRST, SECOND)
    assert [name for name, value in memory.events] == ["choice", "read", "choice"]
    assert planner.tracks == {"second": ()}


@pytest.mark.parametrize("failure", ["read", "evaluate", "checkpoint", "choice"])
def test_planner_failures_stop_at_original_observation_boundaries(failure: str) -> None:
    """Failed effects do not proceed to later reads, choices or writes.

    Args:
        failure: Selected boundary interruption.
    """
    memory = PlannerMemory({"first": (release_track("source"),)}, failure=failure)
    planner = _planner(memory)
    second = replace(SECOND, chronology_date=FIRST.chronology_date)
    with pytest.raises(OSError, match=failure):
        planner.plan(SOURCE, (FIRST, second))
    assert memory.events[-1][0] == failure
    assert bool(planner.tracks) == (failure != "read")
    assert bool(planner.ordering.saved) == (failure in {"checkpoint", "choice"})
