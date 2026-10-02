"""Protect original persistence bytes and accepted failure prefixes."""

import json
from pathlib import Path

import pytest

from tests.support.legacy_library_files import FileScenario
from tests.support.legacy_library_files import file_scenarios
from tests.support.legacy_library_files import observe_file


ORIGINAL = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/refactor/legacy_library_files.json"
    ).read_text()
)


@pytest.mark.parametrize("index,scenario", list(enumerate(file_scenarios())))
def test_original_persistence_contract(index: int, scenario: FileScenario) -> None:
    """Replay original output, bytes and replacement/publication acceptance.

    Args:
        index: Immutable original observation index.
        scenario: Original persistence boundary.
    """
    assert observe_file(scenario) == ORIGINAL[index]
