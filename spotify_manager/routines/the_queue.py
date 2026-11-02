"""Fill and flush The Queue's artist-level discovery stage."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Protocol

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.runtime import ReviewProgress
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.ports.state import BlockingRoutineState
from spotify_manager.application.queue_artist_mapping import (
    QueueArtistChoice as ArtistChoiceReader,
)
from spotify_manager.application.queue_fill_values import FillAction as FillAction
from spotify_manager.application.queue_fill_values import FillResult as FillResult
from spotify_manager.application.queue_fill_values import FillSummary as FillSummary
from spotify_manager.application.queue_flush_values import FlushAction as FlushAction
from spotify_manager.application.queue_flush_values import FlushResult as FlushResult
from spotify_manager.application.queue_flush_values import FlushSummary as FlushSummary
from spotify_manager.application.queue_values import (
    QueueConfigError as QueueConfigError,
)
from spotify_manager.application.queue_values import QueueError as QueueError
from spotify_manager.application.queue_values import (
    QueueSpotifyError as QueueSpotifyError,
)
from spotify_manager.application.queue_values import QueueStateError as QueueStateError
from spotify_manager.client.lastfm import LastFmSimilarArtist
from spotify_manager.core.state.compat import StateLocation
from spotify_manager.core.state.compat import routine_state_from
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.domain.queue_values import ArtistHistory as ArtistHistory
from spotify_manager.domain.queue_values import (
    ArtistRecommendation as ArtistRecommendation,
)
from spotify_manager.domain.queue_values import ArtistSeed as ArtistSeed
from spotify_manager.infrastructure.async_state import AsyncRoutineState

# UFI
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.python_compat.history import (
    BlockingNeighborReader as LegacyNeighborReader,
)
from spotify_manager.infrastructure.python_compat.retry import (
    BlockingRetry as LegacyRetry,
)
from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar
from spotify_manager.infrastructure.routine_state_codecs import TheQueueStateCodec
from spotify_manager.interfaces.requests.queue_fill import QueueFillCallbacks
from spotify_manager.interfaces.requests.queue_fill import QueueFillOptions
from spotify_manager.interfaces.requests.queue_fill import QueueFillResources
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import release_check
from spotify_manager.routines.review_album_limits import (
    async_record_followed_artist as record_followed_artist,
)
from spotify_manager.routines.review_artists import (
    add_playlist_item as add_playlist_item,
)
from spotify_manager.routines.review_artists import (
    remove_library_artists as remove_library_artists,
)
from spotify_manager.routines.review_artists import (
    remove_playlist_items as remove_playlist_items,
)


type ProgressCallback = ReviewProgress


type Echo = Messages


type RetryCall = Retry


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


class LastFmReader(found_art.LastFmReader, Protocol):
    """Last.fm methods used by artist recommendations and history refresh."""

    @property
    def username(self) -> str:
        """Read the configured Last.fm account name.

        Returns:
            Original case-preserving account name.
        """
        ...

    async def similar_artists(
        self,
        artist: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Return artists similar to a seed artist.

        Args:
            artist: Original seed display spelling.
            limit: Original requested maximum neighbors.

        Returns:
            Original ordered Last.fm neighborhood.
        """


@dataclass(frozen=True)
class QueuePlaylists:
    """Playlist identities involved in filling or promoting Queue artists.

    Args:
        queue: Original discovery Queue identity.
        queue_2: Original promotion destination identity.
        new_kids: Original active-listening destination identity.
        queue_3: Original completed-artist destination identity.
        unlucky_ones: Original rejection destination identity.
    """

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
        """Parse all Queue-stage playlist references.

        Args:
            queue: Original discovery Queue reference.
            queue_2: Original promotion destination reference.
            new_kids: Original active-listening destination reference.
            queue_3: Original completed-artist destination reference.
            unlucky_ones: Original rejection destination reference.

        Returns:
            Original parsed Queue-stage identities.

        Raises:
            QueueConfigError: An original reference is missing or invalid.
        """
        values = (
            (queue, "THE_QUEUE_PLAYLIST"),
            (queue_2, "THE_QUEUE_2_PLAYLIST"),
            (new_kids, "NEW_KIDS_ON_THE_BLOCK_PLAYLIST"),
            (queue_3, "THE_QUEUE_3_PLAYLIST"),
            (unlucky_ones, "UNLUCKY_ONES_PLAYLIST"),
        )
        try:
            parsed = []
            for value, setting in values:
                parsed.append(new_wine.parse_playlist_id(value, setting))
        except new_wine.NewWineConfigError as exc:
            raise QueueConfigError(str(exc)) from exc
        return cls(*parsed)


