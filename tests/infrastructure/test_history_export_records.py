"""Replay original deployment source precedence and malformed byte boundaries."""

import json
from pathlib import Path

import pytest

from tests.support.history_export_records import ExportScenario
from tests.support.history_export_records import export_scenarios
from tests.support.history_export_records import observe_export


ORIGINAL = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/refactor/history_export_records.json"
    ).read_text()
)


@pytest.mark.parametrize("index,scenario", list(enumerate(export_scenarios())))
def test_original_history_export_codec(
    index: int, scenario: ExportScenario, tmp_path: Path
) -> None:
    """Retain original source priority, native failures and translated diagnostics.

    Args:
        index: Original immutable fixture position.
        scenario: Original source and raw response profile.
        tmp_path: Isolated managed source directory.
    """
    assert observe_export(scenario, tmp_path) == ORIGINAL[index]
