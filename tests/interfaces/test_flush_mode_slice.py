"""Exercise real CLI/HTTP policy controls and every protected start route."""

import asyncio
from dataclasses import dataclass
from threading import Event
from time import monotonic
from time import sleep
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager import web
from spotify_manager._auth import PasswordMiddleware
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.bootstrap.flush_mode import flush_mode_state
from spotify_manager.core.state.definitions import ObjectDefinition
from spotify_manager.domain.flush_mode import FlushChange
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.interfaces.http import jobs
from tests.interfaces.test_vertical_slices import _http_client


@dataclass
class AdmittedFoundArt:
    """Hold an admitted worker at its external execution boundary.

    Args:
        entered: Signal that accepted execution has begun.
        release: Signal allowing accepted execution to finish.
    """

    entered: Event
    release: Event

    async def run(
        self,
        job_id: str,
        client: SpotifyClient,
        playlist_id: str,
        api_key: str,
        username: str,
        count: int,
        dry_run: bool,
    ) -> None:
        """Complete a registered job after the policy changes.

        Args:
            job_id: Actual registered handle.
            client: Unused external Spotify observation.
            playlist_id: Admitted destination.
            api_key: Admitted credential placeholder.
            username: Admitted username.
            count: Admitted selection count.
            dry_run: Admitted preview mode.
        """
        job = jobs.get_blast_job(job_id, command="found_art")
        with jobs._blast_jobs_lock:
            job.result.status = "running"
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        with jobs._blast_jobs_lock:
            job.result.status = "completed"


def _await_completion(http: TestClient, job_id: str) -> None:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        status = http.get("/commands/found-art-jobs/" + job_id).json()["status"]
        if status == "completed":
            return
        sleep(0.01)
    raise AssertionError("Admitted job could not finish after Flush Mode changed")


def _configuration() -> SimpleNamespace:
    return SimpleNamespace(
        the_queue_playlist="q" * 22,
        the_queue_2_playlist="t" * 22,
        the_queue_3_playlist="r" * 22,
        unlucky_ones_playlist="u" * 22,
        new_kids_on_the_block_playlist="n" * 22,
        great_discoveries_2026_playlist="g" * 22,
        discography_newfoundland_playlist="d" * 22,
        new_wine_from_old_bottles_playlist="w" * 22,
        sauvignon_terre_neuve_playlist="s" * 22,
        wine_cellar_playlist="c" * 22,
        found_art_playlist="f" * 22,
        lastfm_api_key="key",
        lastfm_username="listener",
    )


