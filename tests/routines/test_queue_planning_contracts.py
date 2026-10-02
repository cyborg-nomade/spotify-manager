"""Protect original Queue planning thresholds, cursors and promotion cache reads."""

import pytest

from tests.support.queue_planning import cases
from tests.support.queue_planning import original_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_original_queue_planning_contract(name: str, case: dict[str, object]) -> None:
    """Retain every original plan and read order before extracting its policies.

    Args:
        name: Original immutable scenario identity.
        case: Original configured planning facts and observed outcome.
    """
    assert name
    assert original_outcome(case) == case["outcome"]
