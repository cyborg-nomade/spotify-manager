"""Advance the New Wine from Old Bottles playlist safely by release."""

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import cast

from spotipy import Spotify

from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.new_wine import new_run
from spotify_manager.application.new_wine_plans import drop_plan
from spotify_manager.application.new_wine_plans import record_evaluation
from spotify_manager.application.new_wine_state import release_from_record
from spotify_manager.application.new_wine_state import result_from_plan
from spotify_manager.application.new_wine_state import source_from_record
from spotify_manager.application.new_wine_state import track_from_record
from spotify_manager.application.new_wine_values import (
    CellarRefillResult as CellarRefillResult,
)
from spotify_manager.application.new_wine_values import (
    CellarRefillSummary as CellarRefillSummary,
)
from spotify_manager.application.new_wine_values import FlushResult as FlushResult
from spotify_manager.application.new_wine_values import FlushSummary as FlushSummary
from spotify_manager.application.new_wine_values import (
    NewWineConfigError as NewWineConfigError,
)
from spotify_manager.application.new_wine_values import NewWineError as NewWineError
from spotify_manager.application.new_wine_values import (
    NewWineStateError as NewWineStateError,
)
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.core.state import RoutineState
from spotify_manager.core.state import StateService
from spotify_manager.core.state.compat import routine_state
from spotify_manager.domain import new_wine as wine_policy

# UFI
from spotify_manager.domain.catalog import PlaylistTrack as PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate as ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack as ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines.recover_removed_albums import sync_stats_history_counts
from spotify_manager.routines.review_album_limits import (
    append_removed_album_log as append_removed_album_log,
)
from spotify_manager.utils.sorting import album_sort_key


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "new_wine_flush_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "new_wine_flush_log.jsonl"
DEFAULT_ALBUMS_PATH = FILES_DIR / "albums_total_new.json"
DEFAULT_LIKED_TRACKS_PATH = FILES_DIR / "liked_tracks_total.json"
DEFAULT_REMOVED_ALBUMS_LOG_PATH = FILES_DIR / "removed_albums_log.jsonl"
PLAYLIST_PAGE_LIMIT = 50
ARTIST_RELEASE_PAGE_LIMIT = 10
LIKED_TRACK_BATCH_SIZE = 10
STATE_VERSION = 1
NEW_WINE_TARGET_SIZE = 10
NO_DISCOVERY_MIN_LIKED_TRACKS = 18
NO_DISCOVERY_MIN_SAVED_ALBUMS = 3
CHOICE_SKIP = "skip"
CHOICE_QUIT = "quit"
CHOICE_DROP = "drop"
CHOICE_FINISH = "finish"
CHOICE_CUTOFF = "cutoff"
CHOICE_CONTINUE = "continue"

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
ReleaseChoiceReader = Callable[["PlaylistTrack", tuple["ReleaseCandidate", ...]], str]
EndpointChoiceReader = Callable[
    ["PlaylistTrack", tuple["ReleaseTrack", ...], int],
    str,
]
FlushAction = Literal[
    "advance",
    "drop",
    "sauvignon",
    "complete single",
    "skip",
]


