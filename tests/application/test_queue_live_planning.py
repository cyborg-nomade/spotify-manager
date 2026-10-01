"""Verify complete Queue planning decisions and ordered reads through memory ports."""

import pytest

from tests.support.queue_planning import cases
from tests.support.queue_planning_application import application_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_independent_queue_planning_matches_original(
    name: str, case: dict[str, object]
) -> None:
    """Retain original plan fields, promotion cache reuse and catalog read order.

    Args:
        name: Original immutable planning scenario identifier.
        case: Original configured facts and observed plan/read trace.
    """
    assert name
    assert application_outcome(case) == case["outcome"]
