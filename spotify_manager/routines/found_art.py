"""Rebuild Last.fm-style track recommendations for the Found Art playlist."""

from collections.abc import Iterable
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Protocol

from spotipy import Spotify

from spotify_manager.application.found_art_values import (
    FoundArtConfigError as FoundArtConfigError,
)
from spotify_manager.application.found_art_values import FoundArtError as FoundArtError
from spotify_manager.application.found_art_values import (
    FoundArtStateError as FoundArtStateError,
)
from spotify_manager.application.found_art_values import (
    FoundArtSummary as FoundArtSummary,
)
from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.client.lastfm import LastFmSimilarTrack as LastFmSimilarTrack
from spotify_manager.domain import recommendation_history as history_policy
from spotify_manager.domain.recommendation_candidates import (
    FoundArtCandidate as FoundArtCandidate,
)
from spotify_manager.domain.recommendation_candidates import (
    _CandidateAccumulator as _CandidateAccumulator,
)
from spotify_manager.domain.recommendation_history import TrackHistory as TrackHistory
from spotify_manager.domain.recommendation_matching import (
    FoundArtAction as FoundArtAction,
)
from spotify_manager.domain.recommendation_matching import (
    FoundArtResult as FoundArtResult,
)
from spotify_manager.domain.recommendation_matching import (
    preferred_recommendation_match,
)
from spotify_manager.domain.recommendation_seeds import FoundArtSeed as FoundArtSeed
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history as shared_scrobble_history


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH
DEFAULT_CACHE_PATH = FILES_DIR / "found_art_cache.json"
DEFAULT_RECENT_PATH = FILES_DIR / "found_art_recent_scrobbles.jsonl"
DEFAULT_LOG_PATH = FILES_DIR / "found_art_log.jsonl"
DEFAULT_COUNT = 20
DEFAULT_SEED_COUNT = 30
DEFAULT_SIMILAR_TRACK_LIMIT = 50
SPOTIFY_RESOLUTION_BATCH_SIZE = 10
SPOTIFY_CANDIDATE_MULTIPLIER = 10
WEEKLY_SEED_POOL_MULTIPLIER = 10
WEEKLY_CANDIDATE_POOL_MULTIPLIER = 10
MIN_WEEKLY_CANDIDATE_POOL = 100
MAX_SEEDS_PER_ARTIST = 2
TrackKey = tuple[str, str]
ProgressCallback = blast_from_past.ProgressCallback


