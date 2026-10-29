"""Retain synchronous Python history resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.routines.sauvignon as source_sauvignon
    import spotify_manager.routines.something_old as source_something_old
    import spotify_manager.routines.the_queue as source_the_queue


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.domain.queue_candidates import LastFmSimilarArtist
from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingHistoryReader(Protocol):
    """Caller-owned synchronous HistoryReader resource."""

    def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Return all dated scrobbles in a closed UTC range.

        Args:
            from_timestamp: Inclusive lower timestamp bound in seconds.
            to_timestamp: Inclusive upper timestamp bound in seconds.
            limit: Original request page size.

        Returns:
            Ordered dated observations within the requested range.
        """
        ...


@dataclass(frozen=True)
class PythonHistoryReader:
    """Await caller-owned HistoryReader I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingHistoryReader | source_something_old.LastFmReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Return all dated scrobbles in a closed UTC range.

        Args:
            from_timestamp: Inclusive lower timestamp bound in seconds.
            to_timestamp: Inclusive upper timestamp bound in seconds.
            limit: Original request page size.

        Returns:
            Ordered dated observations within the requested range.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_recent_tracks,
                    from_timestamp=from_timestamp,
                    to_timestamp=to_timestamp,
                    limit=limit,
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...] | Awaitable[tuple[LastFmRecentTrack, ...]]:
        with LegacyControl():
            return self.source.recent_tracks(
                from_timestamp=from_timestamp, to_timestamp=to_timestamp, limit=limit
            )


class BlockingRecommendationReader(Protocol):
    """Caller-owned synchronous RecommendationReader resource."""

    def similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Read the original ordered neighborhood for one seed.

        Args:
            artist: Original seed artist spelling.
            track: Original seed title spelling.
            limit: Original maximum neighborhood size.

        Returns:
            Ordered Last.fm neighbors with original similarity scores.
        """
        ...

    def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Read dated canonical plays within the original UTC bounds.

        Args:
            from_timestamp: Original inclusive lower bound in seconds.
            to_timestamp: Original inclusive upper bound in seconds.
            limit: Original page size.

        Returns:
            Ordered Last.fm observations with original timestamps.
        """
        ...


@dataclass(frozen=True)
class PythonRecommendationReader:
    """Await caller-owned RecommendationReader I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingRecommendationReader | source_sauvignon.LastFmReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Read the original ordered neighborhood for one seed.

        Args:
            artist: Original seed artist spelling.
            track: Original seed title spelling.
            limit: Original maximum neighborhood size.

        Returns:
            Ordered Last.fm neighbors with original similarity scores.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_similar_tracks, artist, track, limit=limit
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...] | Awaitable[tuple[LastFmSimilarTrack, ...]]:
        with LegacyControl():
            return self.source.similar_tracks(artist, track, limit=limit)

    async def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Read dated canonical plays within the original UTC bounds.

        Args:
            from_timestamp: Original inclusive lower bound in seconds.
            to_timestamp: Original inclusive upper bound in seconds.
            limit: Original page size.

        Returns:
            Ordered Last.fm observations with original timestamps.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_recent_tracks,
                    from_timestamp=from_timestamp,
                    to_timestamp=to_timestamp,
                    limit=limit,
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...] | Awaitable[tuple[LastFmRecentTrack, ...]]:
        with LegacyControl():
            return self.source.recent_tracks(
                from_timestamp=from_timestamp, to_timestamp=to_timestamp, limit=limit
            )


class BlockingNeighborReader(Protocol):
    """Caller-owned synchronous NeighborReader resource."""

    def similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Read the original ordered neighborhood for one seed.

        Args:
            artist: Original seed artist spelling.
            track: Original seed title spelling.
            limit: Original maximum neighborhood size.

        Returns:
            Ordered Last.fm neighbors with original similarity scores.
        """
        ...

    def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Read dated canonical plays within the original UTC bounds.

        Args:
            from_timestamp: Original inclusive lower bound in seconds.
            to_timestamp: Original inclusive upper bound in seconds.
            limit: Original page size.

        Returns:
            Ordered Last.fm observations with original timestamps.
        """
        ...

    @property
    def username(self) -> str:
        """Read the configured Last.fm account name.

        Returns:
            Original case-preserving account name.
        """
        ...

    def similar_artists(
        self, artist: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Return artists similar to a seed artist.

        Args:
            artist: Original seed display spelling.
            limit: Original requested maximum neighbors.

        Returns:
            Original ordered Last.fm neighborhood.
        """
        ...


@dataclass(frozen=True)
class PythonNeighborReader:
    """Await caller-owned NeighborReader I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingNeighborReader | source_the_queue.LastFmReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Read the original ordered neighborhood for one seed.

        Args:
            artist: Original seed artist spelling.
            track: Original seed title spelling.
            limit: Original maximum neighborhood size.

        Returns:
            Ordered Last.fm neighbors with original similarity scores.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_similar_tracks, artist, track, limit=limit
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...] | Awaitable[tuple[LastFmSimilarTrack, ...]]:
        with LegacyControl():
            return self.source.similar_tracks(artist, track, limit=limit)

    async def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Read dated canonical plays within the original UTC bounds.

        Args:
            from_timestamp: Original inclusive lower bound in seconds.
            to_timestamp: Original inclusive upper bound in seconds.
            limit: Original page size.

        Returns:
            Ordered Last.fm observations with original timestamps.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_recent_tracks,
                    from_timestamp=from_timestamp,
                    to_timestamp=to_timestamp,
                    limit=limit,
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...] | Awaitable[tuple[LastFmRecentTrack, ...]]:
        with LegacyControl():
            return self.source.recent_tracks(
                from_timestamp=from_timestamp, to_timestamp=to_timestamp, limit=limit
            )

    @property
    def username(self) -> str:
        """Read the configured Last.fm account name.

        Returns:
            Original case-preserving account name.
        """
        return self.source.username

    async def similar_artists(
        self, artist: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Return artists similar to a seed artist.

        Args:
            artist: Original seed display spelling.
            limit: Original requested maximum neighbors.

        Returns:
            Original ordered Last.fm neighborhood.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_similar_artists, artist, limit=limit)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_similar_artists(
        self, artist: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarArtist, ...] | Awaitable[tuple[LastFmSimilarArtist, ...]]:
        with LegacyControl():
            return self.source.similar_artists(artist, limit=limit)
