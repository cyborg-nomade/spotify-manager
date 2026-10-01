"""Bind recommendation neighborhoods to the original Last.fm and cache helpers."""

from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.found_art_values import FoundArtSummary
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_matching import FoundArtResult
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


@dataclass(frozen=True)
class LegacyRecommendationRun:
    """Retain original public helpers, paths, clients and effect ordering.

    Args:
        sp: Caller-owned Spotify client.
        lastfm: Caller-owned history and neighborhood source.
        playlist_id: Original destination identifier.
        export_path: Canonical export destination.
        recent_path: Legacy history delta destination.
        cache_path: Neighborhood cache destination.
        log_path: Recommendation audit destination.
        progress: Optional original progress observer.
    """

    sp: Spotify
    lastfm: legacy.LastFmReader
    playlist_id: str
    export_path: Path
    recent_path: Path
    cache_path: Path
    log_path: Path
    progress: legacy.ProgressCallback | None

    def refresh(
        self, generated_at: datetime, dry_run: bool
    ) -> tuple[list[Scrobble], int]:
        """Refresh canonical history using its original paths and error translation.

        Args:
            generated_at: Resolved UTC timestamp.
            dry_run: Original preview mode.

        Returns:
            Ordered original plays and live-added count.

        Raises:
            FoundArtStateError: Canonical history cannot be refreshed.
        """
        return legacy.refresh_scrobble_history(
            self.lastfm,
            export_path=self.export_path,
            recent_path=self.recent_path,
            dry_run=dry_run,
            now=generated_at,
            progress_callback=self.progress,
        )

    def read(self) -> PlaylistState:
        """Read destination membership after history refresh.

        Returns:
            Original observed playlist state.

        Raises:
            SpotifyTrackResolutionError: Destination data is unusable.
        """
        return legacy.blast_from_past.load_playlist_state(self.sp, self.playlist_id)

    def seeds(
        self, history: tuple[TrackHistory, ...], count: int, week: date
    ) -> tuple[FoundArtSeed, ...]:
        """Bind original seed selection parameters.

        Args:
            history: Aggregated canonical plays.
            count: Original requested seed count.
            week: Effective listening week.

        Returns:
            Original ordered seeds.

        Raises:
            FoundArtStateError: History cannot supply diverse seeds.
        """
        return legacy.select_seed_tracks(history, seed_count=count, week_start=week)

    def gather(
        self,
        seeds: tuple[FoundArtSeed, ...],
        heard: set[TrackKey],
        week: date,
        pool_size: int,
        generated_at: datetime,
    ) -> tuple[FoundArtCandidate, ...]:
        """Bind original neighborhood cache and exclusion parameters.

        Args:
            seeds: Ordered original seeds.
            heard: Original listening exclusions.
            week: Effective listening week.
            pool_size: Original minimum or scaled candidate pool.
            generated_at: Effective UTC timestamp.

        Returns:
            Original ranked candidates.

        Raises:
            FoundArtStateError: Cache or prior-addition data is unusable.
        """
        return legacy.gather_candidates(
            self.lastfm,
            seeds,
            heard,
            cache_path=self.cache_path,
            log_path=self.log_path,
            week_start=week,
            candidate_pool_size=pool_size,
            now=generated_at,
            progress_callback=self.progress,
        )

    def resolve(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        playlist: PlaylistState,
        count: int,
        dry_run: bool,
    ) -> tuple[tuple[FoundArtResult, ...], tuple[SpotifyTrackMatch, ...]]:
        """Bind original Spotify resolution parameters and helper compatibility seam.

        Args:
            candidates: Original ranked pool.
            playlist: Observed destination membership.
            count: Requested additions.
            dry_run: Original preview mode.

        Returns:
            Original ordered outcomes and pending matches.

        Raises:
            SpotifyTrackResolutionError: Catalog or liked-status data is unusable.
        """
        return legacy.resolve_spotify_candidates(
            self.sp,
            candidates,
            playlist,
            count=count,
            dry_run=dry_run,
            progress_callback=self.progress,
        )

    def append(self, pending: list[SpotifyTrackMatch]) -> None:
        """Append pending matches through the original accepted mutation boundary.

        Args:
            pending: Ordered original additions.

        Raises:
            SpotifyTrackResolutionError: A remote append fails.
        """
        legacy.blast_from_past.add_spotify_matches(self.sp, self.playlist_id, pending)

    def audit(self, summary: FoundArtSummary) -> None:
        """Append the original audit after accepted effects, including previews.

        Args:
            summary: Original completed result.

        Raises:
            FoundArtStateError: Audit append fails.
        """
        legacy.append_found_art_log(summary, self.log_path)
