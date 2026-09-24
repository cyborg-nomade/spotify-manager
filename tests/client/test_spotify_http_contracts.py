"""Real Spotipy decoding and request shape, separate from mutable domain fakes."""

import json
from collections.abc import Callable
from collections.abc import Iterator
from functools import partial
from unittest.mock import Mock

import pytest
import requests
from spotipy.exceptions import SpotifyException

from spotify_manager import client as client_module
from spotify_manager.processors import library_lookups
from tests.support.effects import Responses


type Transport = tuple[
    client_module.RotatingSpotify, Callable[..., Responses], list[float]
]


def _install_responses(
    patch: pytest.MonkeyPatch,
    spotify: client_module.RotatingSpotify,
    *outcomes: object,
) -> Responses:
    responses = Responses(*outcomes)
    patch.setattr(spotify._session, "request", responses)
    return responses


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[Transport]:
    """Run the real adapter with scripted HTTP responses and a fake clock.

    Args:
        monkeypatch: Per-test transport and sleep patch manager.

    Yields:
        Adapter, response-script installer, and recorded sleep durations.
    """
    oauth = Mock()
    oauth.get_access_token.return_value = "fixture-token"
    spotify = client_module.RotatingSpotify(("primary",), (oauth,), retries=3)
    sleeps: list[float] = []
    monkeypatch.setattr(client_module, "sleep", sleeps.append)

    yield spotify, partial(_install_responses, monkeypatch, spotify), sleeps
    spotify._session.close()


def _response(
    status: int,
    payload: object = None,
    *,
    raw: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = "https://api.spotify.com/v1/fixture"
    result.headers.update(headers or {})
    result._content = json.dumps(payload).encode() if raw is None else raw
    return result


def test_album_pagination_uses_next_url_and_preserves_track_order(
    transport: Transport,
) -> None:
    """Follow next-page URLs while retaining track and request order.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
    """
    spotify, install, _ = transport
    next_url = "https://api.spotify.com/v1/albums/album/tracks?offset=2&limit=50"
    tracks = _tracks(("a", "b", "c"))
    calls = install(
        _response(200, {"items": tracks[:2], "next": next_url}),
        _response(200, {"items": tracks[2:], "next": None}),
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
def test_malformed_track_pages_do_not_become_silent_empty_albums(
    transport: Transport, page: object
) -> None:
    """Reject malformed pages instead of treating them as an empty album.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
        page: Malformed or incomplete decoded HTTP payload.
    """
    spotify, install, _ = transport
    calls = install(_response(200, page))
    with pytest.raises(library_lookups.SpotifyLookupResponseError):
        library_lookups._fetch_album_tracks(spotify, "album")
    assert len(calls.calls) == 1


@pytest.mark.parametrize("status", [401, 404, 429, 500, 503])
def test_http_error_mapping_preserves_status_reason_and_retry_after(
    transport: Transport, status: int
) -> None:
    """Retain status, reason, and retry headers from a Spotify HTTP error.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
        status: HTTP error code returned by the scripted transport.
    """
    spotify, install, sleeps = transport
    calls = install(
        _response(
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
def test_success_with_non_json_body_retains_legacy_none(
    transport: Transport, raw: bytes
) -> None:
    """Preserve None for successful responses without valid JSON.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
        raw: Empty or invalid JSON response body.
    """
    spotify, install, _ = transport
    install(_response(204, raw=raw))
    assert spotify._delete("playlists/list/items", payload={"items": []}) is None


def test_playlist_writes_keep_canonical_endpoint_and_payload(
    transport: Transport,
) -> None:
    """Preserve playlist endpoints, payloads, and authentication headers.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
    """
    spotify, install, _ = transport
    calls = install(
        _response(201, {"snapshot_id": "one"}), _response(200, {"snapshot_id": "two"})
    )
    uri = "spotify:track:track"
    spotify._post("playlists/list/items", payload={"uris": [uri]})
    spotify._delete("playlists/list/items", payload={"items": [{"uri": uri}]})
    assert len(calls.calls) == 2
    _assert_request(calls.calls[0], "POST", {"uris": [uri]})
    _assert_request(calls.calls[1], "DELETE", {"items": [{"uri": uri}]})


def _assert_request(
    call: tuple[tuple[object, ...], dict[str, object]],
    method: str,
    payload: object,
) -> None:
    args, kwargs = call
    assert args == (method, "https://api.spotify.com/v1/playlists/list/items")
    data = kwargs["data"]
    headers = kwargs["headers"]
    assert isinstance(data, str)
    assert isinstance(headers, dict)
    assert json.loads(data) == payload
    assert headers["Authorization"] == "Bearer fixture-token"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_ambiguous_write_timeouts_are_not_retried(
    transport: Transport, method: str
) -> None:
    """Avoid retrying a write whose remote acceptance is unknown.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
        method: Mutating HTTP method under test.
    """
    spotify, install, sleeps = transport
    calls = install(requests.Timeout("accepted but acknowledgement lost"))
    with pytest.raises(requests.Timeout):
        spotify._internal_call(method, "fixture", {"uris": ["spotify:track:a"]}, {})
    assert len(calls.calls) == 1
    assert sleeps == []


def test_get_timeout_budget_uses_fake_sleep_and_stops_after_four_attempts(
    transport: Transport,
) -> None:
    """Stop read retries at the existing budget and backoff sequence.

    Args:
        transport: Adapter, scripted-response installer, and recorded sleeps.
    """
    spotify, install, sleeps = transport
    calls = install(*(requests.Timeout("no response") for _ in range(4)))
    with pytest.raises(requests.Timeout):
        spotify._get("fixture")
    assert len(calls.calls) == 4
    assert sleeps == [10, 20, 40]


def _tracks(identifiers: tuple[str, ...]) -> list[dict[str, str]]:
    result = []
    for identifier in identifiers:
        result.append(
            {"id": identifier, "name": identifier, "uri": f"spotify:track:{identifier}"}
        )
    return result
