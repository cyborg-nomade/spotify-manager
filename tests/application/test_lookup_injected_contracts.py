"""Replay complete original lookup outcomes, request order and cache effects."""

import json
from pathlib import Path

import pytest

from tests.application.lookup_memory import run_lookup
from tests.support.library_lookup_run import LookupScenario
from tests.support.library_lookup_run import lookup_scenarios
from tests.support.library_lookup_run import observe_lookup


ORIGINAL = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/refactor/library_lookup_run.json"
    ).read_text()
)


@pytest.mark.parametrize("index,scenario", list(enumerate(lookup_scenarios())))
def test_original_lookup_contract(index: int, scenario: LookupScenario) -> None:
    """Retain original results, native errors, SDK requests and accepted cache state.

    Args:
        index: Immutable original observation index.
        scenario: Original raw boundary profile.
    """
    assert observe_lookup(scenario, run_lookup) == ORIGINAL[index]
