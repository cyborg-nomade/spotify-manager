"""Freeze Something Old mode choices, empty-playlist authority and accepted effects."""

from typing import cast

import pytest

from tests.support.something_old_run import cases
from tests.support.something_old_run import original_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_original_something_old_run(name: str, case: dict[str, object]) -> None:
    """Match original complete summaries and boundary failure prefixes.

    Args:
        name: Original immutable scenario identifier.
        case: Original configured mode, preview and observed outcome.
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
