"""Advance Queue 3 artists through complete studio discographies."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import cast

from spotipy import Spotify

from spotify_manager.application.queue_3_values import (
    AnnualImportResult as AnnualImportResult,
)
from spotify_manager.application.queue_3_values import (
    AnnualImportSummary as AnnualImportSummary,
)
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

# UFI
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
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
FlushAction = Literal[
    "advance",
    "composer playlist",
    "next release",
    "complete",
    "skip",
]


OwnedPlaylist = composer_playlists.OwnedPlaylist


@dataclass(frozen=True)
class FlushResult:
    """One snapshotted Queue 3 artist transition."""

    artist: str
    source_track: str
    source_release: str
    action: FlushAction
    target_track: str | None = None
    target_release: str | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    composer_playlist: str | None = None
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one restart-safe Queue 3 run."""

    run_id: str
    total: int
    processed: int
    advanced: int
    changed_releases: int
    completed_artists: int
    skipped: int
    annual_import: tuple[AnnualImportResult, ...]
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Queue 3 playlist id."""
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
    """Load Queue 3 state without hiding malformed files."""
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
    """Validate and upgrade the Queue 3 namespace independently of storage."""
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
    """Persist Queue 3 state through an atomic replacement."""
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
    """Append one auditable Queue 3 event."""
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
    """Load playlists owned by the owner of the configured Queue 3 playlist."""
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
    """Match owned playlists containing a composer's full name or surname."""
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
    from spotify_manager.bootstrap.queue_3 import run_import

    return run_import(
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
    """Snapshot the first ten unique logical artists."""
    routes = cast(dict[str, object], state["composer_routes"])
    route_by_track: dict[str, tuple[str, str]] = {}
    for artist_id, raw_route in routes.items():
        if not isinstance(raw_route, dict):
            continue
        current_track_id = str(raw_route.get("current_track_id") or "")
        artist_name = str(raw_route.get("artist_name") or "")
        if current_track_id and artist_name:
            route_by_track[current_track_id] = (artist_id, artist_name)

    selected: list[tuple[new_wine.PlaylistTrack, str, str]] = []
    seen_artists: set[str] = set()
    for track in tracks:
        artist_id, artist_name = route_by_track.get(
            track.spotify_id,
            (track.primary_artist_id, track.primary_artist_name),
        )
        if artist_id in seen_artists:
            continue
        selected.append((track, artist_id, artist_name))
        seen_artists.add(artist_id)
        if len(selected) == DAILY_ARTIST_LIMIT:
            break
    return {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "entries": [
            {
                "source": asdict(track),
                "artist_id": artist_id,
                "artist_name": artist_name,
                "status": "pending",
                "plan": None,
            }
            for track, artist_id, artist_name in selected
        ],
    }


def _source_from_record(raw: object) -> new_wine.PlaylistTrack:
    """Rebuild one snapshotted Queue 3 source."""
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise Queue3StateError("Queue 3 run has an invalid source track.")
    release = new_wine.ReleaseCandidate(**raw["release"])
    return new_wine.PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=release,
    )


