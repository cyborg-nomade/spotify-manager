"""Controlled clocks and explicit, separate-directory snapshot capture."""

import json
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest

from tests.support.effects import Event
from tests.support.effects import FixedDatetime
from tests.support.effects import TraceAssertion
from tests.support.isolation import application_modules


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register opt-in trace capture to a review directory.

    Args:
        parser: Pytest command-line option registry.
    """
    parser.addoption(
        "--characterization-output",
        type=Path,
        help="Write candidate traces to a separate directory for review",
    )


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze imported application clocks for repeatable observations.

    Args:
        monkeypatch: Per-test patch manager.
    """
    for module in application_modules():
        if getattr(module, "datetime", None) is datetime:
            monkeypatch.setattr(module, "datetime", FixedDatetime)


def _capture_trace(path: Path, events: list[Event]) -> None:
    lines = []
    for event in events:
        lines.append("  " + json.dumps(event, sort_keys=True))
    path.write_text("[\n" + ",\n".join(lines) + "\n]\n", encoding="utf-8")


def _compare_trace(
    fixtures: Path,
    destination: Path | None,
    name: str,
    actual: list[Event],
) -> None:
    if destination:
        _capture_trace(destination / f"{name}.json", actual)
        return
    expected = json.loads((fixtures / f"{name}.json").read_text())
    assert actual == expected


def _capture_directory(request: pytest.FixtureRequest, fixtures: Path) -> Path | None:
    destination: Path | None = request.config.getoption("--characterization-output")
    if destination is None:
        return None
    destination = destination.resolve()
    if destination.is_relative_to(fixtures.resolve()):
        raise pytest.UsageError(
            "Capture to a separate directory; review before replacing fixtures"
        )
    destination.mkdir(parents=True, exist_ok=True)
    return destination


@pytest.fixture
def assert_trace(request: pytest.FixtureRequest) -> TraceAssertion:
    """Compare traces to reviewed fixtures or capture separate candidates.

    Args:
        request: Pytest request containing the capture-directory option.

    Returns:
        Assertion accepting the scenario name and copied observations.

    Raises:
        pytest.UsageError: Capture would overwrite reviewed fixtures.
        OSError: The capture directory cannot be created.
    """
    fixtures = Path(__file__).parent / "fixtures"
    return partial(_compare_trace, fixtures, _capture_directory(request, fixtures))
