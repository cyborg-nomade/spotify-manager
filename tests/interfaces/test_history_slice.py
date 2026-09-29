"""Public history commands exercise the real refresh and local persistence."""

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.routines import scrobble_history
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_discovery_slice import discovery_http as discovery_http
from tests.routines.test_new_kids import FakeSpotify
from tests.routines.test_scrobble_history import FakeLastFm


def _lastfm(monkeypatch: pytest.MonkeyPatch) -> FakeLastFm:
    client = FakeLastFm((LastFmRecentTrack("New Artist", "New Play", "New Album", 2),))
    monkeypatch.setattr(api, "LastFmClient", Mock(return_value=client))
    monkeypatch.setattr(main, "LastFmClient", Mock(return_value=client))
    return client


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("rebuild", [False, True])
def test_http_history_job_reaches_real_refresh(
    discovery_http: tuple[TestClient, FakeSpotify],
    monkeypatch: pytest.MonkeyPatch,
    preview: bool,
    rebuild: bool,
) -> None:
    """Real HTTP workers preserve summaries and preview/rebuild persistence.

    Args:
        discovery_http: Isolated files, configuration and real worker lifecycle.
        monkeypatch: Scoped Last.fm substitution.
        preview: Suppress file mutation.
        rebuild: Replace all historical plays.
    """
    http, _spotify = discovery_http
    lastfm = _lastfm(monkeypatch)
    path = scrobble_history.DEFAULT_SCROBBLES_PATH
    original = path.read_bytes()
    response = http.post(
        "/commands/update-scrobble-history",
        params={"dry_run": preview, "full_rebuild": rebuild},
    )
    assert response.status_code == 202, response.text
    result = _wait(
        http, "update-scrobble-history", str(response.json()["job_id"]), "completed"
    )
    assert result["history_export_scrobbles"] == 1
    assert result["live_scrobbles_added"] == 1
    assert result["history_scrobbles"] == (1 if rebuild else 2)
    assert result["history_persisted"] is not preview
    assert lastfm.calls[0][0] == (0 if rebuild else 1)
    if preview:
        assert path.read_bytes() == original
        return
    payload = json.loads(path.read_text())
    assert len(payload["scrobbles"]) == (1 if rebuild else 2)
    assert ("full_rebuilt_at" in payload) is rebuild
    assert result["history_backup_path"]


@pytest.mark.parametrize("rebuild", [False, True])
def test_cli_history_preview_reaches_real_refresh(
    discovery_http: tuple[TestClient, FakeSpotify],
    monkeypatch: pytest.MonkeyPatch,
    rebuild: bool,
) -> None:
    """CLI previews execute selection and render the original summary.

    Args:
        discovery_http: Isolated files and CLI configuration.
        monkeypatch: Scoped Last.fm substitution.
        rebuild: Request complete replacement preview.
    """
    lastfm = _lastfm(monkeypatch)
    path = scrobble_history.DEFAULT_SCROBBLES_PATH
    original = path.read_bytes()
    arguments = ["update-scrobble-history", "--dry-run"]
    if rebuild:
        arguments.append("--full-rebuild")
    result = CliRunner().invoke(main.app, arguments)
    assert result.exit_code == 0, result.output
    assert "scrobbles" in result.output.lower()
    assert lastfm.calls[0][0] == (0 if rebuild else 1)
    assert path.read_bytes() == original
