"""Compose recommendation seed selection with the original calendar and limits."""

from collections.abc import Iterable
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.found_art_values import FoundArtSummary
from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.application.recommendation_resolution import (
    RecommendationResolution,
)
from spotify_manager.application.recommendation_run import RecommendationRun
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_matching import FoundArtResult
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
from spotify_manager.infrastructure.legacy.recommendations import LegacyNeighborhoods
from spotify_manager.infrastructure.legacy.recommendations import (
    LegacyRecommendationRun,
)
from spotify_manager.routines import found_art as legacy


def select_seeds(
    history: Iterable[TrackHistory], count: int, week: date | None
) -> tuple[FoundArtSeed, ...]:
    """Bind independent seed selection to the existing routine configuration.

    Args:
        history: Original ordered listening statistics.
        count: Requested seed count.
        week: Optional effective listening week.

    Returns:
        Original selected seeds in group and fallback order.

    Raises:
        FoundArtConfigError: Count is invalid.
        FoundArtStateError: History is empty or insufficiently diverse.
    """
    workflow = RecommendationSeeds(
        legacy.listening_week_start,
        legacy.WEEKLY_SEED_POOL_MULTIPLIER,
        legacy.MAX_SEEDS_PER_ARTIST,
    )
    return workflow.run(history, count, week)


def _generated_at(now: datetime | None) -> datetime:
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def gather_candidates(
    lastfm: legacy.LastFmReader,
    seeds: tuple[FoundArtSeed, ...],
    heard: set[TrackKey],
    cache_path: Path,
    log_path: Path | None,
    week: date | None,
    pool_size: int,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> tuple[FoundArtCandidate, ...]:
    """Compose neighborhood gathering with original storage and calendar helpers.

    Args:
        lastfm: Caller-owned Last.fm reader.
        seeds: Ordered weighted seeds.
        heard: Original heard-track identities.
        cache_path: Original cache destination.
        log_path: Optional prior-addition log.
        week: Optional effective listening week.
        pool_size: Original positive candidate pool limit.
        now: Optional effective UTC time.
        progress: Optional per-seed presenter.

    Returns:
        Original ranked unheard candidates.

    Raises:
        FoundArtConfigError: Pool size is invalid.
        FoundArtStateError: Cache or prior-addition data is invalid.
    """
    observations = LegacyNeighborhoods(lastfm, cache_path, log_path)
    workflow = CandidateGathering(
        observations,
        observations.neighbors,
        partial(_generated_at, now),
        legacy.listening_week_start,
        partial(_progress, progress),
    )
    return workflow.run(seeds, heard, week, pool_size)


def resolve_candidates(
    sp: Spotify,
    candidates: tuple[FoundArtCandidate, ...],
    playlist: PlaylistState,
    count: int,
    dry_run: bool,
    progress: legacy.ProgressCallback | None,
) -> tuple[tuple[FoundArtResult, ...], tuple[SpotifyTrackMatch, ...]]:
    """Bind complete-batch recommendation observations to existing Spotify helpers.

    Args:
        sp: Caller-owned Spotify client.
        candidates: Original ranked candidate pool.
        playlist: Observed destination membership.
        count: Original requested addition count.
        dry_run: Original preview mode.
        progress: Optional original progress presenter.

    Returns:
        Original ordered resolution outcomes and unique pending additions.

    Raises:
        SpotifyTrackResolutionError: Catalog or liked-status data is unusable.
    """
    workflow = RecommendationResolution(
        partial(legacy.blast_from_past.search_spotify_matches, sp),
        partial(legacy.blast_from_past.liked_spotify_track_ids, sp),
        partial(_progress, progress),
        legacy.SPOTIFY_RESOLUTION_BATCH_SIZE,
        legacy.SPOTIFY_CANDIDATE_MULTIPLIER,
    )
    return workflow.run(candidates, playlist, count, dry_run)


def run_recommendations(
    sp: Spotify,
    lastfm: legacy.LastFmReader,
    playlist_id: str,
    count: int | None,
    maximum: int | None,
    seed_count: int,
    dry_run: bool,
    export_path: Path,
    recent_path: Path,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> FoundArtSummary:
    """Compose the original recommendation run from explicit outer dependencies.

    Args:
        sp: Caller-owned Spotify client.
        lastfm: Caller-owned history and neighborhood source.
        playlist_id: Original destination.
        count: Optional explicit addition count.
        maximum: Optional destination capacity.
        seed_count: Original requested seed count.
        dry_run: Original preview mode.
        export_path: Canonical export destination.
        recent_path: Legacy history delta destination.
        cache_path: Neighborhood cache destination.
        log_path: Recommendation audit destination.
        now: Optional effective UTC timestamp.
        progress: Optional original progress observer.

    Returns:
        Original completed summary after accepted effects and audit.

    Raises:
        FoundArtConfigError: Request settings are invalid.
        FoundArtStateError: History, cache, seed selection or audit is unusable.
    """
    effects = LegacyRecommendationRun(
        sp,
        lastfm,
        playlist_id,
        export_path,
        recent_path,
        cache_path,
        log_path,
        progress,
    )
    workflow = RecommendationRun(
        effects,
        partial(_generated_at, now),
        legacy.listening_week_start,
        partial(_progress, progress),
        legacy.DEFAULT_COUNT,
        legacy.MIN_WEEKLY_CANDIDATE_POOL,
        legacy.WEEKLY_CANDIDATE_POOL_MULTIPLIER,
    )
    return workflow.run(playlist_id, count, maximum, seed_count, dry_run)
