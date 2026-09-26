"""CLI and HTTP entry points executing the real migrated use cases."""

import json
from collections.abc import Callable
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy import Spotify
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from tests.infrastructure.test_listening_adapters import _client
from tests.infrastructure.test_listening_adapters import _recorded_album
from tests.infrastructure.test_listening_adapters import _track
from tests.routines.test_requeue_for_a_dream import FakeSpotify
from tests.routines.test_requeue_for_a_dream import configured_spotify


PLAYLIST_ID = "p" * 22


def _provided_client(client: Spotify) -> Spotify:
    return client


def _http_client(monkeypatch: pytest.MonkeyPatch, client: Spotify) -> TestClient:
    provider = partial(_provided_client, client)
    overrides = dict(api.app.dependency_overrides)
    overrides[api.get_client] = provider
    overrides[api.get_interactive_client] = provider
    monkeypatch.setattr(api.app, "dependency_overrides", overrides)
    return TestClient(api.app)


def test_album_http_executes_use_case_and_preserves_wire_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the independently captured legacy response through the real route.

    Args:
        monkeypatch: Scoped dependency overrides.
    """
    client = _client([_track("x"), _track("x")], [True, False])
    http = _http_client(monkeypatch, client)
    response = http.get("/albums/evaluation", params={"album_id": "album"})
    assert response.status_code == 200
    assert response.json() == _recorded_album(["x", "x"])["result"]
    client.current_user_saved_tracks_contains.assert_called_once_with(["x", "x"])


def test_album_cli_executes_use_case_and_preserves_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the real command through composition and the shared result presenter.

    Args:
        monkeypatch: Scoped client factory override.
    """
    client = _client([_track("x")], [True])
    monkeypatch.setattr(main, "client", Mock(return_value=client))
    result = CliRunner().invoke(main.app, ["album-decision", "--album-id", "album"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == _recorded_album(["x"])["result"]
    client.album.assert_called_once_with("album")


def test_album_transport_failure_keeps_http_and_cli_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the existing public errors after transport failure in the use case.

    Args:
        monkeypatch: Scoped client dependency overrides.
    """
    client = _client([], [])
    client.album.side_effect = RequestsConnectionError("offline")
    response = _http_client(monkeypatch, client).get(
        "/albums/evaluation", params={"album_id": "album"}
    )
    assert response.status_code == 502
    assert "several attempts" in response.json()["detail"]
    monkeypatch.setattr(main, "client", Mock(return_value=client))
    result = CliRunner().invoke(main.app, ["album-decision", "--album-id", "album"])
    assert result.exit_code == 1
    assert "several attempts" in result.stderr


class InlineThread:
    """Execute the real HTTP worker deterministically at its existing start boundary.

    Args:
        target: Existing worker callback supplied by the job launcher.
        args: Existing worker arguments.
        name: Thread label, irrelevant to the synchronous test executor.
        daemon: Original thread lifetime flag.
    """

    def __init__(
        self,
        *,
        target: Callable[..., None],
        args: tuple[object, ...],
        name: str,
        daemon: bool,
    ) -> None:
        """Store the worker invocation without executing it.

        Args:
            target: Existing worker callback.
            args: Original worker arguments.
            name: Original thread label.
            daemon: Original lifetime flag.
        """
        self.target = target
        self.args = args

    def start(self) -> None:
        """Run the real worker once; its normal job-state handling remains active."""
        self.target(*self.args)


def _configure_requeue(monkeypatch: pytest.MonkeyPatch) -> FakeSpotify:
    spotify, _, _ = configured_spotify()
    settings = Mock(
        return_value=SimpleNamespace(reqeueue_for_a_dream_playlist=PLAYLIST_ID)
    )
    monkeypatch.setattr(api, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "Thread", InlineThread)
    monkeypatch.setattr(api, "_blast_jobs", {})
    return spotify


def _requeue_request(http: TestClient, dry_run: bool) -> dict[str, object]:
    response = http.post(
        "/commands/flush-requeue-for-a-dream", params={"dry_run": dry_run}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    completed = http.get(f"/commands/flush-requeue-for-a-dream-jobs/{job_id}")
    assert completed.status_code == 200
    return dict(completed.json())


@pytest.mark.parametrize("dry_run", [False, True])
def test_requeue_http_runs_complete_slice(
    monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    """Execute the real job worker, use case, effects, and HTTP result translation.

    Args:
        monkeypatch: Scoped client, configuration, and thread dependencies.
        dry_run: Whether to preview or mutate the simulated playlist.
    """
    spotify = _configure_requeue(monkeypatch)
    result = _requeue_request(_http_client(monkeypatch, spotify), dry_run)
    assert result["status"] == "completed"
    assert result["requeue_action"] == "advance"
    assert result["requeue_target_track"] == "First Track"
    assert result["playlist_length_before"] == result["playlist_length_after"] == 1
    assert spotify.mutations == ([] if dry_run else [("add", "t2a"), ("remove", "t1")])


@pytest.mark.parametrize("dry_run", [False, True])
def test_requeue_cli_runs_complete_slice(
    monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    """Execute the real command and preserve its summary and mutation order.

    Args:
        monkeypatch: Scoped client and configuration dependencies.
        dry_run: Whether the command includes the preview flag.
    """
    spotify = _configure_requeue(monkeypatch)
    arguments = ["flush-requeue-for-a-dream"] + (["--dry-run"] if dry_run else [])
    result = CliRunner().invoke(main.app, arguments)
    assert result.exit_code == 0, result.output
    assert "Requeue for a Dream" in result.stdout
    assert "First Track" in result.stdout
    assert spotify.mutations == ([] if dry_run else [("add", "t2a"), ("remove", "t1")])


def test_http_restart_after_accepted_replacement_does_not_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the existing recovery path after append succeeds and removal fails.

    Args:
        monkeypatch: Scoped integration and deterministic worker dependencies.
    """
    spotify = _configure_requeue(monkeypatch)
    spotify.fail_next_delete = True
    http = _http_client(monkeypatch, spotify)
    failed = _requeue_request(http, False)
    assert failed["status"] == "failed"
    assert spotify.mutations == [("add", "t2a")]
    resumed = _requeue_request(http, False)
    assert resumed["status"] == "completed"
    assert resumed["requeue_target_already_present"] is True
    assert spotify.mutations == [("add", "t2a"), ("remove", "t1")]
