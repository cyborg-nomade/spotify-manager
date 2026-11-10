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

from spotify_manager.application.automation_values import DURABLE_ARTIFACT_FILENAMES
from tests.automation.test_nightly_refresh_automation import FakeClient
from tests.support.automation_flush import flush_payload


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
    responses: list[object] = [{"status": "ok"}, flush_payload()]
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
        if method == "POST" and path.startswith("/commands/"):
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
    assert client.calls[1] == ("POST", "/flush-mode/check")


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


def test_duplicate_dispatches_still_check_policy_with_fresh_files(
    dispatcher: ModuleType,
    mocker: MockerFixture,
) -> None:
    """Each delayed probe checks counts even if every library artifact is current.

    Args:
        dispatcher: Real script entry point.
        mocker: Framework replacements for the external clock and client.
    """
    files = []
    for filename in DURABLE_ARTIFACT_FILENAMES:
        files.append(
            {
                "filename": filename,
                "exists": True,
                "updated_at": "2026-11-09T00:00:00+01:00",
            }
        )
    one_run = [{"status": "ok"}, flush_payload(), {"files": files}]
    client = FakeClient(one_run * 2)
    _bind(dispatcher, mocker, "2026-11-09T00:17:00+01:00", client)
    assert dispatcher.main(["--scheduled"]) == 0
    assert dispatcher.main(["--scheduled"]) == 0
    assert (
        client.calls
        == [
            ("GET", "/health"),
            ("POST", "/flush-mode/check"),
            ("GET", "/library-mirrors/status"),
        ]
        * 2
    )


def test_check_only_reads_policy_without_post_or_spotify_counts(
    dispatcher: ModuleType,
    mocker: MockerFixture,
) -> None:
    """Deployment verification remains read-only through the actual entry point.

    Args:
        dispatcher: Real script entry point.
        mocker: External time and client replacements.
    """
    files = []
    for filename in DURABLE_ARTIFACT_FILENAMES:
        files.append({"filename": filename, "exists": True})
    client = FakeClient(
        [
            {"status": "ok"},
            {"status": "ok"},
            {"files": files},
            {"revision": "state-sha"},
            {"paths": {"/one-jobs": {}}},
            [],
            flush_payload(),
        ]
    )
    _bind(dispatcher, mocker, "2026-11-09T14:00:00+01:00", client)
    assert dispatcher.main(["--check-only"]) == 0
    assert client.calls[-1] == ("GET", "/flush-mode")
    assert all(method == "GET" for method, _ in client.calls)


def test_flush_only_dispatch_updates_policy_without_library_requests(
    dispatcher: ModuleType,
    mocker: MockerFixture,
) -> None:
    """Provide a narrow live verification mode without four library jobs.

    Args:
        dispatcher: Real script entry point.
        mocker: External client and clock replacements.
    """
    client = FakeClient([flush_payload()])
    _bind(dispatcher, mocker, "2026-11-09T14:00:00+01:00", client)
    assert dispatcher.main(["--flush-mode-only"]) == 0
    assert client.calls == [("POST", "/flush-mode/check")]


def test_check_only_and_flush_only_cannot_be_combined(dispatcher: ModuleType) -> None:
    """The read-only mode cannot silently turn into a live check.

    Args:
        dispatcher: Real argument parser.
    """
    with pytest.raises(SystemExit) as raised:
        dispatcher.main(["--check-only", "--flush-mode-only"])
    assert raised.value.code == 2
