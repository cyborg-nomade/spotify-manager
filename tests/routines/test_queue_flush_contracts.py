"""Freeze Queue flush results, accepted write prefixes and restart authority."""

from typing import cast

import pytest

from tests.support.queue_flush import cases
from tests.support.queue_flush import original_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_original_queue_flush_contract(name: str, case: dict[str, object]) -> None:
    """Match the complete implementation recorded before coordinator extraction.

    Args:
        name: Original immutable scenario identifier.
        case: Original configured inputs and observed outcome.
    """
    assert name
    assert (
        original_outcome(
            cast(str, case["scenario"]),
            cast(bool, case["preview"]),
            cast(str | None, case["failure"]),
        )
        == case["outcome"]
    )
