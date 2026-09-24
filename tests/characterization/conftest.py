"""Controlled clocks and explicit, separate-directory snapshot capture."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from tests.support.effects import FixedDatetime
from tests.support.isolation import application_modules


def pytest_addoption(parser):
    parser.addoption(
        "--characterization-output",
        type=Path,
        help="Write candidate traces to a separate directory for review",
    )


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    for module in application_modules():
        if getattr(module, "datetime", None) is datetime:
            monkeypatch.setattr(module, "datetime", FixedDatetime)


@pytest.fixture
def assert_trace(request):
    fixtures = Path(__file__).parent / "fixtures"
    destination = request.config.getoption("--characterization-output")
    if destination:
        destination = destination.resolve()
        if destination.is_relative_to(fixtures.resolve()):
            raise pytest.UsageError(
                "Capture to a separate directory; review before replacing fixtures"
            )
        destination.mkdir(parents=True, exist_ok=True)

    def compare(name, actual):
        if destination:
            # One event per line keeps a complete ordered trace reviewable.
            (destination / f"{name}.json").write_text(
                "[\n"
                + ",\n".join(
                    "  " + json.dumps(event, sort_keys=True) for event in actual
                )
                + "\n]\n",
                encoding="utf-8",
            )
        else:
            expected = json.loads((fixtures / f"{name}.json").read_text())
            assert actual == expected

    return compare
