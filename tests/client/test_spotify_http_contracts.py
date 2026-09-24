"""Real Spotipy decoding and request shape, separate from mutable domain fakes."""

import json
from unittest.mock import Mock

import pytest
import requests
from spotipy.exceptions import SpotifyException

from spotify_manager import client as client_module
from spotify_manager.processors import library_lookups
from tests.support.effects import Responses


@pytest.fixture
def transport(monkeypatch):
    oauth = Mock()
    oauth.get_access_token.return_value = "fixture-token"
    spotify = client_module.RotatingSpotify(("primary",), (oauth,), retries=3)
    sleeps = []
    monkeypatch.setattr(client_module, "sleep", sleeps.append)

    def install(*outcomes):
        responses = Responses(*outcomes)
        monkeypatch.setattr(spotify._session, "request", responses)
        return responses

    yield spotify, install, sleeps
    spotify._session.close()


def response(status, payload=None, *, raw=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result.url = "https://api.spotify.com/v1/fixture"
    result.headers.update(headers or {})
    result._content = json.dumps(payload).encode() if raw is None else raw
    return result


def test_album_pagination_uses_next_url_and_preserves_track_order(transport):
    spotify, install, _ = transport
    next_url = "https://api.spotify.com/v1/albums/album/tracks?offset=2&limit=50"
    tracks = [
        {"id": key, "name": key, "uri": f"spotify:track:{key}"}
        for key in ("a", "b", "c")
    ]
    calls = install(
        response(200, {"items": tracks[:2], "next": next_url}),
        response(200, {"items": tracks[2:], "next": None}),
    )
    assert library_lookups._fetch_album_tracks(spotify, "album") == tracks
    assert calls.calls[0][0] == (
        "GET",
        "https://api.spotify.com/v1/albums/album/tracks/",
    )
    assert calls.calls[0][1]["params"] == {"limit": 50, "offset": 0, "market": None}
    assert calls.calls[1][0] == ("GET", next_url)
    assert calls.calls[1][1]["params"] == {}
    assert not calls.remaining


@pytest.mark.parametrize(
    "page",
    [
        None,
        {},
        {"items": None},
        {"items": [], "next": "next"},
        {"items": [{"id": "incomplete"}], "next": None},
    ],
)
def test_malformed_track_pages_do_not_become_silent_empty_albums(transport, page):
    spotify, install, _ = transport
    calls = install(response(200, page))
    with pytest.raises(library_lookups.SpotifyLookupResponseError):
        library_lookups._fetch_album_tracks(spotify, "album")
    assert len(calls.calls) == 1


@pytest.mark.parametrize("status", [401, 404, 429, 500, 503])
def test_http_error_mapping_preserves_status_reason_and_retry_after(transport, status):
    spotify, install, sleeps = transport
    calls = install(
        response(
            status,
            {"error": {"message": "fixture error", "reason": "fixture reason"}},
            headers={"Retry-After": "17"},
        )
    )
    with pytest.raises(SpotifyException) as failure:
        spotify._get("fixture")
    assert failure.value.http_status == status
    assert failure.value.reason == "fixture reason"
    assert failure.value.headers["Retry-After"] == "17"
    assert "fixture error" in str(failure.value)
    assert len(calls.calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("raw", [b"", b"not-json"])
def test_success_with_non_json_body_retains_legacy_none(transport, raw):
    spotify, install, _ = transport
    install(response(204, raw=raw))
    assert spotify._delete("playlists/list/items", payload={"items": []}) is None


def test_playlist_writes_keep_canonical_endpoint_and_payload(transport):
    spotify, install, _ = transport
    calls = install(
        response(201, {"snapshot_id": "one"}), response(200, {"snapshot_id": "two"})
    )
    uri = "spotify:track:track"
    spotify._post("playlists/list/items", payload={"uris": [uri]})
    spotify._delete("playlists/list/items", payload={"items": [{"uri": uri}]})
    assert [args[0] for args, _ in calls.calls] == ["POST", "DELETE"]
    assert [args[1] for args, _ in calls.calls] == [
        "https://api.spotify.com/v1/playlists/list/items"
    ] * 2
    assert [json.loads(kwargs["data"]) for _, kwargs in calls.calls] == [
        {"uris": [uri]},
        {"items": [{"uri": uri}]},
    ]
    assert all(
        kwargs["headers"]["Authorization"] == "Bearer fixture-token"
        for _, kwargs in calls.calls
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_ambiguous_write_timeouts_are_not_retried(transport, method):
    spotify, install, sleeps = transport
    calls = install(requests.Timeout("accepted but acknowledgement lost"))
    with pytest.raises(requests.Timeout):
        spotify._internal_call(method, "fixture", {"uris": ["spotify:track:a"]}, {})
    assert len(calls.calls) == 1
    assert sleeps == []


def test_get_timeout_budget_uses_fake_sleep_and_stops_after_four_attempts(transport):
    spotify, install, sleeps = transport
    calls = install(*(requests.Timeout("no response") for _ in range(4)))
    with pytest.raises(requests.Timeout):
        spotify._get("fixture")
    assert len(calls.calls) == 4
    assert sleeps == [10, 20, 40]
