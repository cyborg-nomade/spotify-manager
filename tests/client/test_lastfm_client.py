"""Tests for the documented read-only Last.fm client."""

import json
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest

from spotify_manager.client import lastfm


class FakeResponse:
    """Context-managed byte response used by urllib."""

    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        """Return the encoded fixture."""
        return self.body


def test_similar_tracks_uses_documented_endpoint_and_parses_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    def open_request(request: object, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == lastfm.LASTFM_TIMEOUT_SECONDS
        return FakeResponse(
            {
                "similartracks": {
                    "track": [
                        {
                            "name": "Neighbor",
                            "match": "0.87",
                            "artist": {"name": "Other Artist"},
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr(lastfm, "urlopen", open_request)
    client = lastfm.LastFmClient("api-key", "listener")

    tracks = client.similar_tracks("Seed Artist", "Seed Track", limit=25)

    assert tracks == (lastfm.LastFmSimilarTrack("Other Artist", "Neighbor", 0.87),)
    query = parse_qs(urlparse(requested_urls[0]).query)
    assert query["method"] == ["track.getSimilar"]
    assert query["artist"] == ["Seed Artist"]
    assert query["track"] == ["Seed Track"]
    assert query["limit"] == ["25"]
    assert query["api_key"] == ["api-key"]


def test_recent_tracks_paginates_and_ignores_now_playing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages: list[int] = []

    def open_request(request: object, timeout: int) -> FakeResponse:
        assert timeout == lastfm.LASTFM_TIMEOUT_SECONDS
        query = parse_qs(urlparse(request.full_url).query)  # type: ignore[attr-defined]
        page = int(query["page"][0])
        pages.append(page)
        tracks: list[dict[str, object]] = [
            {
                "name": f"Track {page}",
                "artist": {"#text": "Artist"},
                "album": {"#text": "Album"},
                "date": {"uts": str(100 + page)},
            }
        ]
        if page == 1:
            tracks.append(
                {
                    "name": "Now playing",
                    "artist": {"#text": "Artist"},
                    "@attr": {"nowplaying": "true"},
                }
            )
        return FakeResponse(
            {
                "recenttracks": {
                    "track": tracks,
                    "@attr": {"totalPages": "2"},
                }
            }
        )

    monkeypatch.setattr(lastfm, "urlopen", open_request)
    client = lastfm.LastFmClient("api-key", "listener")

    tracks = client.recent_tracks(from_timestamp=50, to_timestamp=200)

    assert pages == [1, 2]
    assert [track.track for track in tracks] == ["Track 1", "Track 2"]


def test_transient_http_error_retries_with_exponential_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    delays: list[float] = []

    def open_request(_request: object, timeout: int) -> FakeResponse:
        nonlocal calls
        assert timeout == lastfm.LASTFM_TIMEOUT_SECONDS
        calls += 1
        if calls == 1:
            raise HTTPError("lastfm", 502, "bad gateway", {}, None)
        return FakeResponse({"similartracks": {"track": []}})

    monkeypatch.setattr(lastfm, "urlopen", open_request)
    client = lastfm.LastFmClient(
        "api-key",
        "listener",
        sleeper=delays.append,
    )

    assert client.similar_tracks("Artist", "Track") == ()
    assert calls == 2
    assert delays == [2.0]
