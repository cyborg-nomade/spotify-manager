"""Observe and checkpoint recommendation neighborhoods before pure aggregation."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.application.ports.calendar import ListeningCalendar
from spotify_manager.application.ports.runtime import Clock
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_candidates import RecommendationCandidates
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_history import listening_week_start
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


class NeighborhoodCache(Protocol):
    """Retain original cache parsing, previously added exclusions and checkpoints."""

    async def load(self) -> dict[str, object]:
        """Read the validated mutable cache.

        Returns:
            Original schema and entries.
        """

    async def neighbors(self, seed: FoundArtSeed) -> tuple[LastFmSimilarTrack, ...]:
        """Read one uncached Last.fm neighborhood.

        Args:
            seed: Original weighted seed.

        Returns:
            Similar tracks in original response order.
        """

    async def previous(self) -> set[TrackKey]:
        """Read actually added track exclusions.

        Returns:
            Original normalized identities, empty when the log is disabled.
        """

    def lookup(
        self, entry: object, week: date
    ) -> tuple[LastFmSimilarTrack, ...] | None:
        """Decode a current-week entry.

        Args:
            entry: Original raw cache record.
            week: Effective listening week.

        Returns:
            Valid observation, including empty tuples, or a cache miss.
        """

    async def remember(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: FoundArtSeed,
        similar: tuple[LastFmSimilarTrack, ...],
        generated_at: datetime,
    ) -> None:
        """Update and checkpoint a fetched neighborhood before candidate aggregation.

        Args:
            cache: Complete original cache payload.
            entries: Caller-owned entries mapping.
            seed: Original seed metadata.
            similar: Original neighbor records.
            generated_at: Effective fetch timestamp.
        """


@dataclass(frozen=True)
class CandidateGathering:
    """Observe each seed and preserve cache writes before combining candidate support.

    Args:
        cache: Existing cache and prior-addition boundaries.
        clock: Resolve UTC time after validating the requested pool size.
        calendar: Resolve the calendar only when no week was supplied.
        progress: Present original per-seed progress.
    """

    cache: NeighborhoodCache
    clock: Clock
    calendar: ListeningCalendar
    progress: Messages

    async def run(
        self,
        seeds: tuple[FoundArtSeed, ...],
        heard: set[TrackKey],
        week: date | None,
        pool_size: int,
        now: datetime | None = None,
    ) -> tuple[FoundArtCandidate, ...]:
        """Gather neighborhoods in seed order and apply the original ranking policy.

        Args:
            seeds: Original ordered weighted seeds.
            heard: Existing heard-track identities.
            week: Optional effective listening week.
            pool_size: Positive original candidate pool limit.
            now: Parent workflow's already observed timestamp, when available.

        Returns:
            Ranked unheard candidates after all accepted cache checkpoints.

        Raises:
            FoundArtConfigError: Pool size is less than one.
            AssertionError: Validated cache entries changed type.
            FoundArtStateError: Cache or prior-addition data is unusable.
        """
        if pool_size < 1:
            raise FoundArtConfigError("Candidate pool size must be at least 1.")
        generated_at = now or self.clock.now()
        active_week = week or listening_week_start(
            self.calendar.local_date(generated_at)
        )
        cache = await self.cache.load()
        entries = cache["entries"]
        if not isinstance(entries, dict):
            raise AssertionError("validated cache entries changed type")
        candidates = RecommendationCandidates(heard | (await self.cache.previous()))
        for index, seed in enumerate(seeds, start=1):
            self.progress.echo(
                f"Getting Last.fm neighbors for seed {index}/{len(seeds)}"
            )
            similar = await self._neighbors(
                cache, entries, seed, generated_at, active_week
            )
            candidates.observe(seed, similar)
        return candidates.ranked(active_week, pool_size)

    async def _neighbors(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: FoundArtSeed,
        generated_at: datetime,
        week: date,
    ) -> tuple[LastFmSimilarTrack, ...]:
        similar = self.cache.lookup(entries.get("\0".join(seed.key)), week)
        if similar is not None:
            return similar
        similar = await self.cache.neighbors(seed)
        await self.cache.remember(cache, entries, seed, similar, generated_at)
        return similar
