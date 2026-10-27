"""Cover credential, notification and error boundaries without changing policies."""

import asyncio
import warnings

import httpx
import pytest
import requests.exceptions as request_errors

from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.client.events import SpotifyOutput
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.infrastructure.spotify_async.credentials import Credentials
from spotify_manager.infrastructure.spotify_async.retries import transport_error
from tests.spotify_async.memory import OutputMemory
from tests.spotify_async.memory import TokenMemory
from tests.spotify_async.memory import transport_memory


class BrokenOutput:
    """Expose the existing best-effort notification failure boundary."""

    def echo(self, message: str) -> None:
        """Simulate an unavailable display sink.

        Args:
            message: Original safe diagnostic.

        Raises:
            RuntimeError: Display is unavailable.
        """
        raise RuntimeError("display unavailable")


def test_event_output_preserves_best_effort_display_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep logging intact when no observer exists or its display fails.

    Args:
        caplog: Captured safe diagnostics.
    """
    SpotifyOutput(None).echo("no observer")
    SpotifyOutput(BrokenOutput()).echo("broken observer")
    assert "Spotify event callback failed" in caplog.text
    assert "no observer" in caplog.text


def test_credentials_require_at_least_one_source() -> None:
    """Reject an unusable empty credential pool."""
    with pytest.raises(ValueError, match="At least one"):
        Credentials((), OutputMemory())


def test_concurrent_rate_limits_share_the_newly_activated_credential() -> None:
    """Force-refresh once when two requests observe the same older credential."""
    asyncio.run(_shared_rotation())


async def _shared_rotation() -> None:
    memory = transport_memory(tokens=(TokenMemory(), TokenMemory("app5")))
    credentials = memory.transport.credentials
    previous = 0
    try:
        results = await asyncio.gather(
            credentials.rotate(previous, {0}), credentials.rotate(previous, {0})
        )
        assert list(results) == [True, True]
        assert memory.tokens[1].calls == [True]
        assert credentials.active == 1
    finally:
        await memory.transport.aclose()


def test_empty_next_page_and_album_type_preserve_sdk_rules() -> None:
    """Do not fetch an absent next page; retain deprecated group precedence."""
    asyncio.run(_deprecated_and_next())


async def _deprecated_and_next() -> None:
    memory = transport_memory()
    client = AsyncSpotify(memory.transport)
    try:
        assert await client.next({"next": None}) is None
        assert memory.http.requests == []
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            await client.artist_albums(
                "abc", album_type="single", include_groups="album"
            )
        assert len(seen) == 1
        assert memory.http.requests[0].url.params["include_groups"] == "album"
    finally:
        await memory.transport.aclose()


def test_language_header_is_retained() -> None:
    """Keep explicit Accept-Language separate from market parameters."""
    asyncio.run(_language())


async def _language() -> None:
    memory = transport_memory()
    memory.transport.language = "de"
    try:
        await memory.transport.request(SpotifyRequest("GET", "me/"))
        assert memory.http.requests[0].headers["Accept-Language"] == "de"
    finally:
        await memory.transport.aclose()


@pytest.mark.parametrize(
    "native, expected",
    [
        (httpx.ConnectTimeout("timeout"), request_errors.ConnectTimeout),
        (httpx.ReadTimeout("timeout"), request_errors.ReadTimeout),
        (httpx.WriteTimeout("timeout"), request_errors.Timeout),
        (httpx.PoolTimeout("timeout"), request_errors.Timeout),
        (httpx.ReadError("reset"), request_errors.ConnectionError),
        (httpx.WriteError("reset"), request_errors.ConnectionError),
        (httpx.RemoteProtocolError("reset"), request_errors.ConnectionError),
    ],
)
def test_native_failures_retain_requests_exception_types(
    native: httpx.TransportError, expected: type[Exception]
) -> None:
    """Preserve the exact exception names used by routine retry audit records.

    Args:
        native: Native failure at the HTTP boundary.
        expected: Compatible synchronous exception class.
    """
    actual = transport_error(native)
    assert type(actual) is expected
    assert str(actual) == str(native)
