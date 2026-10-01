"""Observe and checkpoint recommendation neighborhoods before pure aggregation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_candidates import RecommendationCandidates
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


class NeighborhoodCache(Protocol):
    """Retain original cache parsing, previously added exclusions and checkpoints."""

    def load(self) -> dict[str, object]:
        """Read the validated mutable cache.

        Returns:
            Original schema and entries.
        """

    def previous(self) -> set[TrackKey]:
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

    def remember(
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
        neighbors: Read one seed's Last.fm neighborhood.
        clock: Resolve UTC time after validating the requested pool size.
        listening_week: Resolve the calendar only when no week was supplied.
        progress: Present original per-seed progress.
    """

    cache: NeighborhoodCache
    neighbors: Callable[[FoundArtSeed], tuple[LastFmSimilarTrack, ...]]
    clock: Callable[[], datetime]
    listening_week: Callable[[datetime], date]
    progress: Callable[[str], None]

    def run(
        self,
        seeds: tuple[FoundArtSeed, ...],
        heard: set[TrackKey],
        week: date | None,
        pool_size: int,
    ) -> tuple[FoundArtCandidate, ...]:
        """Gather neighborhoods in seed order and apply the original ranking policy.

        Args:
            seeds: Original ordered weighted seeds.
            heard: Existing heard-track identities.
            week: Optional effective listening week.
            pool_size: Positive original candidate pool limit.

        Returns:
            Ranked unheard candidates after all accepted cache checkpoints.

        Raises:
            FoundArtConfigError: Pool size is less than one.
            AssertionError: Validated cache entries changed type.
            FoundArtStateError: Cache or prior-addition data is unusable.
        """
        if pool_size < 1:
            raise FoundArtConfigError("Candidate pool size must be at least 1.")
        generated_at = self.clock()
        active_week = week or self.listening_week(generated_at)
        cache = self.cache.load()
        entries = cache["entries"]
        if not isinstance(entries, dict):
            raise AssertionError("validated cache entries changed type")
        candidates = RecommendationCandidates(heard | self.cache.previous())
        for index, seed in enumerate(seeds, start=1):
            self.progress(f"Getting Last.fm neighbors for seed {index}/{len(seeds)}")
            similar = self._neighbors(cache, entries, seed, generated_at, active_week)
            candidates.observe(seed, similar)
        return candidates.ranked(active_week, pool_size)

    def _neighbors(
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
        similar = self.neighbors(seed)
        self.cache.remember(cache, entries, seed, similar, generated_at)
        return similar
