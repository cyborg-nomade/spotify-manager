"""Verify Spotify export writes use the current endpoints without HTTP replay."""

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application.listening_export import PlaylistServiceUnavailableError
from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.domain.listening_export import ExportTarget
from spotify_manager.infrastructure.listening.playlist_gateway import (
    SpotifyPlaylistGateway,
)
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from tests.support.listening_export import OWNED


class RecordingSpotify:
    """Supply raw Spotify responses and capture the exact mutation options."""

    def __init__(self) -> None:
        """Start with no operations observed."""
        self.requests: list[SpotifyRequest] = []
        self.failure: int | None = None

    async def client(self) -> AsyncSpotify:
        """Return the production client over this local transport."""
        return AsyncSpotify(self)

    async def request(self, request: SpotifyRequest) -> SpotifyJson:
        """Capture a request and return the configured response."""
        self.requests.append(request)
        if self.failure:
            raise SpotifyException(self.failure, -1, "Synthetic Spotify response")
        if request.path == "me/playlists":
            return {
                "id": OWNED,
                "name": "Preview mix",
                "owner": {"id": "owner"},
                "public": False,
                "items": {"total": 0},
                "snapshot_id": "created",
            }
        return {"snapshot_id": "appended"}


@pytest.mark.asyncio
async def test_export_uses_current_endpoints_without_write_replay() -> None:
    """Use a private create and an ordered append with transport replay disabled."""
    wire = RecordingSpotify()
    gateway = SpotifyPlaylistGateway(wire)
    uri = "spotify:track:" + "a" * 22
    target = ExportTarget("Preview mix", "owner", None)
    destination = await gateway.create(target, "Creation marker")
    assert destination is not None and destination.identity == OWNED
    assert await gateway.append(OWNED, (uri, uri)) == "appended"
    assert wire.requests == [
        SpotifyRequest(
            "POST",
            "me/playlists",
            payload={
                "name": "Preview mix",
                "public": False,
                "description": "Creation marker",
            },
            retry_http_status=False,
        ),
        SpotifyRequest(
            "POST",
            f"playlists/{OWNED}/items",
            payload={"uris": [uri, uri]},
            retry_http_status=False,
        ),
    ]


@pytest.mark.asyncio
async def test_export_distinguishes_a_missing_receipt_from_a_rate_limit() -> None:
    """An uncertain response requires reads while a rejected rate limit can retry."""
    wire = RecordingSpotify()
    gateway = SpotifyPlaylistGateway(wire)
    uri = "spotify:track:" + "a" * 22
    wire.failure = 500
    assert await gateway.append(OWNED, (uri,)) is None
    wire.failure = 429
    with pytest.raises(PlaylistServiceUnavailableError, match="rate-limited"):
        await gateway.append(OWNED, (uri,))
