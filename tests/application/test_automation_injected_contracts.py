"""Replay original nightly outcomes, messages and complete ordered API observations."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.application.automation_memory import run_automation
from tests.support.automation_run import AutomationScenario
from tests.support.automation_run import FixedDatetime
from tests.support.automation_run import automation_scenarios
from tests.support.automation_run import observe_automation


ORIGINAL = json.loads(
    (Path(__file__).parents[1] / "fixtures/refactor/automation_run.json").read_text()
)


@pytest.fixture(scope="module")
def automation_module() -> ModuleType:
    """Load the original executable compatibility boundary with a fixed clock.

    Returns:
        Script public entry points without running its CLI.
    """
    path = Path(__file__).parents[2] / ".github/scripts/nightly_refresh.py"
    spec = importlib.util.spec_from_file_location("automation_contract_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.__dict__["datetime"] = FixedDatetime
    return module


@pytest.mark.parametrize("index,scenario", list(enumerate(automation_scenarios())))
def test_original_automation_contract(
    automation_module: ModuleType, index: int, scenario: AutomationScenario
) -> None:
    """Retain original retries, reconnection, partial outcomes and native failures.

    Args:
        automation_module: Original executable facade.
        index: Immutable original fixture position.
        scenario: Original API response profile.
    """
    assert (
        observe_automation(automation_module, scenario, run_automation)
        == ORIGINAL[index]
    )
