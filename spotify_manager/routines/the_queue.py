"""Fill and flush The Queue's artist-level discovery stage."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Literal
from typing import Protocol
from typing import cast

from spotipy import Spotify

# UFI
from spotify_manager.client.lastfm import LastFmSimilarArtist
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import release_check
from spotify_manager.routines.review_album_limits import AlbumArtist
from spotify_manager.routines.review_album_limits import record_followed_artist
from spotify_manager.routines.review_artists import add_playlist_item
from spotify_manager.routines.review_artists import remove_library_artists
from spotify_manager.routines.review_artists import remove_playlist_items


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "queue_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "queue_log.jsonl"
DEFAULT_CACHE_PATH = FILES_DIR / "queue_recommendation_cache.json"
DEFAULT_SCROBBLES_PATH = found_art.DEFAULT_SCROBBLES_PATH
DEFAULT_RECENT_PATH = found_art.DEFAULT_RECENT_PATH
DEFAULT_ARTISTS_PATH = FILES_DIR / "artists_total.json"
STATE_VERSION = 1
DAILY_ARTIST_LIMIT = 10
TOP_TRACK_LIMIT = 10
DEFAULT_COUNT = 20
DEFAULT_SEED_COUNT = 30
SIMILAR_ARTIST_LIMIT = 50
SEED_POOL_MULTIPLIER = 10
CANDIDATE_POOL_MULTIPLIER = 10
MIN_CANDIDATE_POOL = 100
CHOICE_SKIP = release_check.CHOICE_SKIP
CHOICE_QUIT = release_check.CHOICE_QUIT
CHOICE_SEARCH_PREFIX = release_check.CHOICE_SEARCH_PREFIX

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
ArtistChoiceReader = Callable[
    ["ArtistRecommendation", tuple[release_check.SpotifyArtistCandidate, ...]],
    str,
]


class QueueError(RuntimeError):
    """Base error for The Queue routines."""


class QueueConfigError(QueueError):
    """Raised when a required playlist or recommendation setting is absent."""


class QueueStateError(QueueError):
    """Raised when Queue state, cache, or audit data is malformed."""


class QueueSpotifyError(QueueError):
    """Raised when Spotify returns an incomplete response."""


class LastFmReader(found_art.LastFmReader, Protocol):
    """Last.fm methods used by artist recommendations and history refresh."""

    username: str

    def similar_artists(
        self,
        artist: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Return artists similar to a seed artist."""


@dataclass(frozen=True)
class QueuePlaylists:
    """Playlist ids involved in filling or promoting Queue artists."""

    queue: str
    queue_2: str
    new_kids: str
    queue_3: str
    unlucky_ones: str

    @classmethod
    def from_references(
        cls,
        queue: str | None,
        queue_2: str | None,
        new_kids: str | None,
        queue_3: str | None,
        unlucky_ones: str | None,
    ) -> QueuePlaylists:
        """Parse all Queue-stage playlist references."""
        values = (
            (queue, "THE_QUEUE_PLAYLIST"),
            (queue_2, "THE_QUEUE_2_PLAYLIST"),
            (new_kids, "NEW_KIDS_ON_THE_BLOCK_PLAYLIST"),
            (queue_3, "THE_QUEUE_3_PLAYLIST"),
            (unlucky_ones, "UNLUCKY_ONES_PLAYLIST"),
        )
        try:
            parsed = tuple(
                new_wine.parse_playlist_id(value, setting) for value, setting in values
            )
        except new_wine.NewWineConfigError as exc:
            raise QueueConfigError(str(exc)) from exc
        return cls(*parsed)


@dataclass(frozen=True)
class ArtistHistory:
    """Aggregated Last.fm listening history for one artist."""

    artist: str
    key: str
    play_count: int
    recent_play_count: int
    annual_play_count: int
    last_played_ms: int


@dataclass(frozen=True)
class ArtistSeed:
    """One history artist used for Last.fm neighbor discovery."""

    artist: str
    key: str
    source: Literal["recent", "annual", "overall"]
    play_count: int
    source_play_count: int
    weight: float
    weekly_rank: float


@dataclass(frozen=True)
class ArtistRecommendation:
    """One unheard artist aggregated from Last.fm seed neighborhoods."""

    artist: str
    key: str
    score: float
    best_match: float
    supporting_seeds: tuple[str, ...]
    base_rank: int = 0
    weekly_rank: float = 1.0


@dataclass
class _ArtistAccumulator:
    """Mutable candidate score while seed neighborhoods are combined."""

    artist: str
    key: str
    score: float = 0.0
    best_match: float = 0.0
    supporting_seeds: set[str] | None = None

    def __post_init__(self) -> None:
        if self.supporting_seeds is None:
            self.supporting_seeds = set()


