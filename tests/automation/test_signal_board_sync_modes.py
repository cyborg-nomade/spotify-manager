"""Verify matching history/Spotify modes through the real automation entry point."""

import importlib.util
import sys
from dataclasses import dataclass
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from pytest_mock import MockerFixture

from tests.automation.test_nightly_refresh_automation import FakeClient


@dataclass(frozen=True)
class CalendarInstant:
    """Supply an explicit instant through the script's external datetime seam.

    Args:
        value: Aware instant used by every observation in one dispatch.
    """

    value: datetime

    def now(self, timezone: tzinfo) -> datetime:
        """Observe the fixed instant in the requested timezone.

        Args:
            timezone: Script-selected timezone.

        Returns:
            The fixed aware instant.
        """
        return self.value.astimezone(timezone)


@pytest.fixture
def dispatcher() -> ModuleType:
    """Load a fresh script without altering other automation fixtures.

    Returns:
        The real main entry point and compatibility resources.
    """
    path = Path(__file__).parents[2] / ".github/scripts/nightly_refresh.py"
    spec = importlib.util.spec_from_file_location("signal_board_dispatch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _responses(check_freshness: bool) -> list[object]:
    responses: list[object] = [{"status": "ok"}]
    if check_freshness:
        responses.append({"files": []})
    for index in range(4):
        responses.append({"job_id": str(index)})
        responses.append({"status": "completed", "detail": "Already current"})
    return responses


def _bind(
    dispatcher: ModuleType, mocker: MockerFixture, instant: str, client: FakeClient
) -> None:
    mocker.patch.object(
        dispatcher, "datetime", CalendarInstant(datetime.fromisoformat(instant))
    )
    mocker.patch.object(
        dispatcher,
        "required_environment",
        return_value=("https://space.test", "hf-test", "automation-test"),
    )
    mocker.patch.object(dispatcher, "SpaceClient", return_value=client)


@pytest.mark.parametrize(
    ("instant", "arguments", "history_full", "spotify_full", "freshness"),
    [
        ("2026-11-02T00:17:00+01:00", ["--scheduled"], False, False, True),
        ("2026-11-01T22:17:00+01:00", ["--scheduled"], False, False, True),
        (
            "2026-11-07T22:37:00+01:00",
            ["--scheduled", "--full-rebuild"],
            True,
            True,
            True,
        ),
        (
            "2026-11-08T00:37:00+01:00",
            ["--scheduled", "--full-rebuild"],
            True,
            True,
            True,
        ),
        (
            "2026-03-29T00:37:00+01:00",
            ["--scheduled", "--full-rebuild"],
            True,
            True,
            True,
        ),
        (
            "2026-10-25T00:37:00+02:00",
            ["--scheduled", "--full-rebuild"],
            True,
            True,
            True,
        ),
        ("2027-01-01T00:17:00+01:00", ["--scheduled"], True, False, False),
        ("2026-11-03T14:00:00+01:00", ["--full-rebuild"], True, True, False),
        ("2026-11-08T14:00:00+01:00", [], False, False, False),
    ],
)
def test_main_dispatches_all_four_sources_in_the_selected_mode(
    dispatcher: ModuleType,
    mocker: MockerFixture,
    instant: str,
    arguments: list[str],
    history_full: bool,
    spotify_full: bool,
    freshness: bool,
) -> None:
    """Exercise modes, annual override, delayed probes, DST, and unchanged results.

    Args:
        dispatcher: Fresh real automation entry point.
        mocker: Framework replacements for time and authenticated transport.
        instant: Aware run time around calendar boundaries.
        arguments: Actual CLI selections used by Actions or manual dispatch.
        history_full: Expected Last.fm rebuild selection.
        spotify_full: Expected mode for all three Spotify mirrors.
        freshness: Whether the duplicate-trigger read must occur.
    """
    client = FakeClient(_responses(freshness))
    _bind(dispatcher, mocker, instant, client)
    assert dispatcher.main(arguments) == 0
    starts = []
    for method, path in client.calls:
        if method == "POST":
            starts.append(urlsplit(path))
    assert [item.path for item in starts] == [
        "/commands/update-scrobble-history",
        "/commands/refresh-library-mirrors/albums",
        "/commands/refresh-library-mirrors/tracks",
        "/commands/refresh-library-mirrors/artists",
    ]
    history_query = parse_qs(starts[0].query)
    assert history_query["dry_run"] == ["false"]
    assert history_query.get("full_rebuild", ["false"]) == [str(history_full).lower()]
    for item in starts[1:]:
        assert parse_qs(item.query) == {"full_rebuild": [str(spotify_full).lower()]}
    assert (("GET", "/library-mirrors/status") in client.calls) is freshness


@pytest.mark.parametrize(
    "instant", ["2026-11-07T19:37:00+01:00", "2026-11-08T05:00:00+01:00"]
)
def test_scheduled_full_probe_outside_window_starts_nothing(
    dispatcher: ModuleType,
    mocker: MockerFixture,
    instant: str,
) -> None:
    """Keep early and expired workflow probes from starting a history rebuild.

    Args:
        dispatcher: Fresh real automation entry point.
        mocker: Framework time and transport replacements.
        instant: Early evening or closed maintenance-window instant.
    """
    client = FakeClient([])
    _bind(dispatcher, mocker, instant, client)
    assert dispatcher.main(["--scheduled", "--full-rebuild"]) == 0
    assert client.calls == []
