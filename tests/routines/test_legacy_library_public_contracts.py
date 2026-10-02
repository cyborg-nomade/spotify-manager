"""Replay original legacy results, visible output and every accepted effect."""

import json
from pathlib import Path

import pytest

from tests.support.legacy_library_run import Scenario
from tests.support.legacy_library_run import observe
from tests.support.legacy_library_run import scenarios


CASES = scenarios()
ORIGINAL = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/refactor/legacy_library_run.json"
    ).read_text()
)


@pytest.mark.parametrize("index,scenario", list(enumerate(CASES)))
def test_original_complete_legacy_workflow(index: int, scenario: Scenario) -> None:
    """Preserve original results, effects, bytes and partial acceptance.

    Args:
        index: Immutable original observation index.
        scenario: Original workflow and interruption.
    """
    assert observe(scenario) == ORIGINAL[index]
