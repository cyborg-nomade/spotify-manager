"""Compare independently assembled legacy workflows to the original oracle."""

import json
from pathlib import Path

import pytest

from tests.application.legacy_library_memory import run
from tests.support.legacy_library_run import Scenario
from tests.support.legacy_library_run import observe
from tests.support.legacy_library_run import scenarios


ORIGINAL = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/refactor/legacy_library_run.json"
    ).read_text()
)


@pytest.mark.parametrize("index,scenario", list(enumerate(scenarios())))
def test_original_application_sequence(index: int, scenario: Scenario) -> None:
    """Preserve original effects with independently injected stages.

    Args:
        index: Immutable original observation index.
        scenario: Original workflow and interruption.
    """
    assert observe(scenario, run) == ORIGINAL[index]