def parse_playlist_id(reference: str | None, setting_name: str) -> str:
    """Extract a Spotify playlist ID from a URL, URI, or bare ID.

    Args:
        reference: Configured playlist reference.
        setting_name: Setting name used in the original diagnostic.

    Returns:
        Nonempty Spotify playlist identifier.

    Raises:
        NewWineConfigError: The reference is absent or malformed.
    """
    if not reference or not reference.strip():
        raise NewWineConfigError(f"{setting_name} is not configured.")
    value = reference.strip()
    for pattern in (
        r"^spotify:playlist:(?P<id>[A-Za-z0-9]+)$",
        r"open\.spotify\.com/playlist/(?P<id>[A-Za-z0-9]+)",
        r"^(?P<id>[A-Za-z0-9]+)$",
    ):
        match = re.search(pattern, value)
        if match:
            return match.group("id")
    raise NewWineConfigError(f"Invalid {setting_name} playlist reference.")


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Return nonempty Spotify artist ids and names in credit order."""
    if not isinstance(raw, list):
        return ()
    artists: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if spotify_id:
            artists.append((spotify_id, name or spotify_id))
    return tuple(artists)


def classify_release(raw_type: object, total_tracks: int) -> str:
    """Classify Spotify releases while distinguishing EPs from singles.

    Args:
        raw_type: Original Spotify release classification.
        total_tracks: Observed track count used to distinguish EPs.

    Returns:
        Existing display classification, including tolerant unknown types.
    """
    release_type = str(raw_type or "unknown").casefold()
    if release_type == "album":
        return "Album"
    if release_type == "compilation":
        return "Compilation"
    if release_type == "ep":
        return "EP"
    if release_type == "single":
        return "EP" if total_tracks >= 4 else "Single"
    return release_type.title() or "Unknown"


def _track_position(raw: object, fallback: int) -> int:
    """Parse Spotify's one-based disc/track position defensively."""
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if not isinstance(raw, str):
        return fallback
    try:
        parsed = int(raw.strip())
    except ValueError:
        return fallback
    return parsed if parsed > 0 else fallback


def _release_candidate(
    raw: object,
    *,
    target_artist_id: str | None = None,
) -> ReleaseCandidate | None:
    """Parse one Spotify release, requiring the target artist to be first."""
    if not isinstance(raw, dict):
        return None
    artists = _artist_pairs(raw.get("artists"))
    if not artists:
        return None
    if target_artist_id is not None and artists[0][0] != target_artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not spotify_id or not uri:
        return None
    raw_total = raw.get("total_tracks")
    total_tracks = raw_total if isinstance(raw_total, int) else 0
    return ReleaseCandidate(
        spotify_id=spotify_id,
        uri=uri,
        name=str(raw.get("name") or spotify_id),
        release_type=classify_release(raw.get("album_type"), total_tracks),
        release_date=str(raw.get("release_date") or "Unknown"),
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
    )


def _playlist_track(raw_entry: object) -> PlaylistTrack | None:
    """Parse one playable playlist item."""
    if not isinstance(raw_entry, dict):
        return None
    raw_track = raw_entry.get("item") or raw_entry.get("track")
    if not isinstance(raw_track, dict):
        return None
    spotify_id = str(raw_track.get("id") or "").strip()
    uri = str(raw_track.get("uri") or "").strip()
    artists = _artist_pairs(raw_track.get("artists"))
    release = _release_candidate(raw_track.get("album"))
    if not spotify_id or not uri or not artists or release is None:
        return None
    return PlaylistTrack(
        spotify_id=spotify_id,
        uri=uri,
        name=str(raw_track.get("name") or spotify_id),
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        release=release,
    )


def _playlist_request(
    sp: Spotify, playlist_id: str, offset: int
) -> Callable[[], object]:
    return partial(
        sp._get,
        f"playlists/{playlist_id}/items",
        limit=PLAYLIST_PAGE_LIMIT,
        offset=offset,
    )


def load_playlist_tracks(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> tuple[PlaylistTrack, ...]:
    """Load every playable item in playlist order.

    Args:
        sp: Caller-owned synchronous Spotify client.
        playlist_id: Playlist to observe.
        retry_call: Existing retry and cancellation boundary.

    Returns:
        Ordered playable markers, preserving duplicate observations.

    Raises:
        NewWineError: A page is invalid or pagination stalls.
    """
    tracks: list[PlaylistTrack] = []
    offset = 0
    while True:
        response = retry_call(
            _playlist_request(sp, playlist_id, offset),
            f"loading playlist {playlist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise NewWineError("Spotify returned invalid playlist data.")
        raw_items = response["items"]
        _append_playlist_items(tracks, raw_items)
        offset += len(raw_items)
        total = response.get("total")
        has_more = bool(response.get("next"))
        if isinstance(total, int):
            has_more = has_more or offset < total
        if not has_more:
            return tuple(tracks)
        if not raw_items:
            raise NewWineError("Spotify returned an empty playlist page.")


def load_release_tracks(
    sp: Spotify,
    release: ReleaseCandidate,
    retry_call: RetryCall,
) -> tuple[ReleaseTrack, ...]:
    """Load and order a release's complete Spotify track list.

    Args:
        sp: Caller-owned synchronous Spotify client.
        release: Selected release to observe.
        retry_call: Existing retry and cancellation boundary.

    Returns:
        Playable tracks ordered by disc and track position.

    Raises:
        NewWineError: A page is invalid or pagination stalls.
    """
    tracks: list[ReleaseTrack] = []
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.album_tracks,
                release.spotify_id,
                limit=50,
                offset=offset,
            ),
            f"loading {release.name} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise NewWineError(
                f"Spotify returned invalid track data for {release.name}."
            )
        raw_items = response["items"]
        _append_release_items(tracks, raw_items)
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewWineError(
                f"Spotify returned an empty track page for {release.name}."
            )
    return tuple(sorted(tracks, key=_release_track_order))