FillAction = Literal[
    "added",
    "would add",
    "already represented",
    "no Spotify match",
    "no unliked top track",
    "skipped",
]


@dataclass(frozen=True)
class FillResult:
    """Spotify resolution outcome for one Last.fm artist candidate."""

    recommendation: ArtistRecommendation
    spotify_artist: release_check.SpotifyArtistCandidate | None
    track: new_kids.CatalogTrack | None
    action: FillAction
    followed: bool = False


@dataclass(frozen=True)
class FillSummary:
    """Outcome of one Last.fm-driven Queue fill."""

    week_start: date
    requested_count: int
    history_artists: int
    history_scrobbles: int
    live_scrobbles_added: int
    seed_count: int
    candidate_count: int
    playlist_length_before: int
    playlist_length_after: int
    paused: bool
    dry_run: bool
    results: tuple[FillResult, ...]

    @property
    def selected(self) -> int:
        """Return actual or proposed Queue additions."""
        return sum(result.action in {"added", "would add"} for result in self.results)


FlushAction = Literal["advance", "promote", "unlucky", "unfollow", "blocked"]


@dataclass(frozen=True)
class FlushResult:
    """One Queue artist's snapshotted live decision."""

    artist: str
    source_track: str
    action: FlushAction
    top_tracks: int
    top_liked_tracks: int
    total_liked_tracks: int
    target_track: str | None = None
    target_release: str | None = None
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one restart-safe Queue flush."""

    run_id: str
    playlist_length_before: int
    playlist_length_after: int
    total: int
    processed: int
    resumed: bool
    dry_run: bool
    results: tuple[FlushResult, ...]


def _default_state() -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "artist_mappings": {},
        "active_flush": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load versioned Queue state without masking corruption."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueStateError(f"Queue state is invalid: {path}") from exc
    try:
        return validate_state(raw)
    except QueueStateError as exc:
        raise QueueStateError(f"Queue state is invalid: {path}") from exc


def validate_state(raw: object) -> dict[str, object]:
    """Validate The Queue namespace independently of storage."""
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("artist_mappings"), dict)
        or (
            raw.get("active_flush") is not None
            and not isinstance(raw.get("active_flush"), dict)
        )
    ):
        raise QueueStateError("Queue state is invalid.")
    return raw


def save_state(state: dict[str, object], path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically persist Queue state."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise QueueStateError(f"Could not save Queue state: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="queue",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def append_event(path: Path, event: str, **details: object) -> None:
    """Append one timestamped Queue audit event."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "event": event,
        **details,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise QueueStateError(f"Could not write Queue log: {path}") from exc


def canonical_artist_key(name: str) -> str:
    """Return the accent- and punctuation-tolerant Last.fm artist key."""
    return blast_from_past.normalize_name(name)


def aggregate_artist_history(
    scrobbles: Iterable[blast_from_past.Scrobble],
) -> tuple[ArtistHistory, ...]:
    """Aggregate all-time, annual, and 90-day artist seed statistics."""
    materialized = list(scrobbles)
    if not materialized:
        return ()
    latest = max(scrobble.timestamp_ms for scrobble in materialized)
    recent_cutoff = latest - int(timedelta(days=90).total_seconds() * 1000)
    annual_cutoff = latest - int(timedelta(days=365).total_seconds() * 1000)
    total: Counter[str] = Counter()
    recent: Counter[str] = Counter()
    annual: Counter[str] = Counter()
    display: dict[str, tuple[int, str]] = {}
    for scrobble in materialized:
        key = canonical_artist_key(scrobble.artist)
        if not key:
            continue
        total[key] += 1
        if scrobble.timestamp_ms >= recent_cutoff:
            recent[key] += 1
        if scrobble.timestamp_ms >= annual_cutoff:
            annual[key] += 1
        previous = display.get(key)
        if previous is None or scrobble.timestamp_ms > previous[0]:
            display[key] = (scrobble.timestamp_ms, scrobble.artist)
    return tuple(
        ArtistHistory(
            artist=display[key][1],
            key=key,
            play_count=count,
            recent_play_count=recent[key],
            annual_play_count=annual[key],
            last_played_ms=display[key][0],
        )
        for key, count in total.items()
    )