def _release_from_record(raw: object) -> slow_listening.DiscographyRelease | None:
    """Rebuild one optional selected discography release."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise Queue3StateError("Queue 3 plan has an invalid release.")
    return slow_listening.DiscographyRelease(**raw)


def _track_from_record(raw: object) -> new_wine.ReleaseTrack | None:
    """Rebuild one optional target track."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise Queue3StateError("Queue 3 plan has an invalid target track.")
    return new_wine.ReleaseTrack(**raw)


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
    return new_wine._live_evaluation(
        slow_listening._as_release_candidate(release),
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
    """Resolve and persist one owned composer works playlist."""
    routes = cast(dict[str, object], state["composer_routes"])
    candidates = composer_playlist_candidates(
        artist_name,
        owned_playlists,
        excluded_playlist_id=playlist_id,
    )
    existing = routes.get(artist_id)
    if isinstance(existing, dict):
        existing_id = str(existing.get("playlist_id") or "")
        selected = next(
            (
                candidate
                for candidate in candidates
                if candidate.spotify_id == existing_id
            ),
            None,
        )
        if selected is not None:
            return selected, False
        routes.pop(artist_id, None)

    if not candidates:
        return None, False
    if len(candidates) == 1:
        selected = candidates[0]
    else:
        if composer_playlist_reader is None:
            names = ", ".join(candidate.name for candidate in candidates)
            raise Queue3ConfigError(
                f"Multiple owned playlists match {artist_name}: {names}."
            )
        selected_id = composer_playlist_reader(artist_name, candidates)
        if selected_id == CHOICE_QUIT:
            return None, True
        selected = next(
            (
                candidate
                for candidate in candidates
                if candidate.spotify_id == selected_id
            ),
            None,
        )
        if selected is None:
            raise Queue3ConfigError(
                f"The selected playlist is not an owned match for {artist_name}."
            )

    routes[artist_id] = {
        "artist_name": artist_name,
        "playlist_id": selected.spotify_id,
        "playlist_name": selected.name,
        "current_track_id": source_track_id,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return selected, False


def _composer_plan(
    source: new_wine.PlaylistTrack,
    composer_playlist: OwnedPlaylist,
    playlist_tracks: tuple[new_wine.PlaylistTrack, ...],
) -> dict[str, object]:
    """Plan the next distinct track in an owned playlist's stored order."""
    source_indexes = [
        index
        for index, track in enumerate(playlist_tracks)
        if track.spotify_id == source.spotify_id
    ]
    if not source_indexes:
        normalized_source = composer_playlists.name_tokens(source.name)
        title_matches = [
            index
            for index, track in enumerate(playlist_tracks)
            if composer_playlists.name_tokens(track.name) == normalized_source
        ]
        if len(title_matches) == 1:
            source_indexes = title_matches
    if not source_indexes:
        return {
            "action": "skip",
            "current_release": asdict(_source_release(source)),
            "target_release": None,
            "target": None,
            "evaluation": None,
            "composer_playlist_id": composer_playlist.spotify_id,
            "composer_playlist_name": composer_playlist.name,
            "reason": "current marker was not found in the composer playlist",
        }

    source_index = source_indexes[0]
    target = next(
        (
            track
            for track in playlist_tracks[source_index + 1 :]
            if track.spotify_id != source.spotify_id
        ),
        None,
    )
    if target is None:
        return {
            "action": "complete",
            "current_release": asdict(_source_release(source)),
            "target_release": None,
            "target": None,
            "evaluation": None,
            "composer_playlist_id": composer_playlist.spotify_id,
            "composer_playlist_name": composer_playlist.name,
            "reason": "last track of the composer playlist",
        }

    return {
        "action": "composer_advance",
        "current_release": asdict(_source_release(source)),
        "target_release": asdict(_source_release(target)),
        "target": asdict(
            new_wine.ReleaseTrack(
                spotify_id=target.spotify_id,
                uri=target.uri,
                name=target.name,
                disc_number=1,
                track_number=1,
            )
        ),
        "evaluation": None,
        "composer_playlist_id": composer_playlist.spotify_id,
        "composer_playlist_name": composer_playlist.name,
        "reason": "advanced through the owned composer playlist in playlist order",
    }


def _result_from_plan(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    *,
    artist_name: str,
    dry_run: bool,
) -> FlushResult:
    """Convert one durable plan to its public result."""
    action = str(plan["action"])
    target = _track_from_record(plan.get("target"))
    target_release = _release_from_record(plan.get("target_release"))
    evaluation = (
        AlbumEvaluation.model_validate(plan["evaluation"])
        if isinstance(plan.get("evaluation"), dict)
        else None
    )
    public_action = {
        "composer_advance": "composer playlist",
        "next_release": "next release",
    }.get(action, action)
    return FlushResult(
        artist=artist_name,
        source_track=source.name,
        source_release=source.release.name,
        action=cast(FlushAction, public_action),
        target_track=target.name if target is not None else None,
        target_release=target_release.name if target_release is not None else None,
        album_decision=evaluation.decision if evaluation is not None else None,
        album_liked_tracks=evaluation.liked_tracks if evaluation is not None else None,
        album_total_tracks=evaluation.total_tracks if evaluation is not None else None,
        composer_playlist=(
            str(plan["composer_playlist_name"])
            if plan.get("composer_playlist_name")
            else None
        ),
        reason=str(plan["reason"]) if plan.get("reason") else None,
        dry_run=dry_run,
    )


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
    """Import the previous year once, then advance the first ten Queue 3 artists."""
    retry = retry_call or (lambda operation, _description: operation())
    year = active_year or datetime.now(UTC).year
    owned_playlists = load_owned_playlists(sp, retry, playlist_id)
    try:
        live_tracks = list(new_wine.load_playlist_tracks(sp, playlist_id, retry))
    except new_wine.NewWineError as exc:
        raise Queue3Error(str(exc)) from exc

    state_access = _state_access(state_path, state_service)
    persisted_state = state_access.load()
    state = json.loads(json.dumps(persisted_state)) if dry_run else persisted_state
    live_tracks, annual_import = _annual_import(
        sp,
        playlist_id,
        live_tracks,
        state,
        owned_playlists=owned_playlists,
        active_year=year,
        dry_run=dry_run,
        retry_call=retry,
        state_access=state_access,
        log_path=log_path,
        echo=echo,
    )
    live_ids = {track.spotify_id for track in live_tracks}

    resumed = False
    active_run = state.get("active_run")
    if (
        not dry_run
        and isinstance(active_run, dict)
        and active_run.get("status") == "active"
        and active_run.get("playlist_id") == playlist_id
    ):
        run = active_run
        resumed = True
    else:
        run = _new_run(playlist_id, live_tracks, state)
        if not dry_run:
            state["active_run"] = run
            state_access.save(state)

    raw_entries = run.get("entries")
    if not isinstance(raw_entries, list):
        raise Queue3StateError("Queue 3 active run has invalid entries.")
    release_orders = state.get("release_orders")
    if not isinstance(release_orders, dict):
        raise Queue3StateError("Queue 3 release-order state is invalid.")
    composer_routes = state.get("composer_routes")
    if not isinstance(composer_routes, dict):
        raise Queue3StateError("Queue 3 composer-route state is invalid.")

    run_id = str(run["run_id"])
    catalog_cache: dict[
        str,
        tuple[slow_listening.DiscographyRelease, ...],
    ] = {}
    track_cache: dict[str, tuple[new_wine.ReleaseTrack, ...]] = {}
    composer_track_cache: dict[str, tuple[new_wine.PlaylistTrack, ...]] = {}
    liked_cache: dict[str, bool] = {}
    results: list[FlushResult] = []
    paused = False
    total = len(raw_entries)

    def persist_order() -> None:
        if not dry_run:
            state_access.save(state)

    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise Queue3StateError("Queue 3 run contains an invalid entry.")
        if raw_entry.get("status") in {"completed", "skipped"}:
            continue
        source = _source_from_record(raw_entry.get("source"))
        artist_id = str(raw_entry.get("artist_id") or source.primary_artist_id)
        artist_name = str(raw_entry.get("artist_name") or source.primary_artist_name)
        if progress_callback is not None:
            progress_callback(
                index - 1,
                total,
                f"{artist_name} - {source.name}",
            )

        raw_plan = raw_entry.get("plan")
        plan = raw_plan if isinstance(raw_plan, dict) else None
        if plan is not None and plan.get("composer_playlist_id"):
            composer_playlist_id = str(plan["composer_playlist_id"])
            if not composer_playlists.is_composer_playlist_candidate(
                artist_name,
                composer_playlist_id,
                owned_playlists,
                excluded_playlist_ids=frozenset({playlist_id}),
            ):
                plan = None
                raw_entry["plan"] = None
                composer_routes.pop(artist_id, None)
                echo(f"Discarded a stale composer-playlist plan for {artist_name}.")
                if not dry_run:
                    state_access.save(state)
        if plan is None:
            composer_playlist, route_paused = _resolve_composer_playlist(
                artist_id,
                artist_name,
                source.spotify_id,
                playlist_id,
                owned_playlists,
                state,
                composer_playlist_reader,
            )
            if route_paused:
                paused = True
                break
            if composer_playlist is not None:
                composer_tracks = composer_track_cache.get(composer_playlist.spotify_id)
                if composer_tracks is None:
                    try:
                        composer_tracks = new_wine.load_playlist_tracks(
                            sp,
                            composer_playlist.spotify_id,
                            retry,
                        )
                    except new_wine.NewWineError as exc:
                        raise Queue3Error(str(exc)) from exc
                    composer_track_cache[composer_playlist.spotify_id] = composer_tracks
                plan = _composer_plan(
                    source,
                    composer_playlist,
                    composer_tracks,
                )
            else:
                discography = catalog_cache.get(artist_id)
                if discography is None:
                    discography = slow_listening.load_discography(
                        sp,
                        artist_id,
                        retry,
                    )
                    catalog_cache[artist_id] = discography
                plan = _build_plan(
                    sp,
                    source,
                    discography,
                    retry,
                    track_cache,
                    liked_cache,
                    release_orders,
                    persist_order,
                    transition_reader,
                )
            if plan is None:
                paused = True
                break
            raw_entry["plan"] = plan
            if not dry_run:
                state_access.save(state)

        action = str(plan["action"])
        current_release = _release_from_record(plan.get("current_release"))
        target_release = _release_from_record(plan.get("target_release"))
        target = _track_from_record(plan.get("target"))
        evaluation = (
            AlbumEvaluation.model_validate(plan["evaluation"])
            if isinstance(plan.get("evaluation"), dict)
            else None
        )

        if evaluation is not None and current_release is not None:
            new_kids._reconcile_release_library(
                sp,
                _as_ranked_release(current_release),
                evaluation,
                dry_run=dry_run,
                retry_call=retry,
                albums_path=albums_path,
                removed_albums_log_path=removed_albums_log_path,
                log_path=log_path,
                echo=echo,
            )

        is_composer_route = bool(plan.get("composer_playlist_id"))
        artist_live_uris = (
            ([source.uri] if source.spotify_id in live_ids else [])
            if is_composer_route
            else [
                track.uri
                for track in live_tracks
                if track.primary_artist_id == artist_id and track.spotify_id in live_ids
            ]
        )
        source_present = source.spotify_id in live_ids
        target_present = target is not None and target.spotify_id in live_ids
        if (
            action in {"advance", "composer_advance", "next_release"}
            and target is not None
        ):
            if not source_present and not target_present:
                raise Queue3StateError(
                    f"{source.name} and its planned replacement are both absent."
                )
            if not target_present:
                release_for_target = target_release or current_release
                if release_for_target is None:
                    raise Queue3StateError(
                        f"{target.name} has no saved target release."
                    )
                if not dry_run:
                    _add_playlist_tracks(
                        sp,
                        playlist_id,
                        [
                            new_wine.PlaylistTrack(
                                spotify_id=target.spotify_id,
                                uri=target.uri,
                                name=target.name,
                                primary_artist_id=artist_id,
                                primary_artist_name=artist_name,
                                release=slow_listening._as_release_candidate(
                                    release_for_target
                                ),
                            )
                        ],
                        retry,
                        f"adding {target.name} to Queue 3",
                    )
                live_ids.add(target.spotify_id)
                echo(f"{'Would add' if dry_run else 'Added'}: {target.name}")
            if source_present or artist_live_uris:
                if not dry_run:
                    _remove_playlist_uris(
                        sp,
                        playlist_id,
                        artist_live_uris or [source.uri],
                        retry,
                        f"removing the previous {artist_name} marker",
                    )
                live_ids.difference_update(
                    track.spotify_id
                    for track in live_tracks
                    if track.uri in set(artist_live_uris)
                )
                echo(
                    f"{'Would remove' if dry_run else 'Removed'} previous track: "
                    f"{source.name}"
                )
        elif action == "complete":
            if artist_live_uris:
                if not dry_run:
                    _remove_playlist_uris(
                        sp,
                        playlist_id,
                        artist_live_uris,
                        retry,
                        f"completing {artist_name} in Queue 3",
                    )
                live_ids.difference_update(
                    track.spotify_id
                    for track in live_tracks
                    if track.uri in set(artist_live_uris)
                )
            echo(
                f"{'Would complete' if dry_run else 'Completed'} "
                f"{artist_name}; removed the final Queue 3 marker."
            )
        elif action == "skip":
            echo(f"Skipped {artist_name}: {plan.get('reason')}.")

        result = _result_from_plan(
            source,
            plan,
            artist_name=artist_name,
            dry_run=dry_run,
        )
        results.append(result)
        append_event(
            log_path,
            "artist_transition",
            run_id=run_id,
            **asdict(result),
        )
        if not dry_run:
            if action == "composer_advance" and target is not None:
                route = composer_routes.get(artist_id)
                if isinstance(route, dict):
                    route["current_track_id"] = target.spotify_id
                    route["updated_at"] = datetime.now(UTC).isoformat()
            raw_entry["status"] = "skipped" if action == "skip" else "completed"
            state_access.save(state)
        if progress_callback is not None:
            progress_callback(index, total, f"Completed {artist_name}")

    if (
        not dry_run
        and not paused
        and all(
            isinstance(entry, dict) and entry.get("status") in {"completed", "skipped"}
            for entry in raw_entries
        )
    ):
        run["status"] = "completed"
        run["completed_at"] = datetime.now(UTC).isoformat()
        state_access.save(state)

    return FlushSummary(
        run_id=run_id,
        total=total,
        processed=len(results),
        advanced=sum(
            result.action in {"advance", "composer playlist"} for result in results
        ),
        changed_releases=sum(result.action == "next release" for result in results),
        completed_artists=sum(result.action == "complete" for result in results),
        skipped=sum(result.action == "skip" for result in results),
        annual_import=annual_import,
        paused=paused,
        dry_run=dry_run,
        resumed=resumed,
        results=tuple(results),
    )