def current_year_releases(
    sp: Spotify,
    artist_id: str,
    year: int,
    retry_call: RetryCall,
) -> tuple[ReleaseCandidate, ...]:
    """Return current-year primary-artist albums, EPs, and singles.

    Args:
        sp: Caller-owned synchronous Spotify client.
        artist_id: Required first credited artist.
        year: Existing invocation year.
        retry_call: Existing retry and cancellation boundary.

    Returns:
        Deduplicated candidates in the original date/type/title/ID order.

    Raises:
        NewWineError: A page is invalid or pagination stalls.
    """
    releases: dict[str, ReleaseCandidate] = {}
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.artist_albums,
                artist_id,
                include_groups="album,single",
                limit=ARTIST_RELEASE_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading {year} releases for artist {artist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise NewWineError("Spotify returned invalid artist release data.")
        raw_items = response["items"]
        _append_current_year_releases(releases, raw_items, artist_id, year)
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewWineError("Spotify returned an empty artist release page.")
    return tuple(sorted(releases.values(), key=_current_release_order))


def _track_index(
    tracks: tuple[ReleaseTrack, ...],
    source: PlaylistTrack,
) -> int | None:
    """Locate the source in a selected release by id, then normalized name."""
    return wine_policy.track_index(tracks, source)


def get_liked_statuses(
    sp: Spotify,
    track_ids: list[str],
    cache: dict[str, bool],
    retry_call: RetryCall,
) -> dict[str, bool]:
    """Fill and return live Liked Songs statuses in conservative batches.

    Args:
        sp: Caller-owned synchronous Spotify client.
        track_ids: Requested IDs in observation order.
        cache: Run-scoped statuses, updated in place.
        retry_call: Existing retry and cancellation boundary.

    Returns:
        The supplied cache with missing memberships populated.

    Raises:
        NewWineError: Spotify returns an invalid batch response.
    """
    missing = _missing_track_ids(track_ids, cache)
    for start in range(0, len(missing), LIKED_TRACK_BATCH_SIZE):
        batch = missing[start : start + LIKED_TRACK_BATCH_SIZE]
        response = retry_call(
            partial(sp.current_user_saved_tracks_contains, batch),
            f"checking {len(batch)} live Liked Songs statuses",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise NewWineError("Spotify returned invalid Liked Songs statuses.")
        for track_id, liked in zip(batch, response, strict=True):
            cache[track_id] = bool(liked)
    return cache


def _live_evaluation(
    release: ReleaseCandidate,
    tracks: tuple[ReleaseTrack, ...],
    liked: dict[str, bool],
) -> AlbumEvaluation:
    """Build the usual album keep decision entirely from live Spotify state."""
    return evaluate_release(release, tracks, liked)


def _default_state() -> dict[str, object]:
    """Return an empty versioned restart state."""
    return {
        "version": STATE_VERSION,
        "track_progress": {},
        "active_run": None,
    }


def validate_state(raw: object) -> dict[str, object]:
    """Validate the New Wine namespace independently of storage.

    Args:
        raw: Decoded namespace retaining unknown fields.

    Returns:
        Original mutable namespace without copying or normalization.

    Raises:
        NewWineStateError: The version or progress container is invalid.
    """
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("track_progress"), dict)
    ):
        raise NewWineStateError("New Wine state is invalid.")
    return cast(dict[str, object], raw)


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load restart state without discarding malformed data.

    Args:
        path: Existing namespace path.

    Returns:
        Decoded namespace, or defaults when the file is absent.

    Raises:
        NewWineStateError: Reading, decoding or namespace validation fails.
    """
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewWineStateError(f"New Wine state is invalid: {path}") from exc
    try:
        return validate_state(raw)
    except NewWineStateError as exc:
        raise NewWineStateError(f"New Wine state is invalid: {path}") from exc


def save_state(state: dict[str, object], path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist restart state atomically after each successful boundary.

    Args:
        state: Complete namespace, including unknown fields.
        path: Original namespace destination.

    Raises:
        NewWineStateError: Creating or replacing the checkpoint fails.
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
        raise NewWineStateError(f"Could not save New Wine state: {path}") from exc


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="new_wine",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def append_log(
    run_id: str,
    result: FlushResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable source-track outcome.

    Args:
        run_id: Existing execution identifier.
        result: Completed or skipped outcome, including previews.
        path: Original append-only audit destination.

    Raises:
        NewWineStateError: The audit record cannot be written.
    """
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        **asdict(result),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise NewWineStateError(f"Could not write New Wine log: {path}") from exc


