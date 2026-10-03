"""Invoke found art use cases for CLI and HTTP features."""

from collections.abc import Iterable as Iterable
from datetime import date as date
from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.found_art_values import (
    FoundArtConfigError as FoundArtConfigError,
)
from spotify_manager.application.found_art_values import FoundArtError as FoundArtError
from spotify_manager.application.found_art_values import (
    FoundArtSummary as FoundArtSummary,
)
from spotify_manager.bootstrap.recommendations import candidate_gathering
from spotify_manager.bootstrap.recommendations import recommendation_resolution
from spotify_manager.bootstrap.recommendations import recommendation_run
from spotify_manager.bootstrap.recommendations import recommendation_seeds
from spotify_manager.domain.recommendation_candidates import (
    FoundArtCandidate as FoundArtCandidate,
)
from spotify_manager.domain.recommendation_history import TrackHistory as TrackHistory
from spotify_manager.domain.recommendation_matching import (
    FoundArtResult as FoundArtResult,
)
from spotify_manager.domain.recommendation_seeds import FoundArtSeed as FoundArtSeed
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines.found_art import DEFAULT_CACHE_PATH as DEFAULT_CACHE_PATH
from spotify_manager.routines.found_art import DEFAULT_COUNT as DEFAULT_COUNT
from spotify_manager.routines.found_art import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.found_art import (
    DEFAULT_RECENT_PATH as DEFAULT_RECENT_PATH,
)
from spotify_manager.routines.found_art import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.found_art import DEFAULT_SEED_COUNT as DEFAULT_SEED_COUNT
from spotify_manager.routines.found_art import (
    MIN_WEEKLY_CANDIDATE_POOL as MIN_WEEKLY_CANDIDATE_POOL,
)
from spotify_manager.routines.found_art import LastFmReader as LastFmReader
from spotify_manager.routines.found_art import ProgressCallback as ProgressCallback
from spotify_manager.routines.found_art import TrackKey as TrackKey
from spotify_manager.routines.found_art import (
    parse_found_art_playlist_id as parse_found_art_playlist_id,
)
from spotify_manager.routines.found_art import (
    validate_lastfm_configuration as validate_lastfm_configuration,
)


def select_seed_tracks(
    history: Iterable[TrackHistory],
    *,
    seed_count: int = DEFAULT_SEED_COUNT,
    week_start: date | None = None,
) -> tuple[FoundArtSeed, ...]:
    """Choose a weekly weighted mix of recent and established favorites.

    Args:
        history: Original ordered listening statistics.
        seed_count: Requested seed count, subject to the original artist cap.
        week_start: Optional listening week's Friday.

    Returns:
        Exactly the requested number of seeds in quota and fallback order.

    Raises:
        FoundArtConfigError: Count is less than one.
        FoundArtStateError: History is empty or lacks enough diverse seeds.
    """
    configured = recommendation_seeds()
    return configured.run(history, seed_count, week_start)


def gather_candidates(
    lastfm: LastFmReader,
    seeds: tuple[FoundArtSeed, ...],
    heard_keys: set[TrackKey],
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path | None = DEFAULT_LOG_PATH,
    week_start: date | None = None,
    candidate_pool_size: int = MIN_WEEKLY_CANDIDATE_POOL,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[FoundArtCandidate, ...]:
    """Combine seed neighborhoods and apply the weekly weighted ordering.

    Args:
        lastfm: Caller-owned neighborhood reader.
        seeds: Ordered weighted recommendation seeds.
        heard_keys: Normalized identities excluded by listening history.
        cache_path: Mutable neighborhood cache destination.
        log_path: Prior-addition log, or disabled exclusions when absent.
        week_start: Optional effective listening week.
        candidate_pool_size: Positive maximum pool before weekly rotation.
        now: Optional timestamp used for cache freshness and the default week.
        progress_callback: Optional observer of per-seed progress.

    Returns:
        Ranked unheard candidates after all cache checkpoints succeed.

    Raises:
        FoundArtConfigError: The pool size is less than one.
        FoundArtStateError: Cache or enabled prior-addition data is unusable.
        AssertionError: Validated cache entries or candidate support are corrupted.
    """
    configured = candidate_gathering(
        lastfm, cache_path, log_path, now, progress_callback
    )
    return configured.run(seeds, heard_keys, week_start, candidate_pool_size)


def resolve_spotify_candidates(
    sp: Spotify,
    candidates: tuple[FoundArtCandidate, ...],
    playlist: blast_from_past.PlaylistState,
    *,
    count: int,
    dry_run: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[FoundArtResult, ...], tuple[blast_from_past.SpotifyTrackMatch, ...]]:
    """Search complete batches and retain original ordered selection decisions.

    Args:
        sp: Caller-owned Spotify client.
        candidates: Original ranked recommendation pool.
        playlist: Observed destination membership.
        count: Requested additions; helper-level nonpositive counts are tolerated.
        dry_run: Present proposed additions when true.
        progress_callback: Optional per-search and liked-check presenter.

    Returns:
        Ordered candidate outcomes and unique pending matches.

    Raises:
        SpotifyTrackResolutionError: Catalog or liked-status data is unusable.
        ValueError: The configured batch size is zero.
    """
    configured = recommendation_resolution(sp, progress_callback)
    return configured.run(candidates, playlist, count, dry_run)


def run_found_art(
    sp: Spotify,
    lastfm: LastFmReader,
    playlist_id: str,
    *,
    count: int | None = DEFAULT_COUNT,
    max_playlist_length: int | None = None,
    seed_count: int = DEFAULT_SEED_COUNT,
    dry_run: bool = False,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> FoundArtSummary:
    """Refresh history, resolve recommendations, append matches and audit the run.

    Args:
        sp: Caller-owned Spotify client.
        lastfm: Caller-owned history and neighborhood reader.
        playlist_id: Original destination identifier.
        count: Optional positive explicit addition count.
        max_playlist_length: Optional positive capacity, exclusive with count.
        seed_count: Positive requested neighborhood seed count.
        dry_run: Suppress remote appends while retaining preview history and audit.
        export_path: Original canonical export path.
        recent_path: Original legacy history delta path.
        cache_path: Original neighborhood cache destination.
        log_path: Original audit destination.
        now: Optional effective UTC timestamp.
        progress_callback: Optional original progress observer.

    Returns:
        Original completed summary after its audit is accepted.

    Raises:
        FoundArtConfigError: Request settings are invalid.
        FoundArtStateError: History, cache, seed selection or audit is unusable.
        SpotifyTrackResolutionError: Catalog or destination data is unusable.
    """
    configured = recommendation_run(
        sp,
        lastfm,
        playlist_id,
        export_path,
        recent_path,
        cache_path,
        log_path,
        now,
        progress_callback,
    )
    return configured.run(playlist_id, count, max_playlist_length, seed_count, dry_run)
