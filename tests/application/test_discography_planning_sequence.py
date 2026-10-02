"""Compare complete injected Discography plans with immutable original effects."""

from functools import partial
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.discography_planning import DiscographyPlanning
from spotify_manager.application.discography_planning import DiscographyReads
from spotify_manager.domain.discography_values import DiscographyPlan
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName
from tests.support.discography_run import PlanReads
from tests.support.discography_run import cases
from tests.support.discography_run import original_plan
from tests.support.discography_run import plan_outcome


def _priority(edge: PlanReads) -> dict[str, object]:
    edge.state(Path("state"), None)
    return edge.load()


def _resolve(edge: PlanReads, selection: HistoricalArtistSelection) -> QueueArtist:
    return edge.map(selection)


def planner(edge: PlanReads) -> DiscographyPlanning:
    """Compose original complete facts without SDK or mutable routine patches.

    Args:
        edge: Original configured observation boundary.

    Returns:
        Independently injectable original planning use case.
    """
    reads = DiscographyReads(
        partial(_priority, edge),
        edge.queues,
        edge.history,
        partial(_resolve, edge),
        edge.catalog,
        edge.choose,
        edge.progress,
    )
    return DiscographyPlanning(reads)


def _run(edge: PlanReads) -> DiscographyPlan:
    return planner(edge).run()


@pytest.mark.parametrize("case", cases())
def test_discography_complete_injected_plan_matches_original(
    case: dict[str, object],
) -> None:
    """Preserve lazy fallback, caches, choices, packing and failure prefixes.

    Args:
        case: Original immutable input and observation.
    """
    edge = PlanReads(
        cast(str, case["profile"]),
        cast(QueueName, case["start"]),
        cast(str | None, case["failure"]),
    )
    assert plan_outcome(edge, _run) == case["outcome"]
    original = PlanReads(edge.profile, edge.start, edge.failure)
    assert plan_outcome(original, original_plan) == case["outcome"]


@pytest.mark.parametrize("profile", ["normal", "empty", "decline"])
def test_discography_caches_empty_and_complete_interactive_authority(
    profile: str,
) -> None:
    """Retain complete and empty cache hits without repeating catalog or choice reads.

    Args:
        profile: Original complete, empty or declined catalog/choice behavior.
    """
    edge = PlanReads(profile, "newfoundland")
    use_case = planner(edge)
    candidate = QueueArtist("a", "Alpha", "newfoundland")
    first = use_case._choose(candidate)
    trace = list(edge.trace)
    assert use_case._choose(candidate) == first
    assert edge.trace == trace
    assert use_case._catalog(candidate) == edge.catalog(candidate)