def append_cellar_log(
    run_id: str,
    result: CellarRefillResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable Wine Cellar refill decision.

    Args:
        run_id: Existing execution identifier.
        result: Refill outcome, including previews.
        path: Original append-only audit destination.

    Raises:
        NewWineStateError: The audit record cannot be written.
    """
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "event": "wine_cellar_refill",
        **asdict(result),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise NewWineStateError(f"Could not write New Wine log: {path}") from exc


def _artist_key(name: str) -> str:
    """Normalize a primary artist name for local library-count matching."""
    return name.strip().casefold()


def _load_no_discovery_inventory(
    liked_tracks_path: Path,
    albums_path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Load candidate Spotify ids by primary artist from library mirrors."""
    try:
        raw_tracks = json.loads(liked_tracks_path.read_text(encoding="utf-8"))
        raw_albums = json.loads(albums_path.read_text(encoding="utf-8"))
        if not isinstance(raw_tracks, list) or not isinstance(raw_albums, list):
            raise ValueError("library mirrors must contain JSON arrays")
        tracks = [YourLibraryTrack.model_validate(item) for item in raw_tracks]
        albums = [YourLibraryAlbum.model_validate(item) for item in raw_albums]
    except (OSError, ValueError) as exc:
        raise NewWineStateError(
            "Could not load liked-track and saved-album mirrors for --no-discovery."
        ) from exc
    track_ids: dict[str, list[str]] = {}
    album_ids: dict[str, list[str]] = {}
    for track in tracks:
        track_ids.setdefault(_artist_key(track.artist), []).append(track.spotify_id)
    for album in albums:
        album_ids.setdefault(_artist_key(album.artist), []).append(album.spotify_id)
    return _unique_inventory_ids(track_ids), _unique_inventory_ids(album_ids)


def _live_no_discovery_counts(
    sp: Spotify,
    artist_name: str,
    track_ids_by_artist: dict[str, tuple[str, ...]],
    album_ids_by_artist: dict[str, tuple[str, ...]],
    retry_call: RetryCall,
) -> tuple[int | None, int, bool]:
    """Observe one artist's library affinity through the shared application policy."""
    from spotify_manager.bootstrap.wine_cellar import observe_library_affinity

    key = _artist_key(artist_name)
    return observe_library_affinity(
        sp,
        retry_call,
        artist_name,
        track_ids_by_artist.get(key, ()),
        album_ids_by_artist.get(key, ()),
        LIKED_TRACK_BATCH_SIZE,
        NO_DISCOVERY_MIN_SAVED_ALBUMS,
        NO_DISCOVERY_MIN_LIKED_TRACKS,
    )


def _new_run(
    playlist_id: str,
    tracks: tuple[PlaylistTrack, ...],
    wine_cellar_playlist_id: str | None,
    no_discovery: bool,
    choose_album_endpoints: bool,
) -> dict[str, object]:
    """Build a durable snapshot so each original entry advances once."""
    options = NewWineOptions(
        playlist_id,
        "",
        wine_cellar_playlist_id,
        no_discovery,
        choose_album_endpoints,
        False,
    )
    return new_run(options, tracks, _clock)


def _playlist_track_from_record(raw: object) -> PlaylistTrack:
    """Rebuild one snapshotted source track."""
    return source_from_record(raw)


def _release_from_record(raw: object) -> ReleaseCandidate:
    """Rebuild a release stored in one durable plan."""
    return release_from_record(raw)


def _track_from_record(raw: object) -> ReleaseTrack | None:
    """Rebuild an optional target track stored in one durable plan."""
    return track_from_record(raw)


def _load_local_albums(path: Path) -> list[YourLibraryAlbum]:
    """Load the saved-album mirror used by New Wine reconciliation."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewWineStateError(f"Could not read local albums: {path}") from exc
    if not isinstance(raw, list):
        raise NewWineStateError(f"Local albums file is invalid: {path}")
    return [YourLibraryAlbum.model_validate(item) for item in raw]


def _write_local_albums(albums: list[YourLibraryAlbum], path: Path) -> None:
    """Write and publish the saved-album mirror after reconciliation."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                [album.model_dump(mode="json") for album in albums],
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewWineStateError(f"Could not update local albums: {path}") from exc
    publish_managed_path(path, source="New Wine library reconciliation")
    if path == DEFAULT_ALBUMS_PATH:
        sync_stats_history_counts(total_albums=len(albums))


def _add_local_album(release: ReleaseCandidate, path: Path) -> bool:
    """Add one newly saved release to albums_total_new.json."""
    albums = _load_local_albums(path)
    if any(album.spotify_id == release.spotify_id for album in albums):
        return False
    albums.append(
        YourLibraryAlbum(
            artist=release.primary_artist_name,
            album=release.name,
            uri=release.uri,
        )
    )
    albums.sort(key=album_sort_key)
    _write_local_albums(albums, path)
    return True


def _remove_local_album(album_id: str, path: Path) -> bool:
    """Remove a live-unsaved album from albums_total_new.json when present."""
    albums = _load_local_albums(path)
    updated = [album for album in albums if album.spotify_id != album_id]
    if len(updated) == len(albums):
        return False
    _write_local_albums(updated, path)
    return True


def _record_album_evaluation(
    plan: dict[str, object],
    evaluation: AlbumEvaluation,
) -> None:
    """Store one live keep decision in a durable New Wine plan."""
    record_evaluation(plan, evaluation)


def _add_playlist_track(
    sp: Spotify,
    playlist_id: str,
    track: ReleaseTrack,
    retry_call: RetryCall,
) -> None:
    """Add one track through Spotify's current playlist-items endpoint."""
    retry_call(
        partial(_post_track, sp, playlist_id, track),
        f"adding {track.name} to playlist {playlist_id}",
    )


def _remove_playlist_track(
    sp: Spotify,
    playlist_id: str,
    track: PlaylistTrack,
    retry_call: RetryCall,
) -> None:
    """Remove the source only after all required additions succeed."""
    retry_call(
        partial(_delete_track, sp, playlist_id, track),
        f"removing {track.name} from playlist {playlist_id}",
    )


def _refill_new_wine(
    sp: Spotify,
    new_wine_playlist_id: str,
    wine_cellar_playlist_id: str,
    *,
    no_discovery: bool,
    dry_run: bool,
    retry_call: RetryCall,
    state: dict[str, object],
    run: dict[str, object],
    log_path: Path,
    liked_tracks_path: Path,
    albums_path: Path,
    echo: Echo,
    state_access: RoutineState | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    projected_new_wine_ids: set[str] | None = None,
) -> CellarRefillSummary:
    """Delegate ordered refill effects while retaining the original call contract."""
    from spotify_manager.application.wine_cellar import CellarOptions
    from spotify_manager.bootstrap.wine_cellar import run_cellar_refill

    state_access = state_access or _state_access(state_path, None)
    options = CellarOptions(
        new_wine_playlist_id,
        wine_cellar_playlist_id,
        no_discovery,
        dry_run,
        NEW_WINE_TARGET_SIZE,
        projected_new_wine_ids,
    )
    return run_cellar_refill(
        sp,
        retry_call,
        state_access,
        options,
        state,
        run,
        log_path,
        liked_tracks_path,
        albums_path,
        echo,
    )


def _plan_result(
    source: PlaylistTrack,
    plan: dict[str, object],
    *,
    dry_run: bool,
    album_unsaved: bool = False,
) -> FlushResult:
    """Convert a durable plan into the public result model."""
    return result_from_plan(source, plan, dry_run=dry_run, album_unsaved=album_unsaved)


def _drop_plan(
    release: ReleaseCandidate,
    evaluation: AlbumEvaluation,
    *,
    current_liked: bool,
    consecutive_unliked: int,
    reason: str,
) -> dict[str, object]:
    """Build a durable drop plan with its live album evaluation."""
    return drop_plan(
        release,
        evaluation,
        current_liked=current_liked,
        consecutive_unliked=consecutive_unliked,
        reason=reason,
    )


def flush_new_wine(
    sp: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    endpoint_choice_reader: EndpointChoiceReader | None = None,
    choose_album_endpoints: bool = False,
    wine_cellar_playlist_id: str | None = None,
    no_discovery: bool = False,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    liked_tracks_path: Path = DEFAULT_LIKED_TRACKS_PATH,
    removed_albums_log_path: Path = DEFAULT_REMOVED_ALBUMS_LOG_PATH,
) -> FlushSummary:
    """Advance each snapshotted marker through the injected New Wine workflow.

    Args:
        sp: Caller-owned synchronous Spotify client.
        new_wine_playlist_id: Source and progression destination.
        sauvignon_playlist_id: Completed-album destination.
        choice_reader: Existing release selection callback.
        endpoint_choice_reader: Optional album/EP endpoint callback.
        choose_album_endpoints: Whether endpoint selection is requested.
        wine_cellar_playlist_id: Optional post-flush refill source.
        no_discovery: Whether refill requires existing library affinity.
        dry_run: Preview effects while retaining legacy audit writes.
        year: Existing current-year override.
        echo: Original message sink.
        progress_callback: Optional progress/cancellation callback.
        retry_call: Existing retry callback, or direct invocation.
        state_path: Original namespace path.
        state_service: Optional shared state service.
        log_path: Original audit destination.
        albums_path: Canonical saved-album mirror.
        liked_tracks_path: Canonical liked-track mirror.
        removed_albums_log_path: Removed-album recovery log.

    Returns:
        Original result including pause, resume and refill outcomes.

    Raises:
        NewWineError: Observations, choices or durable records are invalid.
    """
    from spotify_manager.interfaces.operations.new_wine import (
        flush_new_wine as operation,
    )

    return operation(
        sp,
        new_wine_playlist_id,
        sauvignon_playlist_id,
        choice_reader,
        endpoint_choice_reader=endpoint_choice_reader,
        choose_album_endpoints=choose_album_endpoints,
        wine_cellar_playlist_id=wine_cellar_playlist_id,
        no_discovery=no_discovery,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        liked_tracks_path=liked_tracks_path,
        removed_albums_log_path=removed_albums_log_path,
    )


def _affinity_album_statuses(
    sp: Spotify, artist_name: str, batch: list[str], retry_call: RetryCall
) -> tuple[bool, ...]:
    response = retry_call(
        partial(sp.current_user_saved_albums_contains, batch),
        f"checking saved albums for {artist_name}",
    )
    if not isinstance(response, list) or len(response) != len(batch):
        raise NewWineError("Spotify returned invalid saved-album statuses.")
    return tuple(bool(saved) for saved in response)


def _affinity_track_statuses(
    sp: Spotify, artist_name: str, batch: list[str], retry_call: RetryCall
) -> tuple[bool, ...]:
    response = retry_call(
        partial(sp.current_user_saved_tracks_contains, batch),
        f"checking liked tracks for {artist_name}",
    )
    if not isinstance(response, list) or len(response) != len(batch):
        raise NewWineError("Spotify returned invalid Liked Songs statuses.")
    return tuple(bool(liked) for liked in response)


def _clock() -> datetime:
    return datetime.now(UTC)


def _local_year() -> int:
    return datetime.now().year


def _post_track(sp: Spotify, playlist_id: str, track: ReleaseTrack) -> object:
    return sp._post(f"playlists/{playlist_id}/items", payload={"uris": [track.uri]})


def _delete_track(sp: Spotify, playlist_id: str, track: PlaylistTrack) -> object:
    return sp._delete(
        f"playlists/{playlist_id}/items", payload={"items": [{"uri": track.uri}]}
    )


def _saved_for_keep(
    sp: Spotify, release: ReleaseCandidate, retry_call: RetryCall
) -> bool:
    response = retry_call(
        partial(sp.current_user_saved_albums_contains, [release.spotify_id]),
        f"checking whether {release.name} is saved",
    )
    return bool(response[0]) if isinstance(response, list) and response else False


def _saved_for_drop(sp: Spotify, release: ReleaseCandidate, retry: RetryCall) -> bool:
    response = retry(
        partial(sp.current_user_saved_albums_contains, [release.spotify_id]),
        f"checking whether {release.name} is saved",
    )
    return bool(response[0]) if isinstance(response, list) and response else False


def _save_album(sp: Spotify, release: ReleaseCandidate, retry_call: RetryCall) -> None:
    retry_call(
        partial(sp.current_user_saved_albums_add, [release.spotify_id]),
        f"saving {release.name}",
    )


def _unsave_album(sp: Spotify, release: ReleaseCandidate, retry: RetryCall) -> None:
    retry(
        partial(sp.current_user_saved_albums_delete, [release.spotify_id]),
        f"unsaving {release.name}",
    )


def _append_playlist_items(
    tracks: list[PlaylistTrack], raw_items: list[object]
) -> None:
    for raw in raw_items:
        track = _playlist_track(raw)
        if track is not None:
            tracks.append(track)


def _release_track(raw: object, fallback_position: int) -> ReleaseTrack | None:
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not spotify_id or not uri:
        return None
    return ReleaseTrack(
        spotify_id=spotify_id,
        uri=uri,
        name=str(raw.get("name") or spotify_id),
        disc_number=_track_position(raw.get("disc_number"), 1),
        track_number=_track_position(raw.get("track_number"), fallback_position),
    )


def _append_release_items(tracks: list[ReleaseTrack], raw_items: list[object]) -> None:
    for raw in raw_items:
        track = _release_track(raw, len(tracks) + 1)
        if track is not None:
            tracks.append(track)


def _release_track_order(track: ReleaseTrack) -> tuple[int, int]:
    return track.disc_number, track.track_number


def _append_current_year_releases(
    releases: dict[str, ReleaseCandidate],
    raw_items: list[object],
    artist_id: str,
    year: int,
) -> None:
    for raw in raw_items:
        candidate = _release_candidate(raw, target_artist_id=artist_id)
        if _eligible_current_release(candidate, year):
            assert candidate is not None
            releases[candidate.spotify_id] = candidate


def _eligible_current_release(candidate: ReleaseCandidate | None, year: int) -> bool:
    if candidate is None or candidate.release_type == "Compilation":
        return False
    return candidate.release_date.startswith(f"{year:04d}")


def _current_release_order(release: ReleaseCandidate) -> tuple[str, str, str, str]:
    return (
        release.release_date,
        release.release_type,
        release.name.casefold(),
        release.spotify_id,
    )


def _missing_track_ids(track_ids: list[str], cache: dict[str, bool]) -> list[str]:
    missing: dict[str, None] = {}
    for track_id in track_ids:
        if track_id not in cache:
            missing[track_id] = None
    return list(missing)


def _unique_inventory_ids(
    inventory: dict[str, list[str]],
) -> dict[str, tuple[str, ...]]:
    unique = {}
    for artist, spotify_ids in inventory.items():
        unique[artist] = tuple(dict.fromkeys(spotify_ids))
    return unique
