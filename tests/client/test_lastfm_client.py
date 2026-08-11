"""Tests for the documented read-only Last.fm client."""

import json
from urllib.error import HTTPError
from urllib.error import URLError
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


class RawResponse(FakeResponse):
    """Response carrying bytes that are intentionally not JSON."""

    def __init__(self, body: bytes) -> None:
        self.body = body


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


def test_similar_artists_uses_documented_endpoint_and_filters_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    def open_request(request: object, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == lastfm.LASTFM_TIMEOUT_SECONDS
        return FakeResponse(
            {
                "similarartists": {
                    "artist": [
                        {"name": "Neighbor", "match": "0.91"},
                        {"name": "", "match": 0.5},
                        {"name": "Bad match", "match": "invalid"},
                        {"name": "No match", "match": 0},
                    ]
                }
            }
        )

    monkeypatch.setattr(lastfm, "urlopen", open_request)

    artists = lastfm.LastFmClient("api-key", "listener").similar_artists(
        "Seed Artist",
        limit=25,
    )

    assert artists == (lastfm.LastFmSimilarArtist("Neighbor", 0.91),)
    query = parse_qs(urlparse(requested_urls[0]).query)
    assert query["method"] == ["artist.getSimilar"]
    assert query["artist"] == ["Seed Artist"]
    assert query["limit"] == ["25"]


def test_similar_artists_validates_response_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse({"similarartists": {}}),
    )

    with pytest.raises(lastfm.LastFmResponseError, match="invalid artist data"):
        lastfm.LastFmClient("key", "listener").similar_artists("Artist")


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


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"api_key": " ", "username": "listener"}, "API key"),
        ({"api_key": "key", "username": " "}, "username"),
        (
            {"api_key": "key", "username": "listener", "max_retries": -1},
            "max_retries",
        ),
        (
            {
                "api_key": "key",
                "username": "listener",
                "backoff_seconds": -1,
            },
            "backoff_seconds",
        ),
    ],
)
def test_client_rejects_invalid_configuration(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        lastfm.LastFmClient(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", [404, 502])
def test_http_error_without_available_retry_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def fail(_request: object, timeout: int) -> FakeResponse:
        raise HTTPError("lastfm", status, "failed", {}, None)

    monkeypatch.setattr(lastfm, "urlopen", fail)

    with pytest.raises(lastfm.LastFmResponseError, match=f"HTTP {status}"):
        lastfm.LastFmClient(
            "key",
            "listener",
            max_retries=0,
        ).similar_tracks("Artist", "Track")


def test_connection_error_retries_then_reports_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    def fail(_request: object, timeout: int) -> FakeResponse:
        raise URLError("offline")

    monkeypatch.setattr(lastfm, "urlopen", fail)
    client = lastfm.LastFmClient(
        "key",
        "listener",
        max_retries=1,
        backoff_seconds=0.5,
        sleeper=delays.append,
    )

    with pytest.raises(lastfm.LastFmResponseError, match="could not connect"):
        client.similar_tracks("Artist", "Track")

    assert delays == [0.5]


@pytest.mark.parametrize(
    "response",
    [RawResponse(b"not-json"), RawResponse(b"\xff")],
)
def test_invalid_json_response_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    response: RawResponse,
) -> None:
    monkeypatch.setattr(lastfm, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(lastfm.LastFmResponseError, match="invalid JSON"):
        lastfm.LastFmClient("key", "listener").similar_tracks("Artist", "Track")


def test_non_object_response_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(["unexpected"]),
    )

    with pytest.raises(lastfm.LastFmResponseError, match="invalid object"):
        lastfm.LastFmClient("key", "listener").similar_tracks("Artist", "Track")


def test_transient_lastfm_error_retries_and_emits_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            FakeResponse({"error": "11", "message": "offline"}),
            FakeResponse({"similartracks": {"track": []}}),
        ]
    )
    messages: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(lastfm, "urlopen", lambda *_args, **_kwargs: next(responses))

    tracks = lastfm.LastFmClient(
        " key ",
        " listener ",
        event_callback=messages.append,
        sleeper=delays.append,
    ).similar_tracks("Artist", "Track")

    assert tracks == ()
    assert messages == ["Last.fm error 11; retrying in 2 seconds."]
    assert delays == [2.0]


@pytest.mark.parametrize("error", ["fatal", None])
def test_lastfm_api_error_is_reported_with_normalized_code(
    monkeypatch: pytest.MonkeyPatch,
    error: object,
) -> None:
    payload = {"error": error, "message": "bad request"}
    if error is None:
        payload = {"error": [], "message": "bad request"}
    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )

    with pytest.raises(lastfm.LastFmResponseError, match=r"failed \(-1\)"):
        lastfm.LastFmClient("key", "listener").similar_tracks("Artist", "Track")


def test_similar_tracks_validates_container_and_filters_bad_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {
                "similartracks": {
                    "track": [
                        "bad",
                        {"name": "Track", "artist": "bad", "match": 1},
                        {"name": "", "artist": {"name": "Artist"}, "match": 1},
                        {
                            "name": "Track",
                            "artist": {"name": "Artist"},
                            "match": "bad",
                        },
                        {
                            "name": "Track",
                            "artist": {"name": "Artist"},
                            "match": 0,
                        },
                        {
                            "name": "Good",
                            "artist": {"name": "Artist"},
                            "match": 0.5,
                        },
                    ]
                }
            }
        ),
    )

    assert lastfm.LastFmClient("key", "listener").similar_tracks("Artist", "Track") == (
        lastfm.LastFmSimilarTrack("Artist", "Good", 0.5),
    )

    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse({"similartracks": {}}),
    )
    with pytest.raises(lastfm.LastFmResponseError, match="invalid track data"):
        lastfm.LastFmClient("key", "listener").similar_tracks("Artist", "Track")


def test_recent_tracks_validates_range_container_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = lastfm.LastFmClient("key", "listener")
    assert client.recent_tracks(from_timestamp=2, to_timestamp=1) == ()

    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse({"recenttracks": {"track": []}}),
    )
    with pytest.raises(lastfm.LastFmResponseError, match="invalid track data"):
        client.recent_tracks(from_timestamp=1, to_timestamp=2)

    monkeypatch.setattr(
        lastfm,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {"recenttracks": {"track": [], "@attr": {"totalPages": "bad"}}}
        ),
    )
    with pytest.raises(lastfm.LastFmResponseError, match="invalid pagination"):
        client.recent_tracks(from_timestamp=1, to_timestamp=2)


@pytest.mark.parametrize(
    "raw_track",
    [
        "bad",
        {},
        {"date": {}, "artist": "bad"},
        {"date": {"uts": []}, "artist": {}},
        {"date": {"uts": "bad"}, "artist": {}},
        {"date": {"uts": "1"}, "artist": {"#text": ""}, "name": "Track"},
        {"date": {"uts": "1"}, "artist": {"#text": "Artist"}, "name": ""},
    ],
)
def test_parse_recent_track_ignores_malformed_items(raw_track: object) -> None:
    assert lastfm._parse_recent_track(raw_track) is None


def test_parse_recent_track_accepts_artist_name_and_missing_album() -> None:
    assert lastfm._parse_recent_track(
        {
            "date": {"uts": 123},
            "artist": {"name": "Artist"},
            "album": "not-an-object",
            "name": "Track",
        }
    ) == lastfm.LastFmRecentTrack("Artist", "Track", "", 123)
