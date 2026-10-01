"""Rebuild Last.fm-style track recommendations for the Found Art playlist."""

import json
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
from spotify_manager.client.lastfm import LastFmSimilarTrack
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
        """Return tracks similar to a seed."""

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ) -> tuple[LastFmRecentTrack, ...]:
        """Return dated scrobbles in a UTC range."""


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
    """Parse the configured Found Art destination playlist."""
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
    """Return stripped read-only Last.fm settings or raise a clear error."""
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
    """Refresh the canonical export and absorb the legacy Found Art delta."""
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
    from spotify_manager.bootstrap.recommendations import select_seeds

    return select_seeds(history, seed_count, week_start)


def _cache_key(seed: FoundArtSeed) -> str:
    """Return a JSON-safe stable seed cache key."""
    return "\u0000".join(seed.key)


def _load_similar_cache(path: Path) -> dict[str, object]:
    """Load the recommendation cache without silently replacing corruption."""
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundArtStateError(f"Found Art cache is invalid: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or not isinstance(payload.get("entries"), dict)
    ):
        raise FoundArtStateError(f"Found Art cache is invalid: {path}")
    return payload


def _save_similar_cache(payload: dict[str, object], path: Path) -> None:
    """Atomically save recommendation progress after each completed seed."""
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise FoundArtStateError(f"Could not save Found Art cache: {path}") from exc


def _cached_similar_tracks(
    entry: object,
    *,
    week_start: date,
) -> tuple[LastFmSimilarTrack, ...] | None:
    """Return a cache entry fetched during the active listening week."""
    if not isinstance(entry, dict):
        return None
    try:
        fetched_at = datetime.fromisoformat(str(entry["fetched_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        if listening_week_start(fetched_at) != week_start:
            return None
        raw_tracks = entry["tracks"]
        if not isinstance(raw_tracks, list):
            return None
        return tuple(
            LastFmSimilarTrack(
                artist=str(raw["artist"]),
                track=str(raw["track"]),
                match=float(raw["match"]),
            )
            for raw in raw_tracks
            if isinstance(raw, dict)
        )
    except KeyError, TypeError, ValueError:
        return None


def previously_added_track_keys(
    path: Path = DEFAULT_LOG_PATH,
) -> set[TrackKey]:
    """Return tracks actually added by earlier Found Art runs."""
    if not path.exists():
        return set()
    keys: set[TrackKey] = set()
    current_line = 0
    try:
        with path.open(encoding="utf-8") as log_file:
            for line_number, line in enumerate(log_file, start=1):
                current_line = line_number
                if not line.strip():
                    continue
                record = json.loads(line)
                raw_results = (
                    record.get("results") if isinstance(record, dict) else None
                )
                if not isinstance(raw_results, list):
                    raise ValueError("results must be a list")
                for result in raw_results:
                    if not isinstance(result, dict) or result.get("action") != "added":
                        continue
                    candidate = result.get("candidate")
                    if not isinstance(candidate, dict):
                        raise ValueError("candidate must be an object")
                    keys.add(
                        canonical_track_key(
                            str(candidate["artist"]),
                            str(candidate["track"]),
                        )
                    )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        detail = f" at line {current_line}" if current_line else ""
        raise FoundArtStateError(
            f"Found Art audit log is invalid{detail}: {path}"
        ) from exc
    return keys


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
    from spotify_manager.bootstrap.recommendations import gather_candidates as gather

    return gather(
        lastfm,
        seeds,
        heard_keys,
        cache_path,
        log_path,
        week_start,
        candidate_pool_size,
        now,
        progress_callback,
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
    from spotify_manager.bootstrap.recommendations import resolve_candidates

    return resolve_candidates(
        sp, candidates, playlist, count, dry_run, progress_callback
    )


def _result_record(result: FoundArtResult) -> dict[str, object]:
    """Return one JSON-compatible audit result."""
    return {
        "candidate": {
            "artist": result.candidate.artist,
            "track": result.candidate.track,
            "score": result.candidate.score,
            "best_match": result.candidate.best_match,
            "supporting_seeds": list(result.candidate.supporting_seeds),
            "base_rank": result.candidate.base_rank,
            "weekly_rank": result.candidate.weekly_rank,
        },
        "match": (
            {
                "spotify_id": result.match.spotify_id,
                "uri": result.match.uri,
                "track": result.match.track,
                "artists": list(result.match.artists),
                "album": result.match.album,
                "track_similarity": result.match.track_similarity,
                "popularity": result.match.popularity,
            }
            if result.match is not None
            else None
        ),
        "action": result.action,
    }


def append_found_art_log(
    summary: FoundArtSummary,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append a reviewable run record after any Spotify write succeeds."""
    record = {
        "generated_at": summary.generated_at.isoformat(),
        "week_start": summary.week_start.isoformat(),
        "playlist_id": summary.playlist_id,
        "requested_count": summary.requested_count,
        "seed_count": summary.seed_count,
        "history_tracks": summary.history_tracks,
        "history_scrobbles": summary.history_scrobbles,
        "live_scrobbles_added": summary.live_scrobbles_added,
        "candidate_count": summary.candidate_count,
        "playlist_length_before": summary.playlist_length_before,
        "playlist_length_after": summary.playlist_length_after,
        "dry_run": summary.dry_run,
        "seeds": [
            {
                "artist": seed.artist,
                "track": seed.track,
                "source": seed.source,
                "play_count": seed.play_count,
                "source_play_count": seed.source_play_count,
                "weight": seed.weight,
                "weekly_rank": seed.weekly_rank,
            }
            for seed in summary.seeds
        ],
        "results": [_result_record(result) for result in summary.results],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise FoundArtStateError(f"Could not write Found Art log: {path}") from exc


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
    from spotify_manager.bootstrap.recommendations import run_recommendations

    return run_recommendations(
        sp,
        lastfm,
        playlist_id,
        count,
        max_playlist_length,
        seed_count,
        dry_run,
        export_path,
        recent_path,
        cache_path,
        log_path,
        now,
        progress_callback,
    )
