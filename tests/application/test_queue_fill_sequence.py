"""Verify complete Queue fill sequencing against immutable original observations."""

from typing import cast

import pytest

from tests.support.queue_fill import cases
from tests.support.queue_fill_application import application_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_independent_queue_fill_matches_original(
    name: str, case: dict[str, object]
) -> None:
    """Preserve mapping learning, preview writes and accepted-effect failure order.

    Args:
        name: Original immutable scenario identifier.
        case: Original input and complete observed outcome.
    """
    assert name
    assert (
        application_outcome(
            cast(str, case["scenario"]),
            cast(bool, case["preview"]),
            cast(str | None, case["failure"]),
        )
        == case["outcome"]
    )
