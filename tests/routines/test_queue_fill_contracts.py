"""Retain original complete Queue fill results, checkpoints and failure prefixes."""

from typing import cast

import pytest

from tests.support.queue_fill import cases
from tests.support.queue_fill import original_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_queue_fill_original_contract(name: str, case: dict[str, object]) -> None:
    """Match the implementation recorded before business-rule extraction.

    Args:
        name: Original immutable scenario identifier.
        case: Original configured inputs and complete effect observations.
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