def _default_state() -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "artist_mappings": {},
        "active_flush": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load versioned Queue state without masking corruption.

    Args:
        path: Original local Queue state location.

    Returns:
        Original validated state or the original missing-file default.

    Raises:
        QueueStateError: The original file cannot be read, decoded or validated.
    """
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
    """Validate The Queue namespace independently of storage.

    Args:
        raw: Original unchecked state document.

    Returns:
        Original caller-owned document without filtering unknown fields.

    Raises:
        QueueStateError: Original version or required section shapes are invalid.
    """
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
    """Atomically persist Queue state.

    Args:
        state: Original complete mutable document.
        path: Original local Queue state location.

    Raises:
        QueueStateError: Original state write or replacement fails.
        OSError: Original temporary-file cleanup fails.
    """
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
    state_path: Path, state_service: StateService | None
) -> BlockingRoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state_from(
        "queue",
        TheQueueStateCodec(),
        StateLocation(state_path, DEFAULT_STATE_PATH, state_service),
    )


def _async_state_access(
    state_path: Path, state_service: StateService | None
) -> AsyncRoutineState:
    return AsyncRoutineState(_state_access(state_path, state_service))


def append_event(path: Path, event: str, **details: object) -> None:
    """Append one timestamped Queue audit event.

    Args:
        path: Original append-only audit location.
        event: Original event name.
        details: Original ordered fields, retaining original override semantics.

    Raises:
        QueueStateError: The original audit file cannot be written.
    """
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
    """Return the accent- and punctuation-tolerant Last.fm artist key.

    Args:
        name: Original artist spelling.

    Returns:
        Original normalized identity.
    """
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

    return QueueSeeds(BerlinCalendar(), SEED_POOL_MULTIPLIER).select(
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

    return cached_artists(raw, week_start)


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


async def async_gather_artist_recommendations(
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
    from spotify_manager.interfaces.operations.the_queue import (
        gather_artist_recommendations as operation,
    )

    return await operation(
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


def _mapped_artist(raw: object) -> release_check.SpotifyArtistCandidate | None:
    from spotify_manager.infrastructure.queue_records import mapped_artist

    return mapped_artist(raw)


def _mapping_choice_reader(
    reader: ArtistChoiceReader | None,
    recommendation: ArtistRecommendation,
) -> release_check.ArtistChoiceReader | None:
    """Adapt the Queue recommendation prompt to release-check mapping logic."""
    if reader is None:
        return None

    from spotify_manager.application.queue_artist_mapping import QueueMappingChoice

    return QueueMappingChoice(reader, recommendation)


async def _playlist_artist_ids(
    sp: Spotify,
    playlist_ids: Iterable[str],
    retry_call: RetryCall,
) -> set[str]:
    represented: set[str] = set()
    for playlist_id in playlist_ids:
        tracks = await new_wine.async_load_playlist_tracks(sp, playlist_id, retry_call)
        for track in tracks:
            represented.add(track.primary_artist_id)
    return represented


async def _liked_statuses(
    sp: Spotify,
    tracks: Iterable[new_kids.CatalogTrack],
    retry_call: RetryCall,
) -> dict[str, bool]:
    materialized = tuple(tracks)
    if not materialized:
        return {}
    for attempt in retry_call.attempts(
        f"checking {len(materialized)} top tracks in Liked Songs"
    ):
        async with attempt:
            response = await sp.current_user_saved_tracks_contains(
                [track.spotify_id for track in materialized]
            )
    if not isinstance(response, list) or len(response) != len(materialized):
        raise QueueSpotifyError("Spotify returned invalid Liked Songs statuses.")
    statuses = {}
    for track, liked in zip(materialized, response, strict=True):
        statuses[track.spotify_id] = bool(liked)
    return statuses


async def _persist_followed_artist(
    candidate: release_check.SpotifyArtistCandidate,
    echo: Echo,
) -> None:
    persisted = await record_followed_artist(
        AlbumArtist(spotify_id=candidate.spotify_id, name=candidate.name)
    )
    if persisted.total_artists_updated:
        echo.echo(f"Recorded artist in artists_total.json: {candidate.name}")
    if persisted.stats_history_updated:
        echo.echo("Updated stats_history.json.")


async def _fill_following(
    sp: Spotify,
    spotify_artist: release_check.SpotifyArtistCandidate,
    retry: RetryCall,
) -> bool:
    for attempt in retry.attempts(f"checking follow status for {spotify_artist.name}"):
        async with attempt:
            followed_response = await sp.current_user_following_artists(
                [spotify_artist.spotify_id]
            )
    if not isinstance(followed_response, list) or not followed_response:
        raise QueueSpotifyError("Spotify returned invalid artist follow status.")
    return bool(followed_response[0])


async def _fill_follow(
    sp: Spotify,
    spotify_artist: release_check.SpotifyArtistCandidate,
    retry: RetryCall,
) -> None:
    for attempt in retry.attempts(f"following {spotify_artist.name}"):
        async with attempt:
            await sp.user_follow_artists([spotify_artist.spotify_id])


async def async_fill_queue_from_lastfm(
    sp: Spotify,
    lastfm: LastFmReader,
    options: QueueFillOptions,
    callbacks: QueueFillCallbacks,
    resources: QueueFillResources | None = None,
) -> FillSummary:
    """Add unheard Last.fm artist recommendations to The Queue.

    Args:
        sp: Caller-owned client.
        lastfm: Caller-owned client.
        options: Destinations and execution mode.
        callbacks: Operator decisions, notifications and retry ownership.
        resources: Persistent files and checkpoint authority.

    Returns:
        The original typed summary and accepted effects.

    Raises:
        RuntimeError: Observations, selections or persistence cannot complete.
    """
    from spotify_manager.interfaces.operations.the_queue import (
        fill_queue_from_lastfm as operation,
    )

    return await operation(sp, lastfm, options, callbacks, resources)


def _playlist_track_from_record(raw: object) -> new_wine.PlaylistTrack:
    from spotify_manager.infrastructure.queue_records import playlist_track

    return playlist_track(raw)


def _catalog_track_from_record(raw: object) -> new_kids.CatalogTrack | None:
    from spotify_manager.infrastructure.queue_records import catalog_track

    return catalog_track(raw)


def _new_flush_run(
    playlist_id: str,
    tracks: tuple[new_wine.PlaylistTrack, ...],
) -> dict[str, object]:
    from spotify_manager.application.queue_flush import new_flush_run

    return new_flush_run(playlist_id, tracks, DAILY_ARTIST_LIMIT, _FLUSH_CLOCK_RESOURCE)


def _flush_clock() -> datetime:
    return datetime.now(UTC)


class FlushClockClock:
    """Observe the original flush clock source directly."""

    def now(self) -> datetime:
        """Read the original clock at the same execution boundary.

        Returns:
            Original observed value.
        """
        return _flush_clock()


_FLUSH_CLOCK_RESOURCE = FlushClockClock()


async def _promotion_track(
    sp: Spotify,
    artist_id: str,
    catalog: tuple[new_kids.RankedRelease, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[new_kids.CatalogTrack, ...]],
) -> tuple[new_kids.CatalogTrack | None, str | None]:
    from spotify_manager.application.queue_flush_planning import promotion_marker
    from spotify_manager.infrastructure.legacy.queue_planning import LegacyQueuePlanning

    return await promotion_marker(
        LegacyQueuePlanning(sp, retry_call), artist_id, catalog, track_cache
    )


async def _plan_flush_entry(
    sp: Spotify,
    source: new_wine.PlaylistTrack,
    source_uris: list[str],
    retry_call: RetryCall,
) -> dict[str, object]:
    from spotify_manager.interfaces.operations.queue_planning import plan_queue_entry

    return await plan_queue_entry(sp, source, source_uris, retry_call)


def _flush_result(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    dry_run: bool,
) -> FlushResult:
    from spotify_manager.infrastructure.queue_records import flush_result

    return flush_result(source, plan, dry_run)


async def _flush_following(
    sp: Spotify,
    source: new_wine.PlaylistTrack,
    retry: RetryCall,
) -> bool:
    for attempt in retry.attempts(
        f"checking follow status for {source.primary_artist_name}"
    ):
        async with attempt:
            followed = await sp.current_user_following_artists(
                [source.primary_artist_id]
            )
    if not isinstance(followed, list) or not followed:
        raise QueueSpotifyError("Spotify returned invalid artist follow status.")
    return bool(followed[0])


async def async_flush_queue(
    sp: Spotify,
    playlists: QueuePlaylists,
    *,
    dry_run: bool = False,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
) -> FlushSummary:
    """Advance the first ten Queue artists through their unliked top tracks.

    Args:
        sp: Original caller-owned Spotify client.
        playlists: Original configured destination identities.
        dry_run: Original preview behavior.
        echo: Original text presenter.
        progress_callback: Original optional stage presenter.
        retry_call: Original optional retry boundary.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        log_path: Original audit location.
        artists_path: Original artist mirror location.

    Returns:
        Original ordered outcomes after accepted effects and checkpoints.

    Raises:
        QueueStateError: Original stored sources, plans or counts are invalid.
        QueueSpotifyError: Original follow-status response is invalid.
    """
    from spotify_manager.interfaces.operations.the_queue import flush_queue as operation

    return await operation(
        sp,
        playlists,
        dry_run=dry_run,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        artists_path=artists_path,
    )


def gather_artist_recommendations(
    lastfm: LastFmReader | LegacyNeighborReader,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.history import (
        PythonNeighborReader,
    )

    return run_python(
        async_gather_artist_recommendations(
            PythonNeighborReader(lastfm),
            seeds,
            heard_keys,
            cache_path=cache_path,
            log_path=log_path,
            week_start=week_start,
            candidate_pool_size=candidate_pool_size,
            now=now,
            progress_callback=progress_callback,
        )
    )


def fill_queue_from_lastfm(
    sp: LegacySpotify,
    lastfm: LastFmReader | LegacyNeighborReader,
    options: QueueFillOptions,
    callbacks: QueueFillCallbacks,
    resources: QueueFillResources | None = None,
) -> FillSummary:
    """Add unheard Last.fm artist recommendations to The Queue.

    Args:
        sp: Caller-owned client.
        lastfm: Caller-owned client.
        options: Destinations and execution mode.
        callbacks: Operator decisions, notifications and retry ownership.
        resources: Persistent files and checkpoint authority.

    Returns:
        The original typed summary and accepted effects.

    Raises:
        RuntimeError: Observations, selections or persistence cannot complete.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.history import (
        PythonNeighborReader,
    )
    from spotify_manager.infrastructure.python_compat.inputs import (
        python_queue_fill_callbacks,
    )
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_fill_queue_from_lastfm(
            legacy_spotify(sp),
            PythonNeighborReader(lastfm),
            options,
            python_queue_fill_callbacks(callbacks),
            resources,
        )
    )


def flush_queue(
    sp: LegacySpotify,
    playlists: QueuePlaylists,
    *,
    dry_run: bool = False,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None | LegacyRetry = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
) -> FlushSummary:
    """Advance the first ten Queue artists through their unliked top tracks.

    Args:
        sp: Original caller-owned Spotify client.
        playlists: Original configured destination identities.
        dry_run: Original preview behavior.
        echo: Original text presenter.
        progress_callback: Original optional stage presenter.
        retry_call: Original optional retry boundary.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        log_path: Original audit location.
        artists_path: Original artist mirror location.

    Returns:
        Original ordered outcomes after accepted effects and checkpoints.

    Raises:
        QueueStateError: Original stored sources, plans or counts are invalid.
        QueueSpotifyError: Original follow-status response is invalid.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.retry import PythonRetry
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_flush_queue(
            legacy_spotify(sp),
            playlists,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=PythonRetry(retry_call) if retry_call is not None else None,
            state_path=state_path,
            state_service=state_service,
            log_path=log_path,
            artists_path=artists_path,
        )
    )
