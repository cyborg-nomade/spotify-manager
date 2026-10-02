"""Replay original Queue flush and restart effects through independent ports."""

from typing import cast

import pytest

from tests.support.queue_flush import cases
from tests.support.queue_flush_application import application_outcome


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_independent_queue_flush_matches_original(
    name: str, case: dict[str, object]
) -> None:
    """Match authoritative stored plans and accepted write/checkpoint prefixes.

    Args:
        name: Original immutable scenario identity.
        case: Original configured inputs and complete effect observations.
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
