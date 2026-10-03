"""Advance Queue 3 artists through complete studio discographies."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.queue_3_values import (
    AnnualImportResult as AnnualImportResult,
)
from spotify_manager.application.queue_3_values import (
    AnnualImportSummary as AnnualImportSummary,
)
from spotify_manager.application.queue_3_values import FlushAction as FlushAction
from spotify_manager.application.queue_3_values import FlushResult as FlushResult
from spotify_manager.application.queue_3_values import FlushSummary as FlushSummary
from spotify_manager.application.queue_3_values import (
    Queue3CancelledError as Queue3CancelledError,
)
from spotify_manager.application.queue_3_values import (
    Queue3ConfigError as Queue3ConfigError,
)
from spotify_manager.application.queue_3_values import Queue3Error as Queue3Error
from spotify_manager.application.queue_3_values import (
    Queue3StateError as Queue3StateError,
)
from spotify_manager.application.queue_3_values import SeedAction as SeedAction
from spotify_manager.application.release_evaluation import evaluate_release

# UFI
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import release_candidate
from spotify_manager.infrastructure.library_records import REMOVED_ALBUMS_LOG_PATH
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.routines import composer_playlists
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import slow_listening


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "queue_3_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "queue_3_log.jsonl"
DEFAULT_ALBUMS_PATH = FILES_DIR / "albums_total_new.json"
STATE_VERSION = 1
DAILY_ARTIST_LIMIT = 10
PLAYLIST_MUTATION_BATCH_SIZE = 100
CHOICE_ADVANCE = "advance"
CHOICE_QUIT = "quit"

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
ReleaseTransitionReader = Callable[
    [
        new_wine.PlaylistTrack,
        slow_listening.DiscographyRelease,
        slow_listening.DiscographyRelease,
    ],
    str,
]
ComposerPlaylistReader = Callable[[str, tuple["OwnedPlaylist", ...]], str]


OwnedPlaylist = composer_playlists.OwnedPlaylist


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Queue 3 playlist identifier.

    Args:
        reference: Original configured URI, URL or identifier.

    Returns:
        Parsed Queue 3 playlist identifier.

    Raises:
        Queue3ConfigError: The configured reference is missing or invalid.
    """
    try:
        return new_wine.parse_playlist_id(reference, "THE_QUEUE_3_PLAYLIST")
    except new_wine.NewWineConfigError as exc:
        raise Queue3ConfigError(str(exc)) from exc


