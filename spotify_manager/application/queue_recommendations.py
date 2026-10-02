"""Gather Queue artist neighborhoods with original cache checkpoint ordering."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.domain.queue_candidates import LastFmSimilarArtist
from spotify_manager.domain.queue_candidates import QueueCandidates
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.queue_values import ArtistSeed


class QueueNeighborhoodCache(Protocol):
    """Original cache, previous-addition and accepted checkpoint boundaries."""

    def load(self) -> dict[str, object]:
        """Read the validated cache.

        Returns:
            Original complete mutable cache document.
        """

    def previous(self) -> set[str]:
        """Read actual previous additions.

        Returns:
            Original excluded artist identities.
        """

    def lookup(self, raw: object, week: date) -> tuple[LastFmSimilarArtist, ...] | None:
        """Decode a current-week neighborhood.

        Args:
            raw: Original entry, including malformed records.
            week: Effective listening week.

        Returns:
            Observations, including valid empty hits, or a cache miss.
        """

    def remember(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: ArtistSeed,
        similar: tuple[LastFmSimilarArtist, ...],
        generated_at: datetime,
    ) -> None:
        """Update and save a fetched neighborhood before candidate aggregation.

        Args:
            cache: Complete caller-owned cache document.
            entries: Original caller-owned entries mapping.
            seed: Original seed metadata.
            similar: Original fetched neighborhood.
            generated_at: Effective original UTC fetch time.
        """


@dataclass(frozen=True)
class QueueRecommendations:
    """Preserve ordered reads, cache writes and progress before pure ranking.

    Args:
        cache: Original neighborhood persistence boundaries.
        neighbors: Original Last.fm reader.
        clock: Resolve the original UTC timestamp.
        listening_week: Resolve the original local calendar when needed.
        progress: Present original per-seed observations.
    """

    cache: QueueNeighborhoodCache
    neighbors: Callable[[ArtistSeed], tuple[LastFmSimilarArtist, ...]]
    clock: Callable[[], datetime]
    listening_week: Callable[[datetime], date]
    progress: Callable[[int, int, str], None]

    def run(
        self,
        seeds: tuple[ArtistSeed, ...],
        heard: set[str],
        week: date | None,
        limit: int,
    ) -> tuple[ArtistRecommendation, ...]:
        """Gather every seed before applying the original candidate pool slice.

        Args:
            seeds: Original ordered seeds, including duplicate labels.
            heard: Original heard identities.
            week: Optional original explicit listening week.
            limit: Original pool slice limit without additional validation.

        Returns:
            Original ranked candidates after accepted cache writes.

        Raises:
            AssertionError: Validated entries changed type.
            QueueStateError: Original cache or prior-addition data is unusable.
        """
        generated_at = self.clock()
        active_week = week or self.listening_week(generated_at)
        cache = self.cache.load()
        entries = cache["entries"]
        assert isinstance(entries, dict)
        candidates = QueueCandidates(heard | self.cache.previous())
        for index, seed in enumerate(seeds, start=1):
            self.progress(index - 1, len(seeds), f"Last.fm neighbors: {seed.artist}")
            similar = self._neighbors(cache, entries, seed, generated_at, active_week)
            candidates.observe(seed, similar)
        return candidates.ranked(active_week, limit)

    def _neighbors(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: ArtistSeed,
        generated_at: datetime,
        week: date,
    ) -> tuple[LastFmSimilarArtist, ...]:
        similar = self.cache.lookup(entries.get(seed.key), week)
        if similar is not None:
            return similar
        similar = self.neighbors(seed)
        self.cache.remember(cache, entries, seed, similar, generated_at)
        return similar
