"""Rebuild Last.fm-style track recommendations for the Found Art playlist."""

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Literal
from typing import Protocol

from spotipy import Spotify

# UFI
from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.client.lastfm import LastFmSimilarTrack
from spotify_manager.routines import blast_from_past


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
FoundArtAction = Literal[
    "added",
    "would add",
    "already present",
    "artist already selected",
    "duplicate",
    "liked",
    "no Spotify match",
]


class FoundArtError(RuntimeError):
    """Base error for the Found Art recommendation routine."""


class FoundArtConfigError(FoundArtError):
    """Raised when required Last.fm or Spotify settings are missing."""


class FoundArtStateError(FoundArtError):
    """Raised when a cache, delta, or audit file cannot be used safely."""


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


@dataclass(frozen=True)
class TrackHistory:
    """Aggregated listening statistics for one normalized track."""

    artist: str
    track: str
    key: TrackKey
    play_count: int
    recent_play_count: int
    annual_play_count: int
    last_played_ms: int


@dataclass(frozen=True)
class FoundArtSeed:
    """One known track used to ask Last.fm for neighbors."""

    artist: str
    track: str
    key: TrackKey
    source: Literal["recent", "annual", "overall"]
    play_count: int
    source_play_count: int
    weight: float
    weekly_rank: float = 1.0


@dataclass(frozen=True)
class FoundArtCandidate:
    """One unheard candidate aggregated across seed recommendations."""

    artist: str
    track: str
    key: TrackKey
    score: float
    best_match: float
    supporting_seeds: tuple[str, ...]
    base_rank: int = 0
    weekly_rank: float = 1.0


@dataclass(frozen=True)
class FoundArtResult:
    """Spotify resolution outcome for one ranked Last.fm candidate."""

    candidate: FoundArtCandidate
    match: blast_from_past.SpotifyTrackMatch | None
    action: FoundArtAction


@dataclass(frozen=True)
class FoundArtSummary:
    """Completed Found Art recommendation and Spotify update."""

    generated_at: datetime
    week_start: date
    playlist_id: str
    requested_count: int
    seed_count: int
    history_tracks: int
    history_scrobbles: int
    live_scrobbles_added: int
    candidate_count: int
    playlist_length_before: int
    playlist_length_after: int
    dry_run: bool
    seeds: tuple[FoundArtSeed, ...]
    results: tuple[FoundArtResult, ...]

    @property
    def added(self) -> int:
        """Return actual Spotify additions made by this run."""
        return sum(result.action == "added" for result in self.results)

    @property
    def selected(self) -> int:
        """Return additions or proposed additions selected by the run."""
        return sum(result.action in {"added", "would add"} for result in self.results)


@dataclass
class _CandidateAccumulator:
    """Mutable aggregation state while seed neighborhoods are combined."""

    artist: str
    track: str
    key: TrackKey
    score: float = 0.0
    best_match: float = 0.0
    supporting_seeds: set[str] | None = None

    def __post_init__(self) -> None:
        if self.supporting_seeds is None:
            self.supporting_seeds = set()


def canonical_track_key(artist: str, track: str) -> TrackKey:
    """Return the edition-tolerant identity used for heard-track filtering."""
    return (
        blast_from_past.normalize_name(artist),
        blast_from_past.normalize_name(
            blast_from_past.without_sliding_qualifiers(track)
        ),
    )


def listening_week_start(value: datetime | date | None = None) -> date:
    """Return the Friday that starts the applicable Berlin listening week."""
    if value is None:
        local_date = datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        local_date = value.astimezone(blast_from_past.SCROBBLE_TIMEZONE).date()
    else:
        local_date = value
    days_since_friday = (local_date.weekday() - 4) % 7
    return local_date - timedelta(days=days_since_friday)


def _weekly_unit_interval(
    week_start: date,
    namespace: str,
    key: TrackKey,
) -> float:
    """Return a stable nonzero 0-1 value for one track and listening week."""
    payload = "\0".join((week_start.isoformat(), namespace, *key)).encode()
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    integer = int.from_bytes(digest, byteorder="big")
    return (integer + 1) / ((2**64) + 1)


