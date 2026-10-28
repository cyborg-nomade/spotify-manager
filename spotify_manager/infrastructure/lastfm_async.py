"""Await the retained Last.fm SDK through the invocation's bounded workers."""

import asyncio
from dataclasses import dataclass

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.client.lastfm import LastFmSimilarArtist
from spotify_manager.client.lastfm import LastFmSimilarTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class AsyncLastFmClient:
    """Keep the original SDK's payload parsing, paging, waits and event boundaries.

    Args:
        client: Original invocation-owned synchronous Last.fm SDK.
    """

    client: LastFmClient

    async def similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Await the SDK's original observations without blocking the event loop.

        Args:
            artist: Original SDK artist parameter.
            track: Original SDK track parameter.
            limit: Original SDK limit parameter.

        Returns:
            Original ordered SDK observations.

        Raises:
            LastFmError: Original SDK request or response failure.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self.client.similar_tracks, artist, track, limit=limit
                )
            )
            return await finish_blocking(task)

    async def similar_artists(
        self, artist: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Await the SDK's original observations without blocking the event loop.

        Args:
            artist: Original SDK artist parameter.
            limit: Original SDK limit parameter.

        Returns:
            Original ordered SDK observations.

        Raises:
            LastFmError: Original SDK request or response failure.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.client.similar_artists, artist, limit=limit)
            )
            return await finish_blocking(task)

    async def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Await the SDK's original observations without blocking the event loop.

        Args:
            from_timestamp: Original SDK from timestamp parameter.
            to_timestamp: Original SDK to timestamp parameter.
            limit: Original SDK limit parameter.

        Returns:
            Original ordered SDK observations.

        Raises:
            LastFmError: Original SDK request or response failure.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self.client.recent_tracks,
                    from_timestamp=from_timestamp,
                    to_timestamp=to_timestamp,
                    limit=limit,
                )
            )
            return await finish_blocking(task)

    @property
    def username(self) -> str:
        """Read the SDK's configured account name.

        Returns:
            Original case-preserving Last.fm username.
        """
        return self.client.username