def select_seed_artists(
    history: Iterable[ArtistHistory],
    *,
    seed_count: int = DEFAULT_SEED_COUNT,
    week_start: date | None = None,
) -> tuple[ArtistSeed, ...]:
    """Choose a weekly mix of recent, annual, and established artists."""
    if seed_count < 1:
        raise QueueConfigError("Seed count must be at least 1.")
    artists = tuple(history)
    if len(artists) < seed_count:
        raise QueueStateError(
            f"Only {len(artists)} seed artists are available; {seed_count} requested."
        )
    active_week = week_start or found_art.listening_week_start()
    specs: tuple[tuple[Literal["recent", "annual", "overall"], str, float], ...] = (
        ("recent", "recent_play_count", 1.25),
        ("annual", "annual_play_count", 1.10),
        ("overall", "play_count", 1.00),
    )
    base, remainder = divmod(seed_count, len(specs))
    selected: list[ArtistSeed] = []
    used: set[str] = set()
    for index, (source, metric, base_weight) in enumerate(specs):
        quota = base + (1 if index < remainder else 0)
        pool = sorted(
            (
                artist
                for artist in artists
                if artist.key not in used and int(getattr(artist, metric)) > 0
            ),
            key=lambda artist: (
                -int(getattr(artist, metric)),
                -artist.play_count,
                -artist.last_played_ms,
                artist.key,
            ),
        )[: max(quota, quota * SEED_POOL_MULTIPLIER)]
        ranked = sorted(
            (
                (
                    found_art.weekly_weighted_rank(
                        active_week,
                        f"queue-seed:{source}",
                        (artist.key, ""),
                        math.log1p(int(getattr(artist, metric))),
                    ),
                    artist,
                )
                for artist in pool
            ),
            key=lambda item: (-item[0], item[1].key),
        )
        for weekly_rank, artist in ranked[:quota]:
            source_count = int(getattr(artist, metric))
            selected.append(
                ArtistSeed(
                    artist=artist.artist,
                    key=artist.key,
                    source=source,
                    play_count=artist.play_count,
                    source_play_count=source_count,
                    weight=base_weight * (1 + min(math.log1p(source_count), 6.0) / 10),
                    weekly_rank=weekly_rank,
                )
            )
            used.add(artist.key)
    if len(selected) < seed_count:
        fillers = sorted(
            (artist for artist in artists if artist.key not in used),
            key=lambda artist: (
                -found_art.weekly_weighted_rank(
                    active_week,
                    "queue-seed:fallback",
                    (artist.key, ""),
                    math.log1p(artist.play_count),
                ),
                artist.key,
            ),
        )
        for artist in fillers[: seed_count - len(selected)]:
            selected.append(
                ArtistSeed(
                    artist=artist.artist,
                    key=artist.key,
                    source="overall",
                    play_count=artist.play_count,
                    source_play_count=artist.play_count,
                    weight=1 + min(math.log1p(artist.play_count), 6.0) / 10,
                    weekly_rank=found_art.weekly_weighted_rank(
                        active_week,
                        "queue-seed:fallback",
                        (artist.key, ""),
                        math.log1p(artist.play_count),
                    ),
                )
            )
    return tuple(selected)


