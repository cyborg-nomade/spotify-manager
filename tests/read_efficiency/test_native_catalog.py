"""Exercise the native optimization through real endpoint and credential owners."""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from unittest.mock import Mock

import httpx
import pytest
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.infrastructure.spotify_compat import legacy_spotify
from spotify_manager.processors.library_lookups import _live_primary_track_ids
from tests.read_efficiency.catalog_memory import album_reply
from tests.read_efficiency.catalog_memory import release_ids
from tests.spotify_async.memory import HttpMemory
from tests.spotify_async.memory import transport_memory


@dataclass
class CatalogHttp(HttpMemory):
    """Synchronize complete native HTTP responses at their actual request boundary.

    Args:
        width: Number of distinct admitted requests in each expected window.
        status: Optional HTTP failure for the first requested batch.
    """

    width: int = 4
    status: int = 200
    active: int = field(default=0, init=False)
    peak: int = field(default=0, init=False)
    barrier: asyncio.Barrier = field(init=False)

    def __post_init__(self) -> None:
        """Build the controlled response rendezvous without a timing threshold."""
        self.barrier = asyncio.Barrier(self.width)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        """Serve only supported album GETs through HTTPX's required test hook.

        Args:
            request: Actual serialized native endpoint request.

        Returns:
            Complete synthetic catalog or original HTTP failure envelope.
        """
        assert request.method == "GET" and request.url.path == "/v1/albums/"
        self.requests.append(request)
        identifiers = request.url.params["ids"].split(",")
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await self.barrier.wait()
            return self.response(request, identifiers)
        finally:
            self.active -= 1

    def response(
        self, request: httpx.Request, identifiers: list[str]
    ) -> httpx.Response:
        """Select a response without changing request ordering or adding a replay.

        Args:
            request: Actual request retained on the response.
            identifiers: Original ordered batch values.

        Returns:
            A catalog response or a failure carrying Retry-After unchanged.
        """
        if identifiers[0] == "0" and self.status != 200:
            return httpx.Response(
                self.status,
                request=request,
                json={"error": {"status": self.status, "message": "original failure"}},
                headers={"Retry-After": "7"},
            )
        return httpx.Response(200, request=request, json=album_reply(identifiers))


@pytest.mark.parametrize("repetitions", [1, 2])
async def test_native_artist_lookup_reuses_the_owned_pool(repetitions: int) -> None:
    """Activate the measured optimization through the actual native caller path.

    Args:
        repetitions: Number of complete duplicate catalog sequences.
    """
    http = CatalogHttp()
    memory = transport_memory(http=http)
    identifiers = release_ids(80)
    try:
        result = await _live_primary_track_ids(
            AsyncSpotify(memory.transport), "artist", identifiers * repetitions
        )
        assert result == identifiers
        assert (len(http.requests), http.peak, http.active) == (4, 4, 0)
        assert not memory.transport.http.is_closed
    finally:
        await memory.transport.aclose()
    assert memory.transport.http.is_closed
    for token in memory.tokens:
        assert token.closed


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_concurrent_http_errors_keep_the_existing_retry_owner(
    status: int,
) -> None:
    """Preserve terminal status and Retry-After without adding a coordinator retry.

    Args:
        status: Original upstream HTTP failure.
    """
    http = CatalogHttp(status=status)
    memory = transport_memory(http=http, profile=RetryProfile(0, 0, (999,)))
    try:
        with pytest.raises(SpotifyException) as caught:
            await _live_primary_track_ids(
                AsyncSpotify(memory.transport), "artist", release_ids(80)
            )
        assert caught.value.http_status == status
        assert caught.value.headers["Retry-After"] == "7"
        assert len(http.requests) == 4 and http.active == 0
        assert memory.wait.delays == []
    finally:
        await memory.transport.aclose()


async def test_retained_sdk_lookup_keeps_its_original_sequential_requests() -> None:
    """Keep caller-owned SDK overrides on the frozen serial compatibility path."""
    source = Mock(spec=Spotify)
    session = Mock()
    source._session = session
    source.albums.side_effect = album_reply
    identifiers = release_ids(80)
    result = await _live_primary_track_ids(
        legacy_spotify(source), "artist", identifiers * 2
    )
    assert result == identifiers and source.albums.call_count == 8
    session.close.assert_not_called()


async def test_singleflight_native_reads_keep_the_original_batch_payload() -> None:
    """Share a pending identical read while retaining duplicate IDs on the wire."""
    http = CatalogHttp(width=1)
    memory = transport_memory(http=http)
    try:
        result = await _live_primary_track_ids(
            AsyncSpotify(memory.transport), "artist", ["same"] * 80
        )
        assert result == ["same"] and len(http.requests) == 1
        assert http.requests[0].url.params["ids"] == ",".join(["same"] * 20)
    finally:
        await memory.transport.aclose()