def _weekly_weighted_rank(
    week_start: date,
    namespace: str,
    key: TrackKey,
    weight: float,
) -> float:
    """Return a deterministic weighted-sampling key; larger values rank first."""
    return _weekly_unit_interval(week_start, namespace, key) ** (
        1 / max(weight, 0.000001)
    )


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


def _load_export_scrobbles(path: Path) -> list[blast_from_past.Scrobble]:
    """Load the existing export through its JSON/gzip fallback-aware loader."""
    by_date = blast_from_past.load_scrobbles_by_date(path)
    return [scrobble for bucket in by_date.values() for scrobble in bucket]


def load_recent_scrobbles(
    path: Path = DEFAULT_RECENT_PATH,
) -> list[blast_from_past.Scrobble]:
    """Load the append-only API delta accumulated after the export."""
    if not path.exists():
        return []

    scrobbles: list[blast_from_past.Scrobble] = []
    current_line = 0
    try:
        with path.open(encoding="utf-8") as delta_file:
            for line_number, line in enumerate(delta_file, start=1):
                current_line = line_number
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record is not an object")
                scrobbles.append(
                    blast_from_past.Scrobble(
                        artist=str(raw["artist"]),
                        track=str(raw["track"]),
                        album=str(raw.get("album") or ""),
                        timestamp_ms=int(raw["timestamp_ms"]),
                    )
                )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        detail = f" at line {current_line}" if current_line else ""
        raise FoundArtStateError(
            f"Found Art recent-scrobble state is invalid{detail}: {path}"
        ) from exc
    return scrobbles


def _scrobble_event_key(
    scrobble: blast_from_past.Scrobble,
) -> tuple[int, str, str, str]:
    """Return a stable identity for export/API overlap removal."""
    artist_key, track_key = canonical_track_key(scrobble.artist, scrobble.track)
    return (
        scrobble.timestamp_ms,
        artist_key,
        track_key,
        blast_from_past.normalize_name(scrobble.album),
    )


