"""Verify Queue artist aggregation independently of legacy adapters."""

import json
from dataclasses import asdict
from datetime import date
from typing import cast

import pytest

from spotify_manager.domain.queue_candidates import QueueCandidates
from tests.support.queue_neighbors import NEIGHBORS
from tests.support.queue_neighbors import SEEDS
from tests.support.queue_neighbors import cases


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_queue_ranking_matches_original(name: str, case: dict[str, object]) -> None:
    """Preserve scores, display spelling, support labels and slice boundaries.

    Args:
        name: Immutable original scenario identifier.
        case: Original ranking inputs and observed result.
    """
    assert name
    candidates = QueueCandidates({"heard", "previous"})
    for seed in SEEDS:
        similar = tuple(reversed(NEIGHBORS)) if seed.artist == "Seed B" else NEIGHBORS
        candidates.observe(seed, similar)
    ranked = candidates.ranked(
        date.fromisoformat(cast(str, case["week"])), cast(int, case["limit"])
    )
    expected = cast(dict[str, object], case["outcome"])
    assert (
        json.loads(json.dumps([asdict(candidate) for candidate in ranked]))
        == expected["result"]
    )


def test_queue_empty_neighborhood_has_no_candidates() -> None:
    """Keep valid empty neighborhoods empty without adding placeholder artists."""
    candidates = QueueCandidates(set())
    candidates.observe(SEEDS[0], ())
    assert candidates.ranked(date(2026, 8, 7), 100) == ()
