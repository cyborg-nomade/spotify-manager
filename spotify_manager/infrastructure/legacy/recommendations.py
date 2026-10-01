"""Bind recommendation neighborhoods to the original Last.fm and cache helpers."""

from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path

from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
from spotify_manager.routines import found_art as legacy


@dataclass(frozen=True)
class LegacyNeighborhoods:
    """Retain Last.fm reads, tolerant cache decoding and original checkpoint bytes.

    Args:
        lastfm: Caller-owned Last.fm reader.
        cache_path: Original mutable cache destination.
        log_path: Original prior-addition log, or disabled exclusions.
    """

    lastfm: legacy.LastFmReader
    cache_path: Path
    log_path: Path | None

    def load(self) -> dict[str, object]:
        """Read the validated original cache.

        Returns:
            Original mutable payload.

        Raises:
            FoundArtStateError: Cache contents are invalid.
        """
        return legacy._load_similar_cache(self.cache_path)

    def previous(self) -> set[TrackKey]:
        """Observe prior accepted additions when their log is enabled.

        Returns:
            Original normalized exclusion keys.

        Raises:
            FoundArtStateError: The enabled audit log is invalid.
        """
        if self.log_path is None:
            return set()
        return legacy.previously_added_track_keys(self.log_path)

    def lookup(
        self, entry: object, week: date
    ) -> tuple[LastFmSimilarTrack, ...] | None:
        """Decode the existing cache using its original timezone and schema tolerance.

        Args:
            entry: Original raw entry.
            week: Effective listening week.

        Returns:
            Current-week observations, or a cache miss.
        """
        return legacy._cached_similar_tracks(entry, week_start=week)

    def neighbors(self, seed: FoundArtSeed) -> tuple[LastFmSimilarTrack, ...]:
        """Read the original number of similar tracks for one seed.

        Args:
            seed: Original artist and track display metadata.

        Returns:
            Ordered Last.fm neighborhood.
        """
        return self.lastfm.similar_tracks(
            seed.artist, seed.track, limit=legacy.DEFAULT_SIMILAR_TRACK_LIMIT
        )

    def remember(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: FoundArtSeed,
        similar: tuple[LastFmSimilarTrack, ...],
        generated_at: datetime,
    ) -> None:
        """Save one fetched neighborhood with its original cache representation.

        Args:
            cache: Complete mutable payload.
            entries: Original entries mapping.
            seed: Original seed metadata.
            similar: Original fetched records, including empty responses.
            generated_at: Original fetch timestamp.

        Raises:
            FoundArtStateError: Cache replacement fails after working entry updates.
        """
        entries[legacy._cache_key(seed)] = {
            "artist": seed.artist,
            "track": seed.track,
            "fetched_at": generated_at.isoformat(),
            "tracks": [asdict(track) for track in similar],
        }
        legacy._save_similar_cache(cache, self.cache_path)
