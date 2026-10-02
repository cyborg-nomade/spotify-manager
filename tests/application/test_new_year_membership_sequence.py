"""Compare original annual reconciliation across lost responses."""

import json
from typing import cast

import pytest

from spotify_manager.application.new_year_membership import AnnualMembership
from tests.application.test_new_year_workflow import MemoryAnnual
from tests.support.new_year_boundaries import cases
from tests.support.new_year_boundaries import reconcile_outcome
from tests.support.new_year_run import AnnualObservations


def _outcome(case: dict[str, object]) -> object:
    edge = AnnualObservations(
        "normal", cast(str | None, case["failure"]), bool(case["automatic"])
    )
    edge.contents["destination"] = ["other", "uri-0", "uri-100"]
    memory = MemoryAnnual(edge, edge.retry)
    owner = AnnualMembership(memory.playlist, memory.append, memory.move, edge.retry)
    uris = [f"uri-{index}" for index in range(cast(int, case["size"]))] + [
        "uri-0",
        "uri-0",
    ]
    result: dict[str, object] = {}
    try:
        owner.run("destination", uris, bool(case["top"]))
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result.update(trace=edge.trace, contents=edge.contents["destination"])
    return json.loads(json.dumps(result))


@pytest.mark.parametrize("case", cases("new_year_reconciliation.json"))
def test_injected_annual_reconciliation_matches_original_retry_attempts(
    case: dict[str, object],
) -> None:
    """Retain original batches and recalculated membership/reorder positions.

    Args:
        case: Original immutable reconciliation and response-loss inputs.
    """
    assert _outcome(case) == case["outcome"]
    assert (
        reconcile_outcome(
            bool(case["top"]),
            cast(str | None, case["failure"]),
            bool(case["automatic"]),
            cast(int, case["size"]),
        )
        == case["outcome"]
    )