def _default_state() -> dict[str, object]:
    """Return empty restart and annual-import state."""
    return {
        "version": STATE_VERSION,
        "annual_imports": {},
        "composer_routes": {},
        "release_orders": {},
        "active_run": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load Queue 3 state without hiding malformed files.

    Args:
        path: Existing legacy JSON namespace path.

    Returns:
        Validated original namespace, or an empty namespace when the file is absent.

    Raises:
        Queue3StateError: Reading, decoding or validating the namespace fails.
    """
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Queue3StateError(f"Queue 3 state is invalid: {path}") from exc
    try:
        return validate_state(raw)
    except Queue3StateError as exc:
        raise Queue3StateError(f"Queue 3 state is invalid: {path}") from exc


def validate_state(raw: object) -> dict[str, object]:
    """Validate and upgrade the Queue 3 namespace independently of storage.

    Args:
        raw: Original decoded JSON namespace, retaining unknown fields.

    Returns:
        The same namespace with missing composer routes initialized when applicable.

    Raises:
        Queue3StateError: Version or required container types are invalid.
    """
    if isinstance(raw, dict) and raw.get("version") == STATE_VERSION:
        raw.setdefault("composer_routes", {})
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("annual_imports"), dict)
        or not isinstance(raw.get("composer_routes"), dict)
        or not isinstance(raw.get("release_orders"), dict)
        or (
            raw.get("active_run") is not None
            and not isinstance(raw.get("active_run"), dict)
        )
    ):
        raise Queue3StateError("Queue 3 state is invalid.")
    return raw


def save_state(state: dict[str, object], path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist Queue 3 state through an atomic replacement.

    Args:
        state: Complete namespace retaining the existing serialized schema.
        path: Existing legacy JSON destination.

    Raises:
        Queue3StateError: Creating, writing or replacing the state file fails.
        OSError: Removing the temporary file fails.
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
        raise Queue3StateError(f"Could not save Queue 3 state: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="queue_3",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def append_event(path: Path, event_type: str, **details: object) -> None:
    """Append one auditable Queue 3 event.

    Args:
        path: Original JSON-lines audit destination.
        event_type: Original event identifier.
        details: Original structured event fields.

    Raises:
        Queue3StateError: The audit destination cannot be created or written.
    """
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "event": event_type,
        **details,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise Queue3StateError(f"Could not write Queue 3 log: {path}") from exc


def load_owned_playlists(
    sp: Spotify,
    retry_call: RetryCall,
    owner_playlist_id: str,
) -> tuple[OwnedPlaylist, ...]:
    """Load playlists owned by the owner of the configured Queue 3 playlist.

    Args:
        sp: Caller-owned Spotify client.
        retry_call: Existing request retry and cancellation boundary.
        owner_playlist_id: Configured Queue 3 playlist used to resolve ownership.

    Returns:
        Original owned-playlist observations.

    Raises:
        Queue3ConfigError: The shared owned-playlist observer fails.
    """
    try:
        return composer_playlists.load_owned_playlists(
            sp,
            retry_call,
            frozenset({owner_playlist_id}),
        )
    except composer_playlists.ComposerPlaylistError as exc:
        raise Queue3ConfigError(str(exc)) from exc


def composer_playlist_candidates(
    artist_name: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    *,
    excluded_playlist_id: str,
) -> tuple[OwnedPlaylist, ...]:
    """Match owned playlists containing a composer's full name or surname.

    Args:
        artist_name: Logical artist display name.
        owned_playlists: Original owned-playlist observations.
        excluded_playlist_id: Queue 3 destination excluded from routing.

    Returns:
        Conservatively matched works playlists in the existing candidate order.
    """
    return composer_playlists.composer_playlist_candidates(
        artist_name,
        owned_playlists,
        excluded_playlist_ids=frozenset({excluded_playlist_id}),
    )


def find_yearly_great_discoveries(
    owned_playlists: tuple[OwnedPlaylist, ...],
    year: int,
) -> str:
    """Find one exact previous-year Great Discoveries playlist owned by the user.

    Args:
        owned_playlists: Original owned-playlist observations.
        year: Previous year used in the exact playlist title.

    Returns:
        The sole distinct matching playlist identifier.

    Raises:
        Queue3ConfigError: Matching playlists are missing or ambiguous.
    """
    from spotify_manager.application.queue_3_import import resolve_yearly_playlist

    return resolve_yearly_playlist(owned_playlists, year)


def _add_playlist_tracks(
    sp: Spotify,
    playlist_id: str,
    tracks: list[new_wine.PlaylistTrack],
    retry_call: RetryCall,
    description: str,
) -> None:
    """Append playlist tracks in Spotify-sized batches."""
    for start in range(0, len(tracks), PLAYLIST_MUTATION_BATCH_SIZE):
        batch = tracks[start : start + PLAYLIST_MUTATION_BATCH_SIZE]
        retry_call(
            partial(
                sp._post,
                f"playlists/{playlist_id}/items",
                payload={"uris": [track.uri for track in batch]},
            ),
            f"{description} ({start + 1}-{start + len(batch)})",
        )


def _remove_playlist_uris(
    sp: Spotify,
    playlist_id: str,
    uris: list[str],
    retry_call: RetryCall,
    description: str,
) -> None:
    """Remove exact playlist markers in Spotify-sized batches."""
    unique_uris = list(dict.fromkeys(uris))
    for start in range(0, len(unique_uris), PLAYLIST_MUTATION_BATCH_SIZE):
        batch = unique_uris[start : start + PLAYLIST_MUTATION_BATCH_SIZE]
        retry_call(
            partial(
                sp._delete,
                f"playlists/{playlist_id}/items",
                payload={"items": [{"uri": uri} for uri in batch]},
            ),
            f"{description} ({start + 1}-{start + len(batch)})",
        )


def _annual_import(
    sp: Spotify,
    playlist_id: str,
    current_tracks: list[new_wine.PlaylistTrack],
    state: dict[str, object],
    *,
    owned_playlists: tuple[OwnedPlaylist, ...],
    active_year: int,
    dry_run: bool,
    retry_call: RetryCall,
    log_path: Path,
    echo: Echo,
    state_access: RoutineState | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
) -> tuple[list[new_wine.PlaylistTrack], tuple[AnnualImportResult, ...]]:
    """Copy unique artists from the previous year's Great Discoveries once."""
    from spotify_manager.bootstrap.queue_3 import annual_import

    state_access = state_access or _state_access(state_path, None)
    service = annual_import(sp, retry_call, log_path, state_access, echo)
    return service.run(
        playlist_id, current_tracks, state, owned_playlists, active_year, dry_run
    )


def import_previous_year_discoveries(
    sp: Spotify,
    playlist_id: str,
    *,
    active_year: int | None = None,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> AnnualImportSummary:
    """Import last year's Great Discoveries without advancing Queue 3.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Configured Queue 3 destination.
        active_year: Explicit checkpoint year, or the current UTC year.
        dry_run: Whether to clone state and suppress writes.
        echo: Existing output sink.
        progress_callback: Optional progress sink.
        retry_call: Optional retry and cancellation callback.
        state_path: Existing legacy namespace path.
        state_service: Optional shared state service.
        log_path: Original audit destination.

    Returns:
        Original annual import summary with source-ordered artist decisions.

    Raises:
        Queue3Error: Configuration, playlist observation or state handling fails.
    """
    from spotify_manager.interfaces.operations.queue_3 import (
        import_previous_year_discoveries as operation,
    )

    return operation(
        sp,
        playlist_id,
        active_year=active_year,
        dry_run=dry_run,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
    )


def _new_run(
    playlist_id: str,
    tracks: list[new_wine.PlaylistTrack],
    state: dict[str, object],
) -> dict[str, object]:
    from spotify_manager.application.queue_3_state import new_run
    from spotify_manager.bootstrap.queue_3 import _datetime

    return new_run(playlist_id, tracks, state, _datetime, DAILY_ARTIST_LIMIT)


def _source_from_record(raw: object) -> new_wine.PlaylistTrack:
    from spotify_manager.application.queue_3_state import source_from_record

    return source_from_record(raw)


def _release_from_record(raw: object) -> slow_listening.DiscographyRelease | None:
    from spotify_manager.application.queue_3_state import release_from_record

    return release_from_record(raw)


def _track_from_record(raw: object) -> new_wine.ReleaseTrack | None:
    from spotify_manager.application.queue_3_state import track_from_record

    return track_from_record(raw)


def _as_ranked_release(
    release: slow_listening.DiscographyRelease,
) -> new_kids.RankedRelease:
    from spotify_manager.domain.queue_3 import ranked_release

    return ranked_release(release)


def _live_evaluation(
    sp: Spotify,
    release: slow_listening.DiscographyRelease,
    tracks: tuple[new_wine.ReleaseTrack, ...],
    liked_cache: dict[str, bool],
    retry_call: RetryCall,
) -> AlbumEvaluation:
    """Evaluate a completed Queue 3 release from live Liked Songs."""
    new_wine.get_liked_statuses(
        sp,
        [track.spotify_id for track in tracks],
        liked_cache,
        retry_call,
    )
    return evaluate_release(
        release_candidate(release),
        tracks,
        liked_cache,
    )


def _stable_release_order(
    _release_date: str,
    releases: tuple[slow_listening.DiscographyRelease, ...],
) -> tuple[str, ...]:
    """Retain the deterministic catalog order for equal-date releases."""
    return tuple(release.spotify_id for release in releases)


def _source_release(
    source: new_wine.PlaylistTrack,
) -> slow_listening.DiscographyRelease:
    from spotify_manager.domain.queue_3 import source_release

    return source_release(source)


def _transition_plan(
    sp: Spotify,
    source: new_wine.PlaylistTrack,
    current_release: slow_listening.DiscographyRelease,
    next_release: slow_listening.DiscographyRelease,
    retry_call: RetryCall,
    track_cache: dict[str, tuple[new_wine.ReleaseTrack, ...]],
    transition_reader: ReleaseTransitionReader,
    *,
    evaluation: AlbumEvaluation | None = None,
    reason: str | None = None,
) -> dict[str, object] | None:
    from spotify_manager.bootstrap.queue_3 import _no_checkpoint
    from spotify_manager.bootstrap.queue_3 import review_planner

    planner = review_planner(
        sp, retry_call, track_cache, {}, {}, _no_checkpoint, transition_reader
    )
    return planner.transition(
        source, current_release, next_release, evaluation=evaluation, reason=reason
    )


def _build_plan(
    sp: Spotify,
    source: new_wine.PlaylistTrack,
    discography: tuple[slow_listening.DiscographyRelease, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[new_wine.ReleaseTrack, ...]],
    liked_cache: dict[str, bool],
    release_orders: dict[str, object],
    order_saved: Callable[[], None],
    transition_reader: ReleaseTransitionReader,
) -> dict[str, object] | None:
    from spotify_manager.bootstrap.queue_3 import review_planner

    planner = review_planner(
        sp,
        retry_call,
        track_cache,
        liked_cache,
        release_orders,
        order_saved,
        transition_reader,
    )
    return planner.plan(source, discography)


def _resolve_composer_playlist(
    artist_id: str,
    artist_name: str,
    source_track_id: str,
    playlist_id: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    state: dict[str, object],
    composer_playlist_reader: ComposerPlaylistReader | None,
) -> tuple[OwnedPlaylist | None, bool]:
    from spotify_manager.application.queue_3_composers import resolve_composer_route
    from spotify_manager.bootstrap.queue_3 import _now

    return resolve_composer_route(
        artist_id,
        artist_name,
        source_track_id,
        playlist_id,
        owned_playlists,
        state,
        composer_playlist_reader,
        _now,
    )


def _composer_plan(
    source: new_wine.PlaylistTrack,
    composer_playlist: OwnedPlaylist,
    playlist_tracks: tuple[new_wine.PlaylistTrack, ...],
) -> dict[str, object]:
    from spotify_manager.application.queue_3_composers import composer_plan

    return composer_plan(source, composer_playlist, playlist_tracks)


def _result_from_plan(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    *,
    artist_name: str,
    dry_run: bool,
) -> FlushResult:
    from spotify_manager.application.queue_3_state import result_from_plan

    return result_from_plan(source, plan, artist_name=artist_name, dry_run=dry_run)


def flush_queue_3(
    sp: Spotify,
    playlist_id: str,
    transition_reader: ReleaseTransitionReader,
    *,
    composer_playlist_reader: ComposerPlaylistReader | None = None,
    active_year: int | None = None,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
) -> FlushSummary:
    """Import the previous year once, then advance the first ten Queue 3 artists.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Configured Queue 3 destination.
        transition_reader: Original release-boundary decision callback.
        composer_playlist_reader: Optional owned works-playlist selection callback.
        active_year: Explicit checkpoint year, or the current UTC year.
        dry_run: Whether state is cloned and durable writes suppressed.
        echo: Existing output sink.
        progress_callback: Optional entry progress sink.
        retry_call: Optional retry and cancellation callback.
        state_path: Original legacy namespace path.
        state_service: Optional shared state service.
        log_path: Original Queue 3 audit destination.
        albums_path: Original local album mirror.
        removed_albums_log_path: Original removed-album recovery log.

    Returns:
        Original public Queue 3 summary with per-artist decisions and resume status.

    Raises:
        Queue3Error: Configuration, state, planning or execution fails.
    """
    from spotify_manager.interfaces.operations.queue_3 import flush_queue_3 as operation

    return operation(
        sp,
        playlist_id,
        transition_reader,
        composer_playlist_reader=composer_playlist_reader,
        active_year=active_year,
        dry_run=dry_run,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        removed_albums_log_path=removed_albums_log_path,
    )