class LastFmReader(Protocol):
    """Read-only Last.fm methods used by this routine."""

    def similar_tracks(
        self,
        artist: str,
        track: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Read the original ordered neighborhood for one seed.

        Args:
            artist: Original seed artist spelling.
            track: Original seed title spelling.
            limit: Original maximum neighborhood size.

        Returns:
            Ordered Last.fm neighbors with original similarity scores.
        """

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ) -> tuple[LastFmRecentTrack, ...]:
        """Read dated canonical plays within the original UTC bounds.

        Args:
            from_timestamp: Original inclusive lower bound in seconds.
            to_timestamp: Original inclusive upper bound in seconds.
            limit: Original page size.

        Returns:
            Ordered Last.fm observations with original timestamps.
        """


def canonical_track_key(artist: str, track: str) -> TrackKey:
    """Return the edition-tolerant identity used for heard-track filtering.

    Args:
        artist: Original display artist.
        track: Original display title.

    Returns:
        Normalized artist and qualifier-free track identities.
    """
    return history_policy.canonical_track_key(artist, track)


def listening_week_start(value: datetime | date | None = None) -> date:
    """Return the Friday that starts the applicable Berlin listening week.

    Args:
        value: Optional date or timestamp; naive timestamps are interpreted as UTC.

    Returns:
        The preceding or same-day Friday after Berlin timezone conversion.
    """
    if value is None:
        local_date = datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        local_date = value.astimezone(blast_from_past.SCROBBLE_TIMEZONE).date()
    else:
        local_date = value
    return history_policy.listening_week_start(local_date)


def _weekly_unit_interval(
    week_start: date,
    namespace: str,
    key: TrackKey,
) -> float:
    """Return a stable nonzero 0-1 value for one track and listening week."""
    return history_policy.weekly_unit_interval(week_start, namespace, key)


def weekly_weighted_rank(
    week_start: date,
    namespace: str,
    key: TrackKey,
    weight: float,
) -> float:
    """Return a deterministic weighted-sampling key; larger values rank first.

    Args:
        week_start: Effective listening week's Friday.
        namespace: Existing ranking context.
        key: Original normalized track identity.
        weight: Existing sampling weight, floored at one millionth.

    Returns:
        The original weighted hash fraction.
    """
    return history_policy.weekly_weighted_rank(week_start, namespace, key, weight)


def parse_found_art_playlist_id(reference: str | None) -> str:
    """Parse the original destination and translate its configuration error.

    Args:
        reference: Configured playlist identifier, URI or URL.

    Returns:
        Original parsed playlist identifier.

    Raises:
        FoundArtConfigError: The original playlist parser rejects the reference.
    """
    try:
        return blast_from_past.parse_playlist_id(
            reference,
            setting_name="FOUND_ART_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise FoundArtConfigError(str(exc)) from exc


def validate_lastfm_configuration(
    api_key: str | None,
    username: str | None,
) -> tuple[str, str]:
    """Validate original Last.fm settings in API-key then username order.

    Args:
        api_key: Configured read-only Last.fm API key.
        username: Configured Last.fm username.

    Returns:
        Original stripped API key and username.

    Raises:
        FoundArtConfigError: Either original required value is blank or absent.
    """
    if not api_key or not api_key.strip():
        raise FoundArtConfigError("LASTFM_API_KEY is not configured.")
    if not username or not username.strip():
        raise FoundArtConfigError("LASTFM_USERNAME is not configured.")
    return api_key.strip(), username.strip()


def refresh_scrobble_history(
    lastfm: LastFmReader,
    *,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    dry_run: bool = False,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[blast_from_past.Scrobble], int]:
    """Refresh canonical history and translate errors with their original cause.

    Args:
        lastfm: Caller-owned history reader with optional username metadata.
        export_path: Original canonical export destination.
        recent_path: Original legacy delta source.
        dry_run: Original history refresh preview mode.
        now: Optional effective UTC timestamp.
        progress_callback: Optional original progress observer.

    Returns:
        Canonical plays as a list and the original live-added count.

    Raises:
        FoundArtStateError: Canonical refresh raises its original history error.
    """
    try:
        summary = shared_scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username=getattr(lastfm, "username", None),
            export_path=export_path,
            legacy_delta_path=recent_path,
            backup_dir=export_path.parent / "lastfm_history_backups",
            log_path=export_path.parent / "scrobble_history_update_log.jsonl",
            dry_run=dry_run,
            now=now,
            progress_callback=progress_callback,
        )
    except shared_scrobble_history.ScrobbleHistoryError as exc:
        raise FoundArtStateError(str(exc)) from exc
    return list(summary.history), summary.live_scrobbles_added


def aggregate_track_history(
    scrobbles: Iterable[blast_from_past.Scrobble],
) -> tuple[TrackHistory, ...]:
    """Aggregate all-time, annual, and 90-day seed statistics.

    Args:
        scrobbles: Ordered original plays, including invalid normalized identities.

    Returns:
        Valid identities in first-seen order with inclusive window counts.
    """
    return history_policy.aggregate_track_history(scrobbles)


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
    from spotify_manager.interfaces.operations.found_art import (
        select_seed_tracks as operation,
    )

    return operation(history, seed_count=seed_count, week_start=week_start)


def _cache_key(seed: FoundArtSeed) -> str:
    """Return a JSON-safe stable seed cache key."""
    return "\u0000".join(seed.key)


def _load_similar_cache(path: Path) -> dict[str, object]:
    from spotify_manager.infrastructure.recommendations_data import load_cache

    return load_cache(path)


def _save_similar_cache(payload: dict[str, object], path: Path) -> None:
    from spotify_manager.infrastructure.recommendations_data import save_cache

    save_cache(payload, path)


def _cached_similar_tracks(
    entry: object,
    *,
    week_start: date,
) -> tuple[LastFmSimilarTrack, ...] | None:
    from spotify_manager.infrastructure.recommendations_data import cached_neighbors

    return cached_neighbors(
        entry, week_start, listening_week_start, datetime.fromisoformat
    )


def previously_added_track_keys(
    path: Path = DEFAULT_LOG_PATH,
) -> set[TrackKey]:
    """Read actually added identities with original physical-line diagnostics.

    Args:
        path: Original audit source.

    Returns:
        Original normalized added identities, empty when the log is absent.

    Raises:
        FoundArtStateError: Reading or decoding fails at an observed physical line.
    """
    from spotify_manager.infrastructure.recommendations_data import (
        previously_added_keys,
    )

    return previously_added_keys(path, canonical_track_key)


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
    from spotify_manager.interfaces.operations.found_art import (
        gather_candidates as operation,
    )

    return operation(
        lastfm,
        seeds,
        heard_keys,
        cache_path=cache_path,
        log_path=log_path,
        week_start=week_start,
        candidate_pool_size=candidate_pool_size,
        now=now,
        progress_callback=progress_callback,
    )


def _preferred_unliked_match(
    matches: tuple[blast_from_past.SpotifyTrackMatch, ...],
    liked_ids: set[str],
) -> blast_from_past.SpotifyTrackMatch | None:
    """Choose the strongest Spotify match after excluding liked tracks."""
    return preferred_recommendation_match(matches, liked_ids, liked=False)


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
    from spotify_manager.interfaces.operations.found_art import (
        resolve_spotify_candidates as operation,
    )

    return operation(
        sp,
        candidates,
        playlist,
        count=count,
        dry_run=dry_run,
        progress_callback=progress_callback,
    )


def _result_record(result: FoundArtResult) -> dict[str, object]:
    from spotify_manager.infrastructure.recommendations_data import result_record

    return result_record(result)


def append_found_art_log(
    summary: FoundArtSummary,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append the original audit after accepted effects, including previews.

    Args:
        summary: Completed original recommendation run.
        path: Original audit destination.

    Raises:
        FoundArtStateError: Directory creation or log append fails.
    """
    from spotify_manager.infrastructure.recommendations_data import append_audit

    append_audit(summary, path)


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
    from spotify_manager.interfaces.operations.found_art import (
        run_found_art as operation,
    )

    return operation(
        sp,
        lastfm,
        playlist_id,
        count=count,
        max_playlist_length=max_playlist_length,
        seed_count=seed_count,
        dry_run=dry_run,
        export_path=export_path,
        recent_path=recent_path,
        cache_path=cache_path,
        log_path=log_path,
        now=now,
        progress_callback=progress_callback,
    )