def append_recent_scrobbles(
    scrobbles: Iterable[blast_from_past.Scrobble],
    path: Path = DEFAULT_RECENT_PATH,
) -> None:
    """Append verified live scrobbles after a complete API delta fetch."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as delta_file:
            for scrobble in scrobbles:
                record = {
                    "artist": scrobble.artist,
                    "track": scrobble.track,
                    "album": scrobble.album,
                    "timestamp_ms": scrobble.timestamp_ms,
                }
                delta_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise FoundArtStateError(
            f"Could not update Found Art recent-scrobble state: {path}"
        ) from exc


def refresh_scrobble_history(
    lastfm: LastFmReader,
    *,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[blast_from_past.Scrobble], int]:
    """Merge the export, saved API delta, and newly fetched live scrobbles."""
    if progress_callback is not None:
        progress_callback("Loading the Last.fm export and live delta")
    export_scrobbles = _load_export_scrobbles(export_path)
    saved_recent = load_recent_scrobbles(recent_path)
    history = export_scrobbles + saved_recent
    if not history:
        raise FoundArtStateError("The Last.fm listening history is empty.")

    known_events = {_scrobble_event_key(scrobble) for scrobble in history}
    latest_timestamp_ms = max(scrobble.timestamp_ms for scrobble in history)
    fetched_at = (now or datetime.now(UTC)).astimezone(UTC)
    to_timestamp = int(fetched_at.timestamp())
    from_timestamp = latest_timestamp_ms // 1000
    if from_timestamp > to_timestamp:
        return history, 0

    if progress_callback is not None:
        progress_callback("Checking Last.fm for scrobbles newer than the export")
    live_tracks = lastfm.recent_tracks(
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )
    fresh: list[blast_from_past.Scrobble] = []
    for live_track in live_tracks:
        scrobble = blast_from_past.Scrobble(
            artist=live_track.artist,
            track=live_track.track,
            album=live_track.album,
            timestamp_ms=live_track.timestamp_seconds * 1000,
        )
        event_key = _scrobble_event_key(scrobble)
        if event_key in known_events:
            continue
        known_events.add(event_key)
        fresh.append(scrobble)

    fresh.sort(key=lambda scrobble: scrobble.timestamp_ms)
    if fresh:
        append_recent_scrobbles(fresh, recent_path)
        history.extend(fresh)
    return history, len(fresh)


def aggregate_track_history(
    scrobbles: Iterable[blast_from_past.Scrobble],
) -> tuple[TrackHistory, ...]:
    """Aggregate all-time, annual, and 90-day seed statistics."""
    materialized = list(scrobbles)
    if not materialized:
        return ()
    latest_timestamp_ms = max(scrobble.timestamp_ms for scrobble in materialized)
    recent_cutoff = latest_timestamp_ms - int(timedelta(days=90).total_seconds() * 1000)
    annual_cutoff = latest_timestamp_ms - int(
        timedelta(days=365).total_seconds() * 1000
    )
    total_counts: Counter[TrackKey] = Counter()
    recent_counts: Counter[TrackKey] = Counter()
    annual_counts: Counter[TrackKey] = Counter()
    display: dict[TrackKey, tuple[int, str, str]] = {}

    for scrobble in materialized:
        key = canonical_track_key(scrobble.artist, scrobble.track)
        if not all(key):
            continue
        total_counts[key] += 1
        if scrobble.timestamp_ms >= recent_cutoff:
            recent_counts[key] += 1
        if scrobble.timestamp_ms >= annual_cutoff:
            annual_counts[key] += 1
        current = display.get(key)
        if current is None or scrobble.timestamp_ms > current[0]:
            display[key] = (
                scrobble.timestamp_ms,
                scrobble.artist,
                scrobble.track,
            )

    return tuple(
        TrackHistory(
            artist=display[key][1],
            track=display[key][2],
            key=key,
            play_count=play_count,
            recent_play_count=recent_counts[key],
            annual_play_count=annual_counts[key],
            last_played_ms=display[key][0],
        )
        for key, play_count in total_counts.items()
    )


def select_seed_tracks(
    history: Iterable[TrackHistory],
    *,
    seed_count: int = DEFAULT_SEED_COUNT,
    week_start: date | None = None,
) -> tuple[FoundArtSeed, ...]:
    """Choose a weekly weighted mix of recent and established favorites."""
    if seed_count < 1:
        raise FoundArtConfigError("Seed count must be at least 1.")
    tracks = tuple(history)
    if not tracks:
        raise FoundArtStateError("No tracks are available for recommendation seeds.")
    active_week = week_start or listening_week_start()

    group_specs: tuple[
        tuple[
            Literal["recent", "annual", "overall"],
            str,
            float,
        ],
        ...,
    ] = (
        ("recent", "recent_play_count", 1.25),
        ("annual", "annual_play_count", 1.10),
        ("overall", "play_count", 1.00),
    )
    base_quota, remainder = divmod(seed_count, len(group_specs))
    quotas = [
        base_quota + (1 if index < remainder else 0)
        for index in range(len(group_specs))
    ]
    selected: list[FoundArtSeed] = []
    used_keys: set[TrackKey] = set()
    artist_counts: Counter[str] = Counter()

    for quota, (source, metric_name, base_weight) in zip(
        quotas,
        group_specs,
        strict=True,
    ):
        if quota == 0:
            continue
        popularity_pool = sorted(
            (
                track
                for track in tracks
                if getattr(track, metric_name) > 0 and track.key not in used_keys
            ),
            key=lambda track: (
                -int(getattr(track, metric_name)),
                -track.play_count,
                -track.last_played_ms,
                track.key,
            ),
        )[: quota * WEEKLY_SEED_POOL_MULTIPLIER]
        weekly_pool = sorted(
            (
                (
                    _weekly_weighted_rank(
                        active_week,
                        f"seed:{source}",
                        track.key,
                        math.log1p(int(getattr(track, metric_name))),
                    ),
                    track,
                )
                for track in popularity_pool
            ),
            key=lambda item: (
                -item[0],
                -int(getattr(item[1], metric_name)),
                item[1].key,
            ),
        )
        group_added = 0
        for weekly_rank, track in weekly_pool:
            artist_key = track.key[0]
            if artist_counts[artist_key] >= MAX_SEEDS_PER_ARTIST:
                continue
            source_count = int(getattr(track, metric_name))
            weight = base_weight * (1 + min(math.log1p(source_count), 6.0) / 10)
            selected.append(
                FoundArtSeed(
                    artist=track.artist,
                    track=track.track,
                    key=track.key,
                    source=source,
                    play_count=track.play_count,
                    source_play_count=source_count,
                    weight=weight,
                    weekly_rank=weekly_rank,
                )
            )
            used_keys.add(track.key)
            artist_counts[artist_key] += 1
            group_added += 1
            if group_added >= quota or len(selected) >= seed_count:
                break

    if len(selected) < seed_count:
        remaining = seed_count - len(selected)
        filler_pool = sorted(
            (track for track in tracks if track.key not in used_keys),
            key=lambda track: (
                -track.play_count,
                -track.last_played_ms,
                track.key,
            ),
        )[: max(1000, remaining * 100)]
        fillers = sorted(
            (
                (
                    _weekly_weighted_rank(
                        active_week,
                        "seed:overall:fallback",
                        track.key,
                        math.log1p(track.play_count),
                    ),
                    track,
                )
                for track in filler_pool
            ),
            key=lambda item: (-item[0], -item[1].play_count, item[1].key),
        )
        for weekly_rank, track in fillers:
            artist_key = track.key[0]
            if artist_counts[artist_key] >= MAX_SEEDS_PER_ARTIST:
                continue
            selected.append(
                FoundArtSeed(
                    artist=track.artist,
                    track=track.track,
                    key=track.key,
                    source="overall",
                    play_count=track.play_count,
                    source_play_count=track.play_count,
                    weight=1 + min(math.log1p(track.play_count), 6.0) / 10,
                    weekly_rank=weekly_rank,
                )
            )
            used_keys.add(track.key)
            artist_counts[artist_key] += 1
            if len(selected) >= seed_count:
                break
    if len(selected) < seed_count:
        raise FoundArtStateError(
            f"Only {len(selected)} sufficiently diverse seed tracks are "
            f"available; {seed_count} were requested."
        )
    return tuple(selected)


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
    log_path: Path = DEFAULT_LOG_PATH,
    week_start: date | None = None,
    candidate_pool_size: int = MIN_WEEKLY_CANDIDATE_POOL,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[FoundArtCandidate, ...]:
    """Combine seed neighborhoods and apply the weekly weighted ordering."""
    if candidate_pool_size < 1:
        raise FoundArtConfigError("Candidate pool size must be at least 1.")
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    active_week = week_start or listening_week_start(generated_at)
    cache = _load_similar_cache(cache_path)
    entries = cache["entries"]
    if not isinstance(entries, dict):
        raise AssertionError("validated cache entries changed type")
    excluded_keys = heard_keys | previously_added_track_keys(log_path)
    candidates: dict[TrackKey, _CandidateAccumulator] = {}

    for index, seed in enumerate(seeds, start=1):
        if progress_callback is not None:
            progress_callback(
                f"Getting Last.fm neighbors for seed {index}/{len(seeds)}"
            )
        key = _cache_key(seed)
        similar = _cached_similar_tracks(
            entries.get(key),
            week_start=active_week,
        )
        if similar is None:
            similar = lastfm.similar_tracks(
                seed.artist,
                seed.track,
                limit=DEFAULT_SIMILAR_TRACK_LIMIT,
            )
            entries[key] = {
                "artist": seed.artist,
                "track": seed.track,
                "fetched_at": generated_at.isoformat(),
                "tracks": [asdict(track) for track in similar],
            }
            _save_similar_cache(cache, cache_path)

        seed_label = f"{seed.artist} - {seed.track}"
        for neighbor in similar:
            candidate_key = canonical_track_key(neighbor.artist, neighbor.track)
            if not all(candidate_key) or candidate_key in excluded_keys:
                continue
            accumulator = candidates.setdefault(
                candidate_key,
                _CandidateAccumulator(
                    artist=neighbor.artist,
                    track=neighbor.track,
                    key=candidate_key,
                ),
            )
            accumulator.score += seed.weight * neighbor.match
            accumulator.best_match = max(accumulator.best_match, neighbor.match)
            if accumulator.supporting_seeds is None:
                raise AssertionError("candidate support set was not initialized")
            accumulator.supporting_seeds.add(seed_label)

    base_ranked = sorted(
        (
            FoundArtCandidate(
                artist=candidate.artist,
                track=candidate.track,
                key=candidate.key,
                score=candidate.score
                * (1 + 0.15 * (len(candidate.supporting_seeds or ()) - 1)),
                best_match=candidate.best_match,
                supporting_seeds=tuple(sorted(candidate.supporting_seeds or ())),
            )
            for candidate in candidates.values()
        ),
        key=lambda candidate: (
            -candidate.score,
            -len(candidate.supporting_seeds),
            -candidate.best_match,
            candidate.key,
        ),
    )
    weekly_pool = tuple(base_ranked[:candidate_pool_size])
    rotated = tuple(
        replace(
            candidate,
            base_rank=base_rank,
            weekly_rank=_weekly_weighted_rank(
                active_week,
                "candidate",
                candidate.key,
                candidate.score**2,
            ),
        )
        for base_rank, candidate in enumerate(weekly_pool, start=1)
    )
    return tuple(
        sorted(
            rotated,
            key=lambda candidate: (
                -candidate.weekly_rank,
                candidate.base_rank,
                candidate.key,
            ),
        )
    )


def _preferred_unliked_match(
    matches: tuple[blast_from_past.SpotifyTrackMatch, ...],
    liked_ids: set[str],
) -> blast_from_past.SpotifyTrackMatch | None:
    """Choose the strongest Spotify match after excluding liked tracks."""
    eligible = tuple(
        replace(match, liked=False)
        for match in matches
        if match.spotify_id not in liked_ids
    )
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda match: (
            match.track_similarity,
            match.popularity if match.popularity is not None else -1,
            -match.search_rank,
        ),
    )


def resolve_spotify_candidates(
    sp: Spotify,
    candidates: tuple[FoundArtCandidate, ...],
    playlist: blast_from_past.PlaylistState,
    *,
    count: int,
    dry_run: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[FoundArtResult, ...], tuple[blast_from_past.SpotifyTrackMatch, ...]]:
    """Search ranked candidates until enough unliked Spotify tracks resolve."""
    results: list[FoundArtResult] = []
    pending: list[blast_from_past.SpotifyTrackMatch] = []
    pending_ids: set[str] = set()
    selected_artist_keys: set[str] = set()
    maximum_candidates = min(
        len(candidates),
        max(count, count * SPOTIFY_CANDIDATE_MULTIPLIER),
    )

    for start in range(0, maximum_candidates, SPOTIFY_RESOLUTION_BATCH_SIZE):
        if len(pending) >= count:
            break
        candidate_batch = candidates[start : start + SPOTIFY_RESOLUTION_BATCH_SIZE]
        match_groups: list[tuple[blast_from_past.SpotifyTrackMatch, ...]] = []
        for offset, candidate in enumerate(candidate_batch, start=start + 1):
            if (
                candidate.key in playlist.track_keys
                or candidate.key[0] in selected_artist_keys
            ):
                match_groups.append(())
                continue
            if progress_callback is not None:
                progress_callback(
                    f"Searching Spotify candidate {offset}/{maximum_candidates}"
                )
            scrobble = blast_from_past.Scrobble(
                artist=candidate.artist,
                track=candidate.track,
                album="",
                timestamp_ms=0,
            )
            match_groups.append(blast_from_past.search_spotify_matches(sp, scrobble))

        if progress_callback is not None:
            progress_callback("Checking candidates against Spotify Liked Songs")
        liked_ids = blast_from_past.liked_spotify_track_ids(sp, match_groups)
        for candidate, matches in zip(candidate_batch, match_groups, strict=True):
            artist_key = candidate.key[0]
            if artist_key in selected_artist_keys:
                match = None
                action: FoundArtAction = "artist already selected"
            elif candidate.key in playlist.track_keys:
                match = None
                action = "already present"
            else:
                liked_matches = tuple(
                    replace(item, liked=True)
                    for item in matches
                    if item.spotify_id in liked_ids
                )
                if liked_matches:
                    match = max(
                        liked_matches,
                        key=lambda item: (
                            item.track_similarity,
                            item.popularity if item.popularity is not None else -1,
                            -item.search_rank,
                        ),
                    )
                    action = "liked"
                else:
                    match = _preferred_unliked_match(matches, liked_ids)
                    if match is None:
                        action = "no Spotify match"
                    elif match.spotify_id in playlist.track_ids:
                        action = "already present"
                    elif match.spotify_id in pending_ids:
                        action = "duplicate"
                    elif len(pending) >= count:
                        break
                    else:
                        action = "would add" if dry_run else "added"
                        pending.append(match)
                        pending_ids.add(match.spotify_id)
                        selected_artist_keys.add(artist_key)
            results.append(
                FoundArtResult(
                    candidate=candidate,
                    match=match,
                    action=action,
                )
            )
    return tuple(results), tuple(pending)


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
    """Generate unheard recommendations and append their Spotify matches."""
    if count is not None and max_playlist_length is not None:
        raise FoundArtConfigError(
            "Use either count or maximum playlist length, not both."
        )
    if count is not None and count < 1:
        raise FoundArtConfigError("Count must be at least 1.")
    if max_playlist_length is not None and max_playlist_length < 1:
        raise FoundArtConfigError("Maximum playlist length must be at least 1.")
    if seed_count < 1:
        raise FoundArtConfigError("Seed count must be at least 1.")

    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    active_week = listening_week_start(generated_at)
    history_scrobbles, live_added = refresh_scrobble_history(
        lastfm,
        export_path=export_path,
        recent_path=recent_path,
        now=generated_at,
        progress_callback=progress_callback,
    )
    history = aggregate_track_history(history_scrobbles)

    if progress_callback is not None:
        progress_callback("Loading the Found Art Spotify playlist")
    playlist = blast_from_past.load_playlist_state(sp, playlist_id)
    requested_count = count if count is not None else DEFAULT_COUNT
    if max_playlist_length is not None:
        requested_count = max(0, max_playlist_length - playlist.total_items)

    if requested_count:
        seeds = select_seed_tracks(
            history,
            seed_count=seed_count,
            week_start=active_week,
        )
        heard_keys = {track.key for track in history}
        candidate_pool_size = max(
            MIN_WEEKLY_CANDIDATE_POOL,
            requested_count * WEEKLY_CANDIDATE_POOL_MULTIPLIER,
        )
        candidates = gather_candidates(
            lastfm,
            seeds,
            heard_keys,
            cache_path=cache_path,
            log_path=log_path,
            week_start=active_week,
            candidate_pool_size=candidate_pool_size,
            now=generated_at,
            progress_callback=progress_callback,
        )
        results, pending = resolve_spotify_candidates(
            sp,
            candidates,
            playlist,
            count=requested_count,
            dry_run=dry_run,
            progress_callback=progress_callback,
        )
    else:
        seeds = ()
        candidates = ()
        results, pending = (), ()

    if pending and not dry_run:
        if progress_callback is not None:
            progress_callback(f"Adding {len(pending)} tracks to Found Art")
        blast_from_past.add_spotify_matches(sp, playlist_id, list(pending))

    actual_additions = 0 if dry_run else len(pending)
    summary = FoundArtSummary(
        generated_at=generated_at,
        week_start=active_week,
        playlist_id=playlist_id,
        requested_count=requested_count,
        seed_count=len(seeds),
        history_tracks=len(history),
        history_scrobbles=len(history_scrobbles),
        live_scrobbles_added=live_added,
        candidate_count=len(candidates),
        playlist_length_before=playlist.total_items,
        playlist_length_after=playlist.total_items + actual_additions,
        dry_run=dry_run,
        seeds=seeds,
        results=results,
    )
    append_found_art_log(summary, log_path)
    return summary
