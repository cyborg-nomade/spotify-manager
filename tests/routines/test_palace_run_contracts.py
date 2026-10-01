"""Freeze Palace's whole-run choices, live authority and accepted-effect prefixes."""

from typing import cast

import pytest

from tests.support.palace_run import cases
from tests.support.palace_run import original_outcome


@pytest.mark.parametrize("case", cases())
def test_original_palace_complete_run(case: dict[str, object]) -> None:
    """Retain original complete summaries and ordered failures.

    Args:
        case: Immutable original scenario and observed outcome.
    """
    assert (
        original_outcome(
            cast(str, case["scenario"]),
            bool(case["preview"]),
            cast(str | None, case["failure"]),
        )
        == case["outcome"]
    )