@pytest.mark.parametrize(
    "path",
    [
        "/commands/found-art",
        "/commands/fill-sauvignon-from-lastfm",
        "/commands/fill-queue-from-lastfm",
        "/commands/flush-queue",
        "/commands/flush-queue-2",
        "/commands/flush-queue-3",
        "/commands/import-queue-3-previous-year",
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_api_rejects_all_restricted_starts_before_job_registration(
    monkeypatch: pytest.MonkeyPatch, path: str, dry_run: bool
) -> None:
    """Crafted API requests cannot bypass the UI or resume blocked routines.

    Args:
        monkeypatch: Scoped interface configuration.
        path: Every protected playlist start/import endpoint.
        dry_run: Preview or apply mode; both must be blocked.
    """
    flush_mode_state().change(FlushChange(control="on"))
    monkeypatch.setattr(jobs, "Settings", _configuration)
    client = AsyncMock()
    with _http_client(monkeypatch, cast(SpotifyClient, client)) as http:
        before = set(jobs._blast_jobs)
        response = http.post(path, params={"dry_run": dry_run})
        assert response.status_code == 409 and "Flush Mode" in response.json()["detail"]
        assert set(jobs._blast_jobs) == before
    assert client.mock_calls == []


@pytest.mark.parametrize(
    "command",
    [
        "found-art",
        "genre-reveal",
        "fill-sauvignon-from-lastfm",
        "fill-queue-from-lastfm",
        "flush-queue",
        "flush-queue-2",
        "flush-queue-3",
        "import-queue-3-previous-year",
    ],
)
def test_cli_blocks_before_hydration_or_configuration(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """CLI starts, including restarts of checkpointed routines, share admission.

    Args:
        monkeypatch: Scoped hydration probe.
        command: Every protected command identity.
    """
    flush_mode_state().change(FlushChange(control="on"))
    hydrate = Mock(side_effect=AssertionError("blocked command hydrated files"))
    monkeypatch.setattr(main, "hydrate_runtime_library_data", hydrate)
    result = CliRunner().invoke(main.app, [command])
    assert result.exit_code == 1 and "Flush Mode is active" in result.output
    hydrate.assert_not_called()


def test_cli_status_and_override_need_no_spotify_or_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force On/Off persists and status reads it without unrelated work.

    Args:
        monkeypatch: Scoped hydration probe.
    """
    hydrate = Mock(side_effect=AssertionError("mode command hydrated files"))
    monkeypatch.setattr(main, "hydrate_runtime_library_data", hydrate)
    runner = CliRunner()
    result = runner.invoke(main.app, ["flush-mode", "--control", "on"])
    assert result.exit_code == 0 and '"active": true' in result.output
    assert flush_mode_state().load().control == "on"
    result = runner.invoke(main.app, ["flush-mode"])
    assert result.exit_code == 0 and '"control": "on"' in result.output
    assert (
        runner.invoke(main.app, ["flush-mode", "--control", "invalid"]).exit_code == 2
    )
    hydrate.assert_not_called()


def test_http_controls_and_checks_preserve_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful live count check cannot undo a persistent manual selection.

    Args:
        monkeypatch: Scoped native client and settings.
    """
    monkeypatch.setattr("spotify_manager.bootstrap.flush_mode.Settings", _configuration)
    client = AsyncMock()
    client.get.side_effect = [{"total": 2400}, {"total": 900}]
    with _http_client(monkeypatch, cast(SpotifyClient, client)) as http:
        assert http.get("/flush-mode").json()["checked_at"] is None
        assert (
            http.put("/flush-mode/control", json={"control": "off"}).status_code == 200
        )
        response = http.post("/flush-mode/check")
        assert response.status_code == 200
        status = response.json()
        assert (
            status["control"] == "off"
            and status["automatic_active"]
            and not status["active"]
        )
        assert status["queue_tracks"] == 2400 and status["queue_2_tracks"] == 900
        assert http.put("/flush-mode/control", json={"control": "automatic"}).json()[
            "active"
        ]
        assert (
            http.put("/flush-mode/control", json={"control": "invalid"}).status_code
            == 422
        )
    assert client.get.await_count == 2


def test_new_wine_request_cannot_disable_forced_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admitted worker receives the forced policy even if the request says false.

    Args:
        monkeypatch: Scoped worker boundary and configured playlists.
    """
    flush_mode_state().change(FlushChange(control="on"))
    monkeypatch.setattr(jobs, "Settings", _configuration)
    worker = AsyncMock()
    monkeypatch.setattr(jobs, "_run_new_wine_job", worker)
    with _http_client(monkeypatch, cast(SpotifyClient, AsyncMock())) as http:
        response = http.post(
            "/commands/flush-new-wine", params={"dry_run": True, "no_discovery": False}
        )
        assert response.status_code == 202 and response.json()["no_discovery"]
        assert worker.call_args.args[-1] is True
        jobs._blast_jobs.pop(response.json()["job_id"])


def test_failed_http_check_keeps_previous_active_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed or missing counts never reset the previous automatic mode.

    Args:
        monkeypatch: Scoped count reader configuration.
    """
    mode = flush_mode_state()
    stamp = "2026-11-09T00:00:00+00:00"
    before = mode.change(
        FlushChange(counts=QueueCounts(2400, 900), started=stamp, completed=stamp)
    )
    monkeypatch.setattr("spotify_manager.bootstrap.flush_mode.Settings", _configuration)
    client = AsyncMock()
    client.get.return_value = {"total": -1}
    with _http_client(monkeypatch, cast(SpotifyClient, client)) as http:
        status = http.post("/flush-mode/check").json()
        assert status["active"] and status["checked_at"] == before.checked_at
        assert status["queue_tracks"] == 2400 and status["error"]


def test_already_running_job_finishes_after_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admission blocks new work without cancelling or rechecking accepted work.

    Args:
        monkeypatch: Scoped external worker and configured playlists.
    """
    worker = AdmittedFoundArt(Event(), Event())
    monkeypatch.setattr(jobs, "Settings", _configuration)
    monkeypatch.setattr(jobs, "_run_found_art_job", worker.run)
    with _http_client(monkeypatch, cast(SpotifyClient, AsyncMock())) as http:
        started = http.post("/commands/found-art", params={"dry_run": True})
        assert started.status_code == 202 and worker.entered.wait(3)
        assert (
            http.put("/flush-mode/control", json={"control": "on"}).status_code == 200
        )
        blocked = http.post("/commands/found-art", params={"dry_run": True})
        assert blocked.status_code == 409 and "Flush Mode" in blocked.json()["detail"]
        worker.release.set()
        _await_completion(http, started.json()["job_id"])
        jobs._blast_jobs.pop(started.json()["job_id"])


@pytest.mark.parametrize(
    "path,method",
    [
        ("/flush-mode", "GET"),
        ("/flush-mode/control", "PUT"),
        ("/flush-mode/check", "POST"),
    ],
)
def test_flush_mode_endpoints_require_deployment_auth(path: str, method: str) -> None:
    """The existing authentication middleware protects status and mutations.

    Args:
        path: Every new policy endpoint.
        method: Endpoint HTTP method.
    """
    with TestClient(PasswordMiddleware(api.app, "password")) as http:
        response = http.request(method, path, json={"control": "on"})
        assert response.status_code == 401


def test_genre_bookmark_cannot_bypass_flush_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct source/run requests are blocked even if the page was already open.

    Args:
        monkeypatch: Scoped native client.
    """
    flush_mode_state().change(FlushChange(control="on"))
    with _http_client(monkeypatch, cast(SpotifyClient, AsyncMock())) as http:
        source = http.get(
            "/genre-reveal/source", params={"slug": "genre", "name": "Genre"}
        )
        run = http.post(
            "/genre-reveal/run-next", json={"slug": "genre", "name": "Genre"}
        )
        assert source.status_code == 409 and run.status_code == 409
        assert not web._genre_reveal_run_lock.locked()


def test_invalid_stored_policy_fails_closed_without_replacing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status, controls, checks and starts cannot hide invalid policy as normal.

    Args:
        monkeypatch: Scoped settings and native observations.
    """
    source = flush_mode_state().service.namespace("flush_mode", ObjectDefinition())
    source.load()
    invalid = {"version": 1, "control": "invalid"}
    source.save(invalid)
    monkeypatch.setattr(jobs, "Settings", _configuration)
    monkeypatch.setattr("spotify_manager.bootstrap.flush_mode.Settings", _configuration)
    client = AsyncMock()
    client.get.return_value = {"total": 1}
    before = set(jobs._blast_jobs)
    with _http_client(monkeypatch, cast(SpotifyClient, client)) as http:
        assert http.get("/flush-mode").status_code == 503
        assert (
            http.put("/flush-mode/control", json={"control": "off"}).status_code == 503
        )
        assert http.post("/flush-mode/check").status_code == 503
        assert http.post("/commands/found-art").status_code == 503
        assert http.post("/commands/flush-new-wine").status_code == 503
        assert set(jobs._blast_jobs) == before
    assert source.load() == invalid
