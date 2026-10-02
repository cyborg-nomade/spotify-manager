"""Execute actual CLI/HTTP Genre Reveal with offline pages and SDK writes."""

import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from types import SimpleNamespace
from types import TracebackType
from typing import Literal
from typing import Self
from typing import cast
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient
from spotipy import Spotify
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager import web
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import genre_reveal


URIS = tuple("spotify:track:" + str(index).zfill(22) for index in range(12))


@dataclass
class PublicPage:
    """Supply an offline UTF-8 response through the original context-manager boundary.

    Args:
        html: Explicit public page text.
    """

    html: str

    def __enter__(self) -> Self:
        """Enter the explicit response context.

        Returns:
            This offline response.
        """
        return self

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Leave the response context without suppressing failures.

        Args:
            error_type: Optional failure class.
            error: Optional failure instance.
            traceback: Optional failure traceback.

        Returns:
            False, preserving any failure.
        """
        return False

    def read(self) -> bytes:
        """Return explicit public-page bytes.

        Returns:
            UTF-8 response body.
        """
        return self.html.encode("utf-8")


@dataclass
class OfflineGenre:
    """Record original public reads and accepted Spotify mutations.

    Args:
        fail_append: Fail after recording the accepted marker append.
    """

    fail_append: bool = False
    pages: list[str] = field(default_factory=list)
    writes: list[object] = field(default_factory=list)

    def client(self) -> Spotify:
        """Supply the caller-owned offline Spotify boundary.

        Returns:
            This explicit SDK stand-in.
        """
        return cast(Spotify, self)

    def settings(self) -> SimpleNamespace:
        """Supply only the original configured genre destination.

        Returns:
            Explicit destination configuration.
        """
        return SimpleNamespace(genre_reveal_playlist="spotify:playlist:destination")

    def page(self, request: Request, *, timeout: int) -> PublicPage:
        """Return original Every Noise and Spotify embed page fixtures.

        Args:
            request: Original user-agent-bearing public request.
            timeout: Original bounded request timeout.

        Returns:
            Explicit original public source or embed page.
        """
        assert timeout == 30
        self.pages.append(request.full_url)
        if request.full_url.startswith("https://everynoise.com/"):
            return PublicPage(
                '<a href="https://open.spotify.com/playlist/source" '
                'title="listen to The Sound of Genre on Spotify">source</a>'
            )
        assert request.full_url == "https://open.spotify.com/embed/playlist/source"
        return PublicPage(" ".join(URIS))

    def _get(self, endpoint: str, *, limit: int, offset: int) -> dict[str, object]:
        assert endpoint == "playlists/destination/items" and offset == 0
        return {"items": [{"item": {"id": URIS[1].rsplit(":", 1)[-1]}}], "total": 1}

    def _put(self, endpoint: str, *, args: object) -> None:
        self.writes.append(["PUT", endpoint, args])

    def _post(self, endpoint: str, *, payload: object) -> None:
        self.writes.append(["POST", endpoint, payload])
        if self.fail_append:
            raise genre_reveal.GenreRevealSourceError("accepted append failed")


def _bind(monkeypatch: pytest.MonkeyPatch, fake: OfflineGenre) -> None:
    monkeypatch.setattr(genre_reveal, "urlopen", fake.page)
    monkeypatch.setattr(main, "Settings", fake.settings)
    monkeypatch.setattr(main, "client", fake.client)
    monkeypatch.setattr(web, "Settings", fake.settings)
    overrides = api.app.dependency_overrides.copy()
    overrides[api.get_client] = fake.client
    monkeypatch.setattr(api.app, "dependency_overrides", overrides)


def _assert_artifacts(
    fake: OfflineGenre,
    state: Path,
    log: Path,
    failed: bool,
    service: StateService | None = None,
) -> None:
    assert len(fake.pages) == 2
    missing = [uri for uri in URIS[:10] if uri != URIS[1]]
    assert fake.writes == [
        ["PUT", "me/library", {"uris": "spotify:playlist:source"}],
        ["POST", "playlists/destination/items", {"uris": missing}],
    ]
    if failed:
        assert (
            genre_reveal.load_genre_reveal_state(state, state_service=service).completed
            == []
        )
        assert not log.exists()
        return
    assert (
        len(
            genre_reveal.load_genre_reveal_state(state, state_service=service).completed
        )
        == 1
    )
    record = json.loads(log.read_text())
    assert record["added_track_uris"] == missing
    assert record["already_present_track_uris"] == [URIS[1]]


@pytest.mark.parametrize("failed", [False, True])
def test_actual_genre_cli_preserves_completion_and_accepted_failure(
    failed: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Run source discovery, SDK writes, audit and progress through the actual CLI.

    Args:
        failed: Fail after accepted Spotify marker append.
        monkeypatch: Explicit offline boundaries.
        tmp_path: Isolated state/audit locations.
    """
    fake = OfflineGenre(failed)
    _bind(monkeypatch, fake)
    state, log = tmp_path / "state.json", tmp_path / "audit.jsonl"
    result = CliRunner().invoke(
        main.app,
        [
            "genre-reveal",
            "--no-open-pages",
            "--state-path",
            str(state),
            "--log-path",
            str(log),
        ],
    )
    assert result.exit_code == (1 if failed else 0), result.output
    assert (
        "accepted append failed" if failed else "completed kerkkoor"
    ) in result.output
    _assert_artifacts(fake, state, log, failed)


@pytest.mark.parametrize("failed", [False, True])
def test_actual_genre_http_preserves_completion_and_accepted_failure(
    failed: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Run actual HTTP translation around the complete Genre Reveal workflow.

    Args:
        failed: Fail after accepted Spotify marker append.
        monkeypatch: Explicit offline boundaries.
        tmp_path: Isolated state/audit locations.
    """
    fake = OfflineGenre(failed)
    _bind(monkeypatch, fake)
    state, log = tmp_path / "state.json", tmp_path / "audit.jsonl"
    monkeypatch.setattr(web, "GENRE_REVEAL_STATE_PATH", state)
    monkeypatch.setattr(web, "GENRE_REVEAL_LOG_PATH", log)
    response = TestClient(api.app).post(
        "/genre-reveal/run-next", json={"slug": "genre", "name": "Genre"}
    )
    assert response.status_code == (502 if failed else 200), response.text
    _assert_artifacts(fake, state, log, failed, get_state_service())
    assert not web._genre_reveal_run_lock.locked()
