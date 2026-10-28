"""Replay original Palace history, population and random-source observations."""

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.palace_history import PalaceHistory
from tests.support.palace_history import HistoryInputs
from tests.support.palace_history import HistoryReads
from tests.support.palace_history import cases
from tests.support.palace_history import original_outcome


def _cutoff() -> date:
    return date(2025, 12, 31)


async def _run(edge: HistoryReads, count: int) -> object:
    workflow = PalaceHistory(
        HistoryInputs(edge, Path("history"), _cutoff()),
        edge,
        date(2007, 11, 27),
    )
    generated, cutoff, available, selected = await workflow.run(count)
    return {
        "generated": generated,
        "cutoff": cutoff,
        "available": available,
        "selected": [asdict(album) for album in selected],
    }


async def _outcome(case: dict[str, object]) -> object:
    edge = HistoryReads(cast(str, case["profile"]), cast(int, case["second"]))
    result: dict[str, object] = {}
    try:
        result["result"] = await _run(edge, cast(int, case["count"]))
    except (RuntimeError, IndexError) as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("case", cases())
async def test_palace_history_matches_original_population_and_random_reads(
    case: dict[str, object],
) -> None:
    """Protect date eligibility, seconds-only ranks and custom-reader tolerance.

    Args:
        case: Immutable original history inputs and complete observations.
    """
    assert (
        await original_outcome(
            cast(str, case["profile"]),
            cast(int, case["count"]),
            cast(int, case["second"]),
        )
    ) == case["outcome"]
    assert (await _outcome(case)) == case["outcome"]
