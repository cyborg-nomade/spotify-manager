"""Bind Queue recommendations to caller-owned original Last.fm and file seams."""

import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

from spotify_manager.domain.queue_candidates import LastFmSimilarArtist
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.routines import the_queue as legacy


@dataclass(frozen=True)
class LegacyQueueNeighborhoods:
    """Retain original persistence and observation behavior at the outer edge.

    Args:
        reader: Original caller-owned Last.fm client.
        cache_path: Original neighborhood cache location.
        log_path: Original previous-addition log location.
        now: Optional original explicit timestamp.
        callback: Optional original progress presenter.
        timestamp_override: Original optional timestamp override.
    """

    reader: legacy.LastFmReader
    cache_path: Path
    log_path: Path
    timestamp_override: datetime | None
    callback: legacy.ProgressCallback | None

    async def load(self) -> dict[str, object]:
        """Read the original validated cache.

        Returns:
            Original mutable cache document.
        """
        from spotify_manager.routines.the_queue import _load_cache

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_load_cache, self.cache_path)
            )
            return await finish_blocking(file_operation)

    async def previous(self) -> set[str]:
        """Read original actually added artist exclusions.

        Returns:
            Original normalized artist identities.
        """
        from spotify_manager.routines.the_queue import (
            previously_added_artist_keys as _previously_added_artist_keys,
        )

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_previously_added_artist_keys, self.log_path)
            )
            return await finish_blocking(file_operation)

    def lookup(self, raw: object, week: date) -> tuple[LastFmSimilarArtist, ...] | None:
        """Decode the original current-week cache record.

        Args:
            raw: Original unchecked cache entry.
            week: Effective original listening week.

        Returns:
            Original cached observations or a miss.
        """
        from spotify_manager.routines.the_queue import _cached_similar_artists

        return _cached_similar_artists(raw, week)

    async def remember(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: ArtistSeed,
        similar: tuple[LastFmSimilarArtist, ...],
        generated_at: datetime,
    ) -> None:
        """Preserve the original cache record and immediate save boundary.

        Args:
            cache: Complete caller-owned cache document.
            entries: Original caller-owned entries mapping.
            seed: Original seed metadata.
            similar: Original Last.fm observations.
            generated_at: Original effective UTC time.
        """
        from spotify_manager.routines.the_queue import _save_cache

        entries[seed.key] = {
            "artist": seed.artist,
            "fetched_at": generated_at.isoformat(),
            "artists": [asdict(candidate) for candidate in similar],
        }
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_save_cache, cache, self.cache_path)
            )
            await finish_blocking(file_operation)

    async def neighbors(self, seed: ArtistSeed) -> tuple[LastFmSimilarArtist, ...]:
        """Read one original artist neighborhood.

        Args:
            seed: Original requested artist and display spelling.

        Returns:
            Original ordered neighbor observations.
        """
        return await self.reader.similar_artists(
            seed.artist, limit=legacy.SIMILAR_ARTIST_LIMIT
        )

    def now(self) -> datetime:
        """Resolve the original timestamp before loading the cache.

        Returns:
            Original supplied or current timestamp converted to UTC.
        """
        return (self.timestamp_override or legacy.datetime.now(UTC)).astimezone(UTC)

    def progress(self, current: int, total: int, status: str) -> None:
        """Present the original progress only when configured.

        Args:
            current: Original completed-seed count.
            total: Original seed count.
            status: Original status text.
        """
        if self.callback is not None:
            self.callback.progress(current, total, status)
