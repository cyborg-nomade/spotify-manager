"""Freeze caller-owned SDK override, argument and process-control compatibility."""

import asyncio
import json
import warnings
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from spotipy import Spotify

from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.infrastructure.library_analysis_catalog import SpotifyOffsetPages
from spotify_manager.infrastructure.spotify_compat import legacy_spotify
from tests.spotify_async.cases import CASES
from tests.spotify_async.cases import EndpointCase
from tests.spotify_async.memory import ResponseSpec
from tests.spotify_async.memory import SynchronousRecorder


def _recorded_cases() -> list[tuple[EndpointCase, dict[str, object]]]:
    path = Path(__file__).parents[1] / "spotify_async/fixtures/requests.json"
    recording = json.loads(path.read_text())
    return list(zip(CASES, recording["requests"], strict=True))


@pytest.mark.parametrize("case,expected", _recorded_cases())
async def test_sync_sdk_requests_still_match_frozen_prepared_contracts(
    case: EndpointCase, expected: dict[str, object]
) -> None:
    """Keep the original SDK's paths, encoded values, bodies and caller session.

    Args:
        case: Original SDK invocation, including omitted and explicit arguments.
        expected: Immutable original prepared HTTP request.
    """
    session = SynchronousRecorder()
    source = Spotify(auth="primary-token", requests_session=session)
    adapter = legacy_spotify(source)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = await getattr(adapter, case.name)(*case.args, **case.keywords)
        assert result == {"contract": True}
        request = session.observed
        assert request is not None
        assert request.url is not None
        assert request.method == expected["method"]
        assert request.url == expected["url"]
        assert (request.body or None) == expected["body"]
        assert request.headers["Content-Type"] == expected["content_type"]
    finally:
        session.close()


def _one_album(identifier: str) -> dict[str, str]:
    return {"requested": identifier}


async def test_overridden_sdk_method_receives_only_the_original_arguments() -> None:
    """Retain a narrow override that does not accept added SDK default keywords."""
    source = Mock(spec=Spotify)
    source.album = Mock(side_effect=_one_album)
    assert await legacy_spotify(source).album("album") == {"requested": "album"}
    source.album.assert_called_once_with("album")


async def test_existing_async_python_resource_is_awaited_on_the_callers_loop() -> None:
    """Keep the compatible async resource's body out of the blocking worker loop."""
    source = Mock(spec=Spotify)
    source.album = AsyncMock(return_value={"available": True})
    assert await legacy_spotify(source).album("album") == {"available": True}
    source.album.assert_awaited_once_with("album")


@pytest.mark.parametrize("error", [KeyboardInterrupt("stop"), SystemExit(7)])
async def test_original_control_exception_returns_without_terminating_the_loop(
    error: KeyboardInterrupt | SystemExit,
) -> None:
    """Deliver the exact original operator control object after worker completion.

    Args:
        error: Original synchronous SDK or operator control exception.
    """
    source = Mock(spec=Spotify)
    source.album = Mock(side_effect=error)
    with pytest.raises(type(error)) as observed:
        await legacy_spotify(source).album("album")
    assert observed.value is error
    await asyncio.sleep(0)


async def test_original_ordinary_sdk_failure_is_not_translated() -> None:
    """Keep the error object and its cause for the existing application handler."""
    error = ValueError("original SDK failure")
    source = Mock(spec=Spotify)
    source.album = Mock(side_effect=error)
    with pytest.raises(ValueError) as observed:
        await legacy_spotify(source).album("album")
    assert observed.value is error and observed.value.__cause__ is None