def _load_cache(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueStateError(f"Queue recommendation cache is invalid: {path}") from exc
    if (
        not isinstance(raw, dict)
        or raw.get("version") != 1
        or not isinstance(raw.get("entries"), dict)
    ):
        raise QueueStateError(f"Queue recommendation cache is invalid: {path}")
    return raw


def _save_cache(cache: dict[str, object], path: Path) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise QueueStateError(f"Could not save Queue cache: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _cached_similar_artists(
    raw: object,
    week_start: date,
) -> tuple[LastFmSimilarArtist, ...] | None:
    if not isinstance(raw, dict):
        return None
    try:
        fetched_at = datetime.fromisoformat(str(raw["fetched_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        if found_art.listening_week_start(fetched_at) != week_start:
            return None
        values = raw["artists"]
        if not isinstance(values, list):
            return None
        return tuple(
            LastFmSimilarArtist(
                artist=str(value["artist"]),
                match=float(value["match"]),
            )
            for value in values
            if isinstance(value, dict)
        )
    except KeyError, TypeError, ValueError:
        return None


def previously_added_artist_keys(path: Path = DEFAULT_LOG_PATH) -> set[str]:
    """Return Last.fm artist keys actually added by earlier fill runs."""
    if not path.exists():
        return set()
    keys: set[str] = set()
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                raw = json.loads(line)
                if isinstance(raw, dict) and raw.get("event") == "artist_added":
                    key = str(raw.get("lastfm_artist_key") or "").strip()
                    if key:
                        keys.add(key)
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueStateError(f"Queue log is invalid: {path}") from exc
    return keys


def gather_artist_recommendations(
    lastfm: LastFmReader,
    seeds: tuple[ArtistSeed, ...],
    heard_keys: set[str],
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    week_start: date | None = None,
    candidate_pool_size: int = MIN_CANDIDATE_POOL,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[ArtistRecommendation, ...]:
    """Aggregate Last.fm artist neighborhoods into a weekly ordering."""
    active_now = (now or datetime.now(UTC)).astimezone(UTC)
    active_week = week_start or found_art.listening_week_start(active_now)
    cache = _load_cache(cache_path)
    entries = cache["entries"]
    assert isinstance(entries, dict)
    excluded = heard_keys | previously_added_artist_keys(log_path)
    candidates: dict[str, _ArtistAccumulator] = {}
    for index, seed in enumerate(seeds, start=1):
        if progress_callback is not None:
            progress_callback(
                index - 1, len(seeds), f"Last.fm neighbors: {seed.artist}"
            )
        similar = _cached_similar_artists(entries.get(seed.key), active_week)
        if similar is None:
            similar = lastfm.similar_artists(seed.artist, limit=SIMILAR_ARTIST_LIMIT)
            entries[seed.key] = {
                "artist": seed.artist,
                "fetched_at": active_now.isoformat(),
                "artists": [asdict(candidate) for candidate in similar],
            }
            _save_cache(cache, cache_path)
        for neighbor in similar:
            key = canonical_artist_key(neighbor.artist)
            if not key or key in excluded:
                continue
            candidate = candidates.setdefault(
                key,
                _ArtistAccumulator(artist=neighbor.artist, key=key),
            )
            candidate.score += seed.weight * neighbor.match
            candidate.best_match = max(candidate.best_match, neighbor.match)
            assert candidate.supporting_seeds is not None
            candidate.supporting_seeds.add(seed.artist)
    base_ranked = sorted(
        (
            ArtistRecommendation(
                artist=candidate.artist,
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
    )[:candidate_pool_size]
    rotated = tuple(
        replace(
            candidate,
            base_rank=rank,
            weekly_rank=found_art.weekly_weighted_rank(
                active_week,
                "queue-candidate",
                (candidate.key, ""),
                candidate.score**2,
            ),
        )
        for rank, candidate in enumerate(base_ranked, start=1)
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


def _mapped_artist(raw: object) -> release_check.SpotifyArtistCandidate | None:
    if not isinstance(raw, dict):
        return None
    try:
        return release_check.SpotifyArtistCandidate(**raw)
    except TypeError:
        return None


def _mapping_choice_reader(
    reader: ArtistChoiceReader | None,
    recommendation: ArtistRecommendation,
) -> release_check.ArtistChoiceReader | None:
    """Adapt the Queue recommendation prompt to release-check mapping logic."""
    if reader is None:
        return None

    def read_choice(
        _artist: release_check.RankedArtist,
        choices: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        return reader(recommendation, choices)

    return read_choice


def _playlist_artist_ids(
    sp: Spotify,
    playlist_ids: Iterable[str],
    retry_call: RetryCall,
) -> set[str]:
    represented: set[str] = set()
    for playlist_id in playlist_ids:
        represented.update(
            track.primary_artist_id
            for track in new_wine.load_playlist_tracks(sp, playlist_id, retry_call)
        )
    return represented


def _liked_statuses(
    sp: Spotify,
    tracks: Iterable[new_kids.CatalogTrack],
    retry_call: RetryCall,
) -> dict[str, bool]:
    materialized = tuple(tracks)
    if not materialized:
        return {}
    response = retry_call(
        partial(
            sp.current_user_saved_tracks_contains,
            [track.spotify_id for track in materialized],
        ),
        f"checking {len(materialized)} top tracks in Liked Songs",
    )
    if not isinstance(response, list) or len(response) != len(materialized):
        raise QueueSpotifyError("Spotify returned invalid Liked Songs statuses.")
    return {
        track.spotify_id: bool(liked)
        for track, liked in zip(materialized, response, strict=True)
    }


def _persist_followed_artist(
    candidate: release_check.SpotifyArtistCandidate,
    echo: Echo,
) -> None:
    persisted = record_followed_artist(
        AlbumArtist(spotify_id=candidate.spotify_id, name=candidate.name)
    )
    if persisted.total_artists_updated:
        echo(f"Recorded artist in artists_total.json: {candidate.name}")
    if persisted.stats_history_updated:
        echo("Updated stats_history.json.")


def fill_queue_from_lastfm(
    sp: Spotify,
    lastfm: LastFmReader,
    playlists: QueuePlaylists,
    choice_reader: ArtistChoiceReader | None,
    *,
    count: int | None = DEFAULT_COUNT,
    max_playlist_length: int | None = None,
    seed_count: int = DEFAULT_SEED_COUNT,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> FillSummary:
    """Add unheard Last.fm artist recommendations to The Queue."""
    if count is not None and max_playlist_length is not None:
        raise QueueConfigError("Use either count or maximum playlist length, not both.")
    if count is not None and count < 1:
        raise QueueConfigError("Count must be at least 1.")
    if max_playlist_length is not None and max_playlist_length < 1:
        raise QueueConfigError("Maximum playlist length must be at least 1.")
    retry = retry_call or (lambda operation, _description: operation())
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    week_start = found_art.listening_week_start(generated_at)
    try:
        scrobbles, live_added = found_art.refresh_scrobble_history(
            lastfm,
            export_path=export_path,
            recent_path=recent_path,
            dry_run=dry_run,
            now=generated_at,
            progress_callback=(
                (lambda status: progress_callback(0, 0, status))
                if progress_callback is not None
                else None
            ),
        )
    except found_art.FoundArtError as exc:
        raise QueueStateError(str(exc)) from exc
    history = aggregate_artist_history(scrobbles)
    queue_tracks = new_wine.load_playlist_tracks(sp, playlists.queue, retry)
    before = len(queue_tracks)
    requested = count if count is not None else DEFAULT_COUNT
    if max_playlist_length is not None:
        requested = max(0, max_playlist_length - before)
    if not requested:
        return FillSummary(
            week_start=week_start,
            requested_count=0,
            history_artists=len(history),
            history_scrobbles=len(scrobbles),
            live_scrobbles_added=live_added,
            seed_count=0,
            candidate_count=0,
            playlist_length_before=before,
            playlist_length_after=before,
            paused=False,
            dry_run=dry_run,
            results=(),
        )
    seeds = select_seed_artists(history, seed_count=seed_count, week_start=week_start)
    candidates = gather_artist_recommendations(
        lastfm,
        seeds,
        {artist.key for artist in history},
        cache_path=cache_path,
        log_path=log_path,
        week_start=week_start,
        candidate_pool_size=max(
            MIN_CANDIDATE_POOL, requested * CANDIDATE_POOL_MULTIPLIER
        ),
        now=generated_at,
        progress_callback=progress_callback,
    )
    represented = _playlist_artist_ids(
        sp,
        (playlists.queue, playlists.queue_2, playlists.new_kids, playlists.queue_3),
        retry,
    )
    state_access = _state_access(state_path, state_service)
    state = state_access.load()
    mappings = state["artist_mappings"]
    assert isinstance(mappings, dict)
    results: list[FillResult] = []
    selected = 0
    paused = False
    maximum = min(
        len(candidates), max(requested, requested * CANDIDATE_POOL_MULTIPLIER)
    )
    for index, recommendation in enumerate(candidates[:maximum], start=1):
        if selected >= requested:
            break
        if progress_callback is not None:
            progress_callback(index - 1, maximum, f"Resolving {recommendation.artist}")
        spotify_artist = _mapped_artist(mappings.get(recommendation.key))
        if spotify_artist is None:
            ranked = release_check.RankedArtist(
                key=recommendation.key,
                name=recommendation.artist,
                scrobbles=0,
                rank=recommendation.base_rank,
            )
            resolved = release_check.resolve_spotify_artist(
                sp,
                ranked,
                _mapping_choice_reader(choice_reader, recommendation),
                retry,
            )
            if resolved == CHOICE_QUIT:
                paused = True
                break
            if resolved == CHOICE_SKIP:
                result = FillResult(recommendation, None, None, "skipped")
                results.append(result)
                append_event(
                    log_path, "fill_candidate", result=asdict(result), dry_run=dry_run
                )
                continue
            if not isinstance(resolved, release_check.SpotifyArtistCandidate):
                result = FillResult(recommendation, None, None, "no Spotify match")
                results.append(result)
                append_event(
                    log_path, "fill_candidate", result=asdict(result), dry_run=dry_run
                )
                continue
            spotify_artist = resolved
            mappings[recommendation.key] = asdict(spotify_artist)
            state_access.save(state)
        if spotify_artist.spotify_id in represented:
            result = FillResult(
                recommendation,
                spotify_artist,
                None,
                "already represented",
            )
            results.append(result)
            append_event(
                log_path, "fill_candidate", result=asdict(result), dry_run=dry_run
            )
            continue
        _album_ranks, top_tracks = new_kids.load_top_track_data(
            sp, spotify_artist.spotify_id, retry
        )
        liked = _liked_statuses(sp, top_tracks[:TOP_TRACK_LIMIT], retry)
        target = next(
            (
                track
                for track in top_tracks[:TOP_TRACK_LIMIT]
                if not liked.get(track.spotify_id, False)
            ),
            None,
        )
        if target is None:
            result = FillResult(
                recommendation,
                spotify_artist,
                None,
                "no unliked top track",
            )
            results.append(result)
            append_event(
                log_path, "fill_candidate", result=asdict(result), dry_run=dry_run
            )
            continue
        followed_response = retry(
            partial(sp.current_user_following_artists, [spotify_artist.spotify_id]),
            f"checking follow status for {spotify_artist.name}",
        )
        if not isinstance(followed_response, list) or not followed_response:
            raise QueueSpotifyError("Spotify returned invalid artist follow status.")
        followed_now = not bool(followed_response[0])
        if not dry_run:
            if followed_now:
                retry(
                    partial(sp.user_follow_artists, [spotify_artist.spotify_id]),
                    f"following {spotify_artist.name}",
                )
                _persist_followed_artist(spotify_artist, echo)
            retry(
                partial(add_playlist_item, sp, playlists.queue, target.uri),
                f"adding {spotify_artist.name} to The Queue",
            )
        action: FillAction = "would add" if dry_run else "added"
        result = FillResult(
            recommendation,
            spotify_artist,
            target,
            action,
            followed=followed_now,
        )
        results.append(result)
        represented.add(spotify_artist.spotify_id)
        selected += 1
        append_event(
            log_path,
            "artist_added" if not dry_run else "fill_candidate",
            lastfm_artist_key=recommendation.key,
            result=asdict(result),
            dry_run=dry_run,
        )
        echo(
            f"{'Would add' if dry_run else 'Added'} {spotify_artist.name} - "
            f"{target.name} to The Queue."
        )
    after = before if dry_run else before + selected
    return FillSummary(
        week_start=week_start,
        requested_count=requested,
        history_artists=len(history),
        history_scrobbles=len(scrobbles),
        live_scrobbles_added=live_added,
        seed_count=len(seeds),
        candidate_count=len(candidates),
        playlist_length_before=before,
        playlist_length_after=after,
        paused=paused,
        dry_run=dry_run,
        results=tuple(results),
    )


def _playlist_track_from_record(raw: object) -> new_wine.PlaylistTrack:
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise QueueStateError("Queue run contains an invalid playlist track.")
    try:
        return new_wine.PlaylistTrack(
            spotify_id=str(raw["spotify_id"]),
            uri=str(raw["uri"]),
            name=str(raw["name"]),
            primary_artist_id=str(raw["primary_artist_id"]),
            primary_artist_name=str(raw["primary_artist_name"]),
            release=new_wine.ReleaseCandidate(**raw["release"]),
        )
    except (KeyError, TypeError) as exc:
        raise QueueStateError("Queue run contains an invalid playlist track.") from exc


def _catalog_track_from_record(raw: object) -> new_kids.CatalogTrack | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QueueStateError("Queue plan contains an invalid target track.")
    try:
        return new_kids.CatalogTrack(**raw)
    except TypeError as exc:
        raise QueueStateError("Queue plan contains an invalid target track.") from exc


def _new_flush_run(
    playlist_id: str,
    tracks: tuple[new_wine.PlaylistTrack, ...],
) -> dict[str, object]:
    selected: list[new_wine.PlaylistTrack] = []
    seen: set[str] = set()
    for track in tracks:
        if track.primary_artist_id in seen:
            continue
        seen.add(track.primary_artist_id)
        selected.append(track)
        if len(selected) == DAILY_ARTIST_LIMIT:
            break
    return {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "started_at": datetime.now(UTC).isoformat(),
        "entries": [
            {"source": asdict(track), "status": "pending", "plan": None}
            for track in selected
        ],
    }


def _promotion_track(
    sp: Spotify,
    artist_id: str,
    catalog: tuple[new_kids.RankedRelease, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[new_kids.CatalogTrack, ...]],
) -> tuple[new_kids.CatalogTrack | None, str | None]:
    for release in catalog:
        if release.tier != 0:
            continue
        tracks = track_cache.get(release.spotify_id)
        if tracks is None:
            tracks = new_kids.load_release_tracks(sp, release, retry_call)
            track_cache[release.spotify_id] = tracks
        target = next(
            (track for track in tracks if track.primary_artist_id == artist_id),
            None,
        )
        if target is not None:
            return target, release.name
    return None, None


def _plan_flush_entry(
    sp: Spotify,
    source: new_wine.PlaylistTrack,
    source_uris: list[str],
    retry_call: RetryCall,
) -> dict[str, object]:
    _album_ranks, top_tracks = new_kids.load_top_track_data(
        sp, source.primary_artist_id, retry_call
    )
    top_tracks = top_tracks[:TOP_TRACK_LIMIT]
    top_liked = _liked_statuses(sp, top_tracks, retry_call)
    catalog = new_kids.load_ranked_catalog(sp, source.primary_artist_id, retry_call)
    track_cache: dict[str, tuple[new_kids.CatalogTrack, ...]] = {}
    assessment = new_kids.assess_artist(
        sp,
        source.primary_artist_id,
        catalog,
        retry_call,
        track_cache,
    )
    source_index = next(
        (
            index
            for index, track in enumerate(top_tracks)
            if track.spotify_id == source.spotify_id
        ),
        -1,
    )
    next_unliked = next(
        (
            track
            for track in top_tracks[source_index + 1 :]
            if not top_liked.get(track.spotify_id, False)
        ),
        None,
    )
    liked_top_count = sum(top_liked.values())
    promote_reason: str | None = None
    if assessment.liked_tracks >= 6:
        promote_reason = "six liked tracks in the primary-artist catalog"
    elif next_unliked is None and liked_top_count >= 5:
        promote_reason = "five liked tracks in the Spotify top ten"
    if promote_reason is not None:
        target, release_name = _promotion_track(
            sp,
            source.primary_artist_id,
            catalog,
            retry_call,
            track_cache,
        )
        action: FlushAction = "promote" if target is not None else "blocked"
        reason = (
            promote_reason
            if target is not None
            else f"{promote_reason}, but no eligible top album marker was found"
        )
    elif next_unliked is not None:
        target = next_unliked
        release_name = None
        action = "advance"
        reason = "next unliked primary-artist track in the Spotify top ten"
    elif assessment.top_liked_track is not None:
        target = assessment.top_liked_track
        release_name = None
        action = "unlucky"
        reason = "top-ten window ended below the promotion threshold"
    else:
        target = None
        release_name = None
        action = "unfollow"
        reason = "top-ten window ended without any liked tracks"
    return {
        "action": action,
        "source_uris": source_uris,
        "target": asdict(target) if target is not None else None,
        "target_release": release_name,
        "top_tracks": len(top_tracks),
        "top_liked_tracks": liked_top_count,
        "total_liked_tracks": assessment.liked_tracks,
        "reason": reason,
    }


def _flush_result(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    dry_run: bool,
) -> FlushResult:
    target = _catalog_track_from_record(plan.get("target"))
    integer_fields: dict[str, int] = {}
    for key in ("top_tracks", "top_liked_tracks", "total_liked_tracks"):
        value = plan.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise QueueStateError(f"Queue plan has invalid {key}.")
        integer_fields[key] = value
    return FlushResult(
        artist=source.primary_artist_name,
        source_track=source.name,
        action=cast(FlushAction, str(plan["action"])),
        top_tracks=integer_fields["top_tracks"],
        top_liked_tracks=integer_fields["top_liked_tracks"],
        total_liked_tracks=integer_fields["total_liked_tracks"],
        target_track=target.name if target is not None else None,
        target_release=(
            str(plan["target_release"]) if plan.get("target_release") else None
        ),
        reason=str(plan.get("reason") or "") or None,
        dry_run=dry_run,
    )


def flush_queue(
    sp: Spotify,
    playlists: QueuePlaylists,
    *,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
) -> FlushSummary:
    """Advance the first ten Queue artists through their unliked top tracks."""
    retry = retry_call or (lambda operation, _description: operation())
    state_access = _state_access(state_path, state_service)
    state = _default_state() if dry_run else state_access.load()
    active = state.get("active_flush")
    resumed = bool(
        not dry_run
        and isinstance(active, dict)
        and active.get("playlist_id") == playlists.queue
    )
    live_tracks = list(new_wine.load_playlist_tracks(sp, playlists.queue, retry))
    length_before = len(live_tracks)
    if resumed:
        run = active
        assert isinstance(run, dict)
    else:
        run = _new_flush_run(playlists.queue, tuple(live_tracks))
        if not dry_run:
            state["active_flush"] = run
            state_access.save(state)
    raw_entries = run.get("entries")
    if not isinstance(raw_entries, list):
        raise QueueStateError("Queue active flush has invalid entries.")
    live_ids = {track.spotify_id for track in live_tracks}
    live_uris = {track.uri for track in live_tracks}
    queue_2_artists = {
        track.primary_artist_id
        for track in new_wine.load_playlist_tracks(sp, playlists.queue_2, retry)
    }
    unlucky_artists = {
        track.primary_artist_id
        for track in new_wine.load_playlist_tracks(sp, playlists.unlucky_ones, retry)
    }
    results: list[FlushResult] = []
    total = len(raw_entries)
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise QueueStateError("Queue active flush has an invalid entry.")
        if raw_entry.get("status") == "completed":
            continue
        source = _playlist_track_from_record(raw_entry.get("source"))
        if progress_callback is not None:
            progress_callback(
                index - 1, total, f"Planning {source.primary_artist_name}"
            )
        raw_plan = raw_entry.get("plan")
        plan = raw_plan if isinstance(raw_plan, dict) else None
        if plan is None:
            source_uris = [
                track.uri
                for track in live_tracks
                if track.primary_artist_id == source.primary_artist_id
            ] or [source.uri]
            plan = _plan_flush_entry(sp, source, source_uris, retry)
            raw_entry["plan"] = plan
            if not dry_run:
                state_access.save(state)
        action = str(plan.get("action") or "")
        target = _catalog_track_from_record(plan.get("target"))
        raw_source_uris = plan.get("source_uris")
        if not isinstance(raw_source_uris, list):
            raise QueueStateError("Queue plan has invalid source URIs.")
        source_uris = [str(uri) for uri in raw_source_uris]
        if action == "advance" and target is not None:
            if target.spotify_id not in live_ids and not dry_run:
                retry(
                    partial(add_playlist_item, sp, playlists.queue, target.uri),
                    f"adding the next Queue track for {source.primary_artist_name}",
                )
            live_ids.add(target.spotify_id)
            live_uris.add(target.uri)
            echo(
                f"{'Would advance' if dry_run else 'Advanced'} "
                f"{source.primary_artist_name} to {target.name}."
            )
        elif action == "promote" and target is not None:
            if source.primary_artist_id not in queue_2_artists:
                if not dry_run:
                    retry(
                        partial(add_playlist_item, sp, playlists.queue_2, target.uri),
                        f"promoting {source.primary_artist_name} to Queue 2",
                    )
                queue_2_artists.add(source.primary_artist_id)
            echo(
                f"{'Would promote' if dry_run else 'Promoted'} "
                f"{source.primary_artist_name} to Queue 2 with {target.name}."
            )
        elif action == "unlucky" and target is not None:
            if source.primary_artist_id not in unlucky_artists:
                if not dry_run:
                    retry(
                        partial(
                            add_playlist_item, sp, playlists.unlucky_ones, target.uri
                        ),
                        f"adding {source.primary_artist_name} to Unlucky Ones",
                    )
                unlucky_artists.add(source.primary_artist_id)
            echo(
                f"{'Would add' if dry_run else 'Added'} "
                f"{source.primary_artist_name} to Unlucky Ones with {target.name}."
            )
        if action in {"unlucky", "unfollow"}:
            followed = retry(
                partial(
                    sp.current_user_following_artists,
                    [source.primary_artist_id],
                ),
                f"checking follow status for {source.primary_artist_name}",
            )
            if not isinstance(followed, list) or not followed:
                raise QueueSpotifyError(
                    "Spotify returned invalid artist follow status."
                )
            if bool(followed[0]):
                if not dry_run:
                    retry(
                        partial(
                            remove_library_artists,
                            sp,
                            [f"spotify:artist:{source.primary_artist_id}"],
                        ),
                        f"unfollowing {source.primary_artist_name}",
                    )
                    new_kids.remove_local_artist(source.primary_artist_id, artists_path)
                echo(
                    f"{'Would unfollow' if dry_run else 'Unfollowed'} "
                    f"{source.primary_artist_name}."
                )
        if action != "blocked":
            removable = [
                uri
                for uri in source_uris
                if uri in live_uris
                and not (action == "advance" and target and uri == target.uri)
            ]
            if removable and not dry_run:
                retry(
                    partial(remove_playlist_items, sp, playlists.queue, removable),
                    "removing the previous Queue marker for "
                    f"{source.primary_artist_name}",
                )
            for uri in removable:
                live_uris.discard(uri)
                matching = next(
                    (track.spotify_id for track in live_tracks if track.uri == uri),
                    None,
                )
                if matching is not None:
                    live_ids.discard(matching)
        result = _flush_result(source, plan, dry_run)
        results.append(result)
        append_event(
            log_path,
            "flush_artist_completed",
            run_id=run.get("run_id"),
            artist_id=source.primary_artist_id,
            result=asdict(result),
        )
        if not dry_run:
            raw_entry["status"] = "completed"
            state_access.save(state)
        if progress_callback is not None:
            progress_callback(index, total, f"Completed {source.primary_artist_name}")
    if not dry_run:
        state["active_flush"] = None
        state_access.save(state)
    return FlushSummary(
        run_id=str(run.get("run_id") or "dry-run"),
        playlist_length_before=length_before,
        playlist_length_after=len(live_uris),
        total=total,
        processed=len(results),
        resumed=resumed,
        dry_run=dry_run,
        results=tuple(results),
    )
