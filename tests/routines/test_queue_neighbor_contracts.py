"""Protect Queue ranking, exclusions, duplicate support and cache persistence."""

from datetime import date
from typing import cast

import pytest

from tests.support.queue_neighbors import cases
from tests.support.queue_neighbors import original_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_original_queue_neighbor_contract(name: str, case: dict[str, object]) -> None:
    """Retain original observations from the implementation before extraction.

    Args:
        name: Frozen scenario identifier.
        case: Original limit, listening week and observed outcome.
    """
    assert name
    assert (
        original_outcome(
            cast(int, case["limit"]), date.fromisoformat(cast(str, case["week"]))
        )
        == case["outcome"]
    )
