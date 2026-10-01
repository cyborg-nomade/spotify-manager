"""Fill and flush The Queue's artist-level discovery stage."""

from __future__ import annotations

import json
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import Protocol
from typing import cast

from spotipy import Spotify

from spotify_manager.application.queue_fill_values import FillAction as FillAction
from spotify_manager.application.queue_fill_values import FillResult as FillResult
from spotify_manager.application.queue_fill_values import FillSummary as FillSummary
from spotify_manager.application.queue_values import (
    QueueConfigError as QueueConfigError,
)
from spotify_manager.application.queue_values import QueueError as QueueError
from spotify_manager.application.queue_values import (
    QueueSpotifyError as QueueSpotifyError,
)
from spotify_manager.application.queue_values import QueueStateError as QueueStateError

# UFI
from spotify_manager.client.lastfm import LastFmSimilarArtist
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.domain.queue_values import ArtistHistory as ArtistHistory
from spotify_manager.domain.queue_values import (
    ArtistRecommendation as ArtistRecommendation,
)
from spotify_manager.domain.queue_values import ArtistSeed as ArtistSeed
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import release_check
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
    """Aggregate all-time, annual, and 90-day artist seed statistics.

    Args:
        scrobbles: Original plays in observation order.

    Returns:
        Original counts and display spelling in first-identity order.
    """
    from spotify_manager.domain.queue_history import aggregate_artists

    return aggregate_artists(scrobbles)


def select_seed_artists(
    history: Iterable[ArtistHistory],
    *,
    seed_count: int = DEFAULT_SEED_COUNT,
    week_start: date | None = None,
) -> tuple[ArtistSeed, ...]:
    """Choose a weekly mix of recent, annual, and established artists.

    Args:
        history: Original artist history facts.
        seed_count: Original requested number of weekly seeds.
        week_start: Optional original explicit listening week.

    Returns:
        Original ordered quota and fallback seeds.

    Raises:
        QueueConfigError: Original requested seed count is below one.
        QueueStateError: Original history contains too few artists.
    """
    from spotify_manager.application.queue_seeds import QueueSeeds

    return QueueSeeds(found_art.listening_week_start, SEED_POOL_MULTIPLIER).select(
        history,
        seed_count,
        week_start,
    )


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
    from spotify_manager.infrastructure.queue_neighborhoods import cached_artists

    return cached_artists(raw, week_start, found_art.listening_week_start)


def previously_added_artist_keys(path: Path = DEFAULT_LOG_PATH) -> set[str]:
    """Return Last.fm artist keys actually added by earlier fill runs.

    Args:
        path: Original append-only Queue audit location.

    Returns:
        Original stripped nonblank identities from actual additions.

    Raises:
        QueueStateError: The original log cannot be read or decoded.
    """
    if not path.exists():
        return set()
    from spotify_manager.infrastructure.queue_neighborhoods import added_artist_keys

    try:
        with path.open(encoding="utf-8") as source:
            return added_artist_keys(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueStateError(f"Queue log is invalid: {path}") from exc


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
    """Aggregate Last.fm artist neighborhoods into a weekly ordering.

    Args:
        lastfm: Caller-owned original Last.fm client.
        seeds: Original ordered weighted seed artists.
        heard_keys: Original heard artist identities.
        cache_path: Original neighborhood cache location.
        log_path: Original prior-addition audit location.
        week_start: Optional original effective listening week.
        candidate_pool_size: Original pool slice limit.
        now: Optional original timestamp.
        progress_callback: Optional original progress presenter.

    Returns:
        Original weekly ordering after accepted neighborhood checkpoints.

    Raises:
        QueueStateError: Original cache or audit data is unusable.
    """
    from spotify_manager.bootstrap.queue_recommendations import (
        gather_queue_recommendations,
    )

    return gather_queue_recommendations(
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

    return partial(_read_mapping_choice, reader, recommendation)


def _read_mapping_choice(
    reader: ArtistChoiceReader,
    recommendation: ArtistRecommendation,
    _artist: release_check.RankedArtist,
    choices: tuple[release_check.SpotifyArtistCandidate, ...],
) -> str:
    return reader(recommendation, choices)


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


def _fill_following(
    sp: Spotify,
    spotify_artist: release_check.SpotifyArtistCandidate,
    retry: RetryCall,
) -> bool:
    followed_response = retry(
        partial(sp.current_user_following_artists, [spotify_artist.spotify_id]),
        f"checking follow status for {spotify_artist.name}",
    )
    if not isinstance(followed_response, list) or not followed_response:
        raise QueueSpotifyError("Spotify returned invalid artist follow status.")
    return bool(followed_response[0])


def _fill_follow(
    sp: Spotify,
    spotify_artist: release_check.SpotifyArtistCandidate,
    retry: RetryCall,
) -> None:
    retry(
        partial(sp.user_follow_artists, [spotify_artist.spotify_id]),
        f"following {spotify_artist.name}",
    )


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
    """Add unheard Last.fm artist recommendations to The Queue.

    Args:
        sp: Caller-owned original Spotify client.
        lastfm: Caller-owned original Last.fm reader.
        playlists: Original parsed destination identities.
        choice_reader: Original optional mapping interaction.
        count: Original optional requested additions.
        max_playlist_length: Original optional maximum Queue length.
        seed_count: Original requested weekly seeds.
        dry_run: Original preview behavior.
        echo: Original text presenter.
        progress_callback: Original optional progress presenter.
        retry_call: Original optional retry boundary.
        export_path: Original history export location.
        recent_path: Original recent-history location.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        cache_path: Original neighborhood cache location.
        log_path: Original audit location.
        now: Original optional timestamp.

    Returns:
        Original complete ordered fill outcome.

    Raises:
        QueueConfigError: Original limits conflict or are invalid.
        QueueStateError: Original history, cache or state is unusable.
        QueueSpotifyError: Original follow or liked response is invalid.
    """
    from spotify_manager.application.queue_fill_values import QueueFillRequest
    from spotify_manager.bootstrap.queue_fill import fill_queue

    return fill_queue(
        sp,
        lastfm,
        playlists,
        choice_reader,
        QueueFillRequest(count, max_playlist_length, seed_count, dry_run),
        echo,
        progress_callback,
        retry_call,
        export_path,
        recent_path,
        state_path,
        state_service,
        cache_path,
        log_path,
        now,
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