@pytest.mark.parametrize("resource", ["albums", "tracks"])
async def test_scan_retains_the_original_sdk_method_after_an_override_changes(
    resource: ResourceName,
) -> None:
    """Bind once per scan and observe a newer override only in the following scan.

    Args:
        resource: Original saved-library endpoint selector.
    """
    source = Mock(spec=Spotify)
    original = Mock(return_value={"items": ["original"]})
    replacement = Mock(return_value={"items": ["replacement"]})
    name = "current_user_saved_" + resource
    setattr(source, name, original)
    client = legacy_spotify(source)
    first = SpotifyOffsetPages(client, resource, True)
    setattr(source, name, replacement)
    assert await first.read(limit=50, offset=3) == {"items": ["original"]}
    original.assert_called_once_with(limit=50, offset=3)
    replacement.assert_not_called()
    second = SpotifyOffsetPages(client, resource, False)
    assert await second.read(limit=20, offset=4) == {"items": ["replacement"]}
    replacement.assert_called_once_with(limit=20, offset=4)


@pytest.mark.parametrize("name", ["_get", "_post", "_put", "_delete"])
async def test_raw_sdk_calls_keep_query_precedence_and_payload(name: str) -> None:
    """Retain the SDK's argument overrides, original body and raw call hooks.

    Args:
        name: Original raw SDK HTTP method.
    """
    session = SynchronousRecorder()
    source = Spotify(auth="primary-token", requests_session=session)
    adapter = legacy_spotify(source)
    try:
        result = await getattr(adapter, name)(
            "me/library",
            args={"limit": 7, "market": "DE"},
            payload={"uris": ["uri"]},
            limit=50,
        )
        assert result == {"contract": True}
        request = session.observed
        assert request is not None
        assert request.url is not None and request.url.endswith("?limit=7&market=DE")
        assert request.body == '{"uris": ["uri"]}'
    finally:
        session.close()


@pytest.mark.parametrize("name", ["get", "post", "put", "delete"])
async def test_generic_sdk_aliases_preserve_raw_http_contracts(name: str) -> None:
    """Forward the async port's raw aliases through the caller-owned SDK.

    Args:
        name: Generic async HTTP alias.
    """
    session = SynchronousRecorder()
    adapter = legacy_spotify(Spotify(auth="primary-token", requests_session=session))
    try:
        options: dict[str, object] = {"query": {"limit": 7}}
        if name != "get":
            options["payload"] = {"uris": ["uri"]}
        await getattr(adapter, name)("me/library", **options)
        request = session.observed
        assert request is not None and request.method == name.upper()
        assert request.url is not None
        assert request.url.endswith("?limit=7")
        assert request.body == (None if name == "get" else '{"uris": ["uri"]}')
    finally:
        session.close()


async def test_token_maintenance_does_not_replace_or_close_the_callers_sdk() -> None:
    """Keep explicit credential maintenance with the original SDK owner."""
    source = Mock(spec=Spotify)
    source.rotate_credentials = Mock(return_value="app5")
    source.refresh_all_app_tokens = Mock(return_value=("primary", "app5"))
    adapter = legacy_spotify(source)
    assert await adapter.rotate_credentials() == "app5"
    assert await adapter.refresh_all_app_tokens() == ("primary", "app5")
    source.rotate_credentials.assert_called_once_with()
    source.refresh_all_app_tokens.assert_called_once_with()


@pytest.mark.parametrize("name", ["_get", "_post", "_put", "_delete"])
@pytest.mark.parametrize("payload", [None, {}, {"uris": ["uri"]}])
async def test_native_raw_aliases_match_the_original_sdk_including_get_bodies(
    name: str, payload: object
) -> None:
    """Keep raw query overrides and original falsey and nonempty payload behavior.

    Args:
        name: Original raw SDK HTTP operation.
        payload: Original absent, empty or populated JSON body.
    """
    from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
    from tests.spotify_async.memory import transport_memory
    from tests.spotify_async.test_endpoints import _assert_requests

    session = SynchronousRecorder()
    memory = transport_memory([ResponseSpec(payload={"contract": True})])
    source = Spotify(auth="primary-token", requests_session=session)
    native = AsyncSpotify(memory.transport)
    options = {"args": {"limit": 7, "market": "DE"}, "payload": payload, "limit": 50}
    try:
        assert getattr(source, name)("me/library", **options) == {"contract": True}
        assert await getattr(native, name)("me/library", **options) == {
            "contract": True
        }
        _assert_requests(session, memory.http.requests[-1])
    finally:
        session.close()
        await memory.transport.aclose()
