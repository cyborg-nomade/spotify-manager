"""Tests for deployment-only web pages and Genre Reveal state."""

from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from spotipy.exceptions import SpotifyException

from spotify_manager import api
from spotify_manager import web
from spotify_manager._auth import OPEN_PATHS
from spotify_manager.routines import genre_reveal


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setattr(
        web,
        "GENRE_REVEAL_STATE_PATH",
        tmp_path / "genre_reveal_state.json",
    )
    monkeypatch.setattr(
        web,
        "GENRE_REVEAL_LOG_PATH",
        tmp_path / "genre_reveal_log.jsonl",
    )
    web.app.dependency_overrides[api.get_client] = lambda: object()
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.pop(api.get_client, None)


def test_genre_reveal_shell_is_open_but_state_api_is_protected() -> None:
    assert "/genre-reveal" in OPEN_PATHS
    assert "/genre-reveal/" in OPEN_PATHS
    assert "/genre-reveal/state" not in OPEN_PATHS


def test_genre_reveal_page_preserves_route_and_server_sync(client: TestClient) -> None:
    response = client.get("/genre-reveal")

    assert response.status_code == 200
    assert "Every Noise — nearest-neighbour route" in response.text
    assert "through 6,132 genres" in response.text
    assert 'const STATE_URL = "/genre-reveal/state"' in response.text
    assert 'const RUN_URL = "/genre-reveal/run-next"' in response.text
    assert 'id="runNext"' in response.text
    assert "everynoise-nearest-neighbour-completed-v1" in response.text
    assert "everynoise-nearest-neighbour-completed-updated-v1" in response.text
    assert "everynoise-nearest-neighbour-completed-backups-v1" in response.text
    assert "cachedUpdatedAt > serverUpdatedAt" in response.text


def test_genre_reveal_state_api_round_trip(client: TestClient) -> None:
    empty = client.get("/genre-reveal/state")
    saved = client.put(
        "/genre-reveal/state",
        json={
            "completed": ["ambient", "jazz", "ambient"],
            "hide_done": True,
        },
    )
    loaded = client.get("/genre-reveal/state")

    assert empty.status_code == 200
    assert empty.json()["completed"] == []
    assert empty.json()["updated_at"] is None
    assert saved.status_code == 200
    assert saved.json()["completed"] == ["ambient", "jazz"]
    assert saved.json()["hide_done"] is True
    assert saved.json()["updated_at"] is not None
    assert loaded.json() == saved.json()


def test_genre_reveal_source_preview(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = genre_reveal.GenreRevealSourcePreview(
        slug="kerkkoor",
        name="kerkkoor",
        every_noise_url="https://everynoise.com/engenremap-kerkkoor.html",
        source_playlist_id="source",
        source_playlist_uri="spotify:playlist:source",
        source_playlist_url="https://open.spotify.com/playlist/source",
    )
    monkeypatch.setattr(
        web.genre_reveal,
        "discover_genre_source",
        lambda slug, name: preview,
    )

    response = client.get(
        "/genre-reveal/source",
        params={"slug": "kerkkoor", "name": "kerkkoor"},
    )

    assert response.status_code == 200
    assert response.json()["source_playlist_id"] == "source"


def test_genre_reveal_run_marks_state_only_after_spotify_succeeds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )
    monkeypatch.setattr(
        web.genre_reveal,
        "process_next_genre",
        lambda client, slug, name, destination_playlist_id, log_path: (
            genre_reveal.GenreRevealRunResult(
                slug=slug,
                name=name,
                every_noise_url=("https://everynoise.com/engenremap-kerkkoor.html"),
                source_playlist_id="source",
                source_playlist_uri="spotify:playlist:source",
                source_playlist_url="https://open.spotify.com/playlist/source",
                destination_playlist_id=destination_playlist_id,
                source_track_uris=["spotify:track:0000000000000000000000"],
                added_track_uris=["spotify:track:0000000000000000000000"],
                already_present_track_uris=[],
                completed_at=datetime.now(UTC),
            )
        ),
    )

    response = client.post(
        "/genre-reveal/run-next",
        json={"slug": "kerkkoor", "name": "kerkkoor"},
    )
    state = client.get("/genre-reveal/state")

    assert response.status_code == 200
    assert response.json()["added_track_uris"] == [
        "spotify:track:0000000000000000000000"
    ]
    assert state.json()["completed"] == ["kerkkoor"]


def test_genre_reveal_failure_leaves_state_incomplete(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise genre_reveal.GenreRevealSourceError("Spotify embed unavailable")

    monkeypatch.setattr(web.genre_reveal, "process_next_genre", fail)

    response = client.post(
        "/genre-reveal/run-next",
        json={"slug": "kerkkoor", "name": "kerkkoor"},
    )
    state = client.get("/genre-reveal/state")

    assert response.status_code == 502
    assert state.json()["completed"] == []


def test_genre_reveal_rate_limit_returns_promptly_and_releases_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )

    def rate_limit(*args: object, **kwargs: object) -> None:
        raise SpotifyException(
            429,
            -1,
            "rate limited",
            headers={"Retry-After": "120"},
        )

    monkeypatch.setattr(web.genre_reveal, "process_next_genre", rate_limit)

    response = client.post(
        "/genre-reveal/run-next",
        json={"slug": "kerkkoor", "name": "kerkkoor"},
    )

    assert response.status_code == 429
    assert "after trying all configured credentials" in response.json()["detail"]
    assert "in 2 minutes" in response.json()["detail"]
    assert web._genre_reveal_run_lock.locked() is False


def test_main_page_places_genre_reveal_after_daily_mind_radio(
    client: TestClient,
) -> None:
    response = client.get("/")

    daily_position = response.text.index('id="dailyMindRadioCard"')
    genre_position = response.text.index('id="genreRevealCard"')
    artist_position = response.text.index("<!-- Artist stats -->")

    assert daily_position < genre_position < artist_position
    assert 'data-action="openGenreReveal"' in response.text
