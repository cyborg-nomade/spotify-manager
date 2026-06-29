"""Tests for the FastAPI interface.

Both the Spotify client and the library are overridden so no network,
credentials, or YourLibrary.json file are needed.
"""

import pytest
from fastapi.testclient import TestClient

from spotify_manager.api import app
from spotify_manager.api import get_client
from spotify_manager.api import get_library
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


def _library() -> YourLibraryFile:
    return YourLibraryFile(
        tracks=[
            YourLibraryTrack(
                artist="Radiohead",
                album="OK Computer",
                track="Airbag",
                uri="spotify:track:t1",
            ),
            YourLibraryTrack(
                artist="Radiohead",
                album="OK Computer",
                track="Karma Police",
                uri="spotify:track:t2",
            ),
        ],
        albums=[
            YourLibraryAlbum(
                artist="Radiohead", album="OK Computer", uri="spotify:album:alb1"
            )
        ],
        artists=[YourLibraryArtist(name="Radiohead", uri="spotify:artist:art1")],
    )


class FakeSpotify:
    """Minimal spotipy stand-in: only album_tracks is exercised."""

    def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": [
                {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
                {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
                {"id": "t3", "name": "Let Down", "uri": "spotify:track:t3"},
            ],
            "next": None,
        }


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_library] = _library
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_artist_stats_endpoint(client: TestClient) -> None:
    resp = client.get("/artists/stats", params={"name": "radiohead"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["artist_id"] == "art1"
    assert body["liked_tracks"] == 2
    assert body["saved_releases"] == 1
    assert body["source"] == "files"


def test_artist_stats_requires_an_argument(client: TestClient) -> None:
    assert client.get("/artists/stats").status_code == 400


def test_album_evaluation_endpoint(client: TestClient) -> None:
    resp = client.get("/albums/evaluation", params={"name": "OK Computer"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["album_id"] == "alb1"
    assert body["decision"] == "keep"  # 2/3 liked
    assert body["total_tracks"] == 3
    assert body["liked_tracks"] == 2


def test_album_evaluation_not_found(client: TestClient) -> None:
    resp = client.get("/albums/evaluation", params={"name": "Nope"})
    assert resp.status_code == 404


def test_count_artists_endpoint(client: TestClient, monkeypatch) -> None:
    from spotify_manager import api

    monkeypatch.setattr(api, "count_artists_in_library", lambda: 42)
    resp = client.get("/commands/count-artists")
    assert resp.json() == {"count": 42}
