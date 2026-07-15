"""Live-first, restart-safe Spotify library synchronization."""

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep
from typing import Any
from typing import Literal
from typing import Protocol

from pydantic import BaseModel
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines.review_album_limits import TRANSIENT_MAX_ATTEMPTS
from spotify_manager.routines.review_album_limits import TRANSIENT_RETRY_DELAY_SECONDS
from spotify_manager.routines.review_album_limits import SpotifyRateLimitError
from spotify_manager.routines.review_album_limits import SpotifyTransientServerError
from spotify_manager.routines.review_album_limits import current_stats_history_key
from spotify_manager.routines.review_album_limits import retry_spotify_server_errors
from spotify_manager.utils.growth import calculate_growth
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key
from spotify_manager.utils.sorting import track_sort_key


ALBUM_PAGE_LIMIT = 50
TRACK_PAGE_LIMIT = 10
ARTIST_PAGE_LIMIT = 50
LIBRARY_CONTAINS_LIMIT = 40
TRACK_DISCOVERY_STABLE_PAGES = 3
TRACK_DISCOVERY_MAX_PASSES = 3
FALLBACK_HTTP_STATUSES = {400, 403, 404}
ARTIST_IMMEDIATE_FALLBACK_HTTP_STATUSES = {502}
CHECKPOINT_VERSION = 2

ResourceName = Literal["albums", "tracks", "artists"]
Echo = Callable[[str], None]
ProgressCallback = Callable[[ResourceName, int, int | None, str], None]
Sleep = Callable[[float], None]


class SpotifyIdentified(Protocol):
    """Structural type for local models carrying a Spotify id property."""

    @property
    def spotify_id(self) -> str:
        """Return the underlying Spotify id."""
        ...


@dataclass(frozen=True)
class LibrarySyncPaths:
    """Filesystem paths used by one library-sync workspace."""

    files_dir: Path
    your_library: Path
    albums_total: Path
    liked_tracks_total: Path
    liked_tracks_legacy: Path
    artists_total: Path
    stats_history: Path
    checkpoint: Path
    staging_dir: Path
    event_log: Path
    backups_dir: Path

    @classmethod
    def for_files_dir(cls, files_dir: Path) -> LibrarySyncPaths:
        """Build the conventional sync paths beneath ``files_dir``."""
        sync_dir = files_dir / "library_sync"
        return cls(
            files_dir=files_dir,
            your_library=files_dir / "YourLibrary.json",
            albums_total=files_dir / "albums_total_new.json",
            liked_tracks_total=files_dir / "liked_tracks_total.json",
            liked_tracks_legacy=files_dir / "liked_tracks.json",
            artists_total=files_dir / "artists_total.json",
            stats_history=files_dir / "stats_history.json",
            checkpoint=sync_dir / "checkpoint.json",
            staging_dir=sync_dir / "staging",
            event_log=files_dir / "library_sync_log.jsonl",
            backups_dir=files_dir / "library_sync_backups",
        )

    def stage(self, name: str) -> Path:
        """Return an append-only staging path."""
        return self.staging_dir / f"{name}.jsonl"


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_PATHS = LibrarySyncPaths.for_files_dir(FILES_DIR)


@dataclass(frozen=True)
class ResourceSyncSummary:
    """Final source and diff counts for one generated file."""

    resource: ResourceName
    source: str
    previous: int
    current: int
    added: int
    removed: int
    skipped: int = 0


@dataclass(frozen=True)
class LibrarySyncSummary:
    """Final outcome of a completed live-library synchronization."""

    run_id: str
    backup_dir: str
    resources: tuple[ResourceSyncSummary, ...]


class LibrarySyncError(RuntimeError):
    """Base exception for a sync that cannot safely publish output."""


class IncompleteLiveResourceError(LibrarySyncError):
    """Raised when Spotify returns a structurally incomplete page sequence."""


class ArtistVerificationUnavailableError(LibrarySyncError):
    """Raised when fallback artist candidates cannot be verified live."""


class LibrarySyncRestoreError(LibrarySyncError):
    """Raised when a requested sync backup cannot be restored."""


class _FollowedArtistsEndpointUnavailableError(RuntimeError):
    """Signal an expected followed-artists failure without retrying it."""

    def __init__(self, http_status: int) -> None:
        super().__init__("Followed-artists endpoint unavailable")
        self.http_status = http_status


def fetch_followed_artists_page(sp: Spotify, after: object) -> dict:
    """Fetch one artist page, surfacing expected 502s without retrying."""
    try:
        return sp.current_user_followed_artists(
            limit=ARTIST_PAGE_LIMIT,
            after=after,
        )
    except SpotifyException as exc:
        if exc.http_status in ARTIST_IMMEDIATE_FALLBACK_HTTP_STATUSES:
            raise _FollowedArtistsEndpointUnavailableError(exc.http_status) from exc
        raise


def utc_now() -> str:
    """Return a JSON-friendly UTC timestamp."""
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    """Return a sortable filesystem-safe run identifier."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def write_json_atomic(path: Path, value: object) -> None:
    """Write JSON via a neighboring temporary file and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(temporary_path, "w") as output_file:
        json.dump(value, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(path)


def load_json(path: Path, default: object | None = None) -> Any:
    """Load JSON, returning ``default`` only when the file is absent."""
    try:
        with open(path) as input_file:
            return json.load(input_file)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise LibrarySyncError(f"Invalid JSON in {path}.") from exc


def append_json_lines(path: Path, entries: list[dict[str, object]]) -> None:
    """Append JSON objects to a JSON Lines file."""
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as output_file:
        for entry in entries:
            output_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_event(
    paths: LibrarySyncPaths,
    run_id: str,
    event: str,
    **details: object,
) -> None:
    """Append one permanent synchronization audit event."""
    append_json_lines(
        paths.event_log,
        [
            {
                "timestamp": utc_now(),
                "run_id": run_id,
                "event": event,
                **details,
            }
        ],
    )


def write_models(path: Path, models: list[BaseModel]) -> None:
    """Atomically write a generated model list as JSON."""
    write_json_atomic(path, [model.model_dump() for model in models])


def write_models_jsonl(path: Path, models: list[BaseModel]) -> None:
    """Replace a staging file with one model per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(temporary_path, "w") as output_file:
        for model in models:
            output_file.write(json.dumps(model.model_dump(), ensure_ascii=False) + "\n")
    temporary_path.replace(path)


def append_models_jsonl(path: Path, models: list[BaseModel]) -> None:
    """Append models to a restart-safe staging file."""
    append_json_lines(path, [model.model_dump() for model in models])


def load_model_list[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load a normal JSON model list, or return an empty list when absent."""
    raw_items = load_json(path, default=[])
    if not isinstance(raw_items, list):
        raise LibrarySyncError(f"Expected a JSON list in {path}.")
    return [model.model_validate(item) for item in raw_items]


def load_models_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load and de-duplicate a model staging file by Spotify id."""
    if not path.exists():
        return []
    models: list[T] = []
    with open(path) as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                models.append(model.model_validate_json(line))
            except ValueError as exc:
                raise LibrarySyncError(
                    f"Invalid staging data in {path} at line {line_number}."
                ) from exc
    return deduplicate_models(models)


def deduplicate_models[T: SpotifyIdentified](models: list[T]) -> list[T]:
    """De-duplicate Spotify models by id, preferring the latest metadata."""
    by_id: dict[str, T] = {}
    for model in models:
        by_id[model.spotify_id] = model
    return list(by_id.values())


def load_your_library(paths: LibrarySyncPaths) -> YourLibraryFile:
    """Load the export used only for explicit fallback paths."""
    raw_library = load_json(paths.your_library)
    if raw_library is None:
        raise LibrarySyncError(f"Missing fallback export: {paths.your_library}")
    return YourLibraryFile.model_validate(raw_library)


def empty_resource_checkpoint() -> dict[str, object]:
    """Return a new resource checkpoint."""
    return {
        "status": "pending",
        "source": None,
        "offset": 0,
        "after": None,
        "fetched": 0,
        "skipped": 0,
        "total": None,
        "candidate_index": 0,
        "restart_count": 0,
        "discovery_pass": 0,
        "discovery_baseline_count": 0,
        "stable_pages": 0,
        "new_in_pass": 0,
        "last_seen_live_total": None,
    }


def create_checkpoint(
    paths: LibrarySyncPaths,
    fallback_library: YourLibraryFile,
) -> dict[str, object]:
    """Start a fresh sync checkpoint and clear prior staging data."""
    paths.staging_dir.mkdir(parents=True, exist_ok=True)
    for stage_name in (
        "albums",
        "tracks",
        "track_candidates",
        "tracks_verified",
        "artists_live",
        "artist_candidates",
        "artists_verified",
    ):
        paths.stage(stage_name).write_text("")

    run_id = new_run_id()
    checkpoint: dict[str, object] = {
        "version": CHECKPOINT_VERSION,
        "run_id": run_id,
        "status": "in_progress",
        "started_at": utc_now(),
        "completed_at": None,
        "backup_run_id": None,
        "resources": {
            "albums": empty_resource_checkpoint(),
            "tracks": empty_resource_checkpoint(),
            "artists": empty_resource_checkpoint(),
        },
    }
    write_json_atomic(paths.checkpoint, checkpoint)
    append_event(
        paths,
        run_id,
        "run_started",
        fallback_export_counts={
            "albums": len(fallback_library.albums),
            "tracks": len(fallback_library.tracks),
            "artists": len(fallback_library.artists),
        },
    )
    return checkpoint


def load_or_create_checkpoint(
    paths: LibrarySyncPaths,
    fallback_library: YourLibraryFile,
) -> dict[str, object]:
    """Resume an incomplete sync, or create a fresh one."""
    checkpoint = load_json(paths.checkpoint)
    if checkpoint is None or checkpoint.get("status") == "complete":
        return create_checkpoint(paths, fallback_library)
    if checkpoint.get("version") == 1:
        return migrate_v1_checkpoint(paths, checkpoint)
    if checkpoint.get("version") != CHECKPOINT_VERSION:
        raise LibrarySyncError(
            "The saved library-sync checkpoint uses an unsupported version."
        )
    if checkpoint.get("status") not in {"in_progress", "finalizing"}:
        raise LibrarySyncError("The saved library-sync checkpoint is invalid.")
    append_event(paths, str(checkpoint["run_id"]), "run_resumed")
    return checkpoint


def migrate_v1_checkpoint(
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
) -> dict[str, object]:
    """Migrate an interrupted full track scan to the seeded hybrid strategy."""
    if checkpoint.get("status") not in {"in_progress", "finalizing"}:
        raise LibrarySyncError("The saved library-sync checkpoint is invalid.")

    track_state = resource_checkpoint(checkpoint, "tracks")
    reset_tracks = (
        checkpoint.get("status") == "in_progress"
        and track_state.get("status") != "complete"
    )
    if reset_tracks:
        for stage_name in ("tracks", "track_candidates", "tracks_verified"):
            paths.stage(stage_name).parent.mkdir(parents=True, exist_ok=True)
            paths.stage(stage_name).write_text("")
        resources = checkpoint["resources"]
        assert isinstance(resources, dict)
        resources["tracks"] = empty_resource_checkpoint()

    checkpoint["version"] = CHECKPOINT_VERSION
    save_checkpoint(paths, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "checkpoint_migrated",
        from_version=1,
        to_version=CHECKPOINT_VERSION,
        track_scan_reset=reset_tracks,
    )
    return checkpoint


def resource_checkpoint(
    checkpoint: dict[str, object],
    resource: ResourceName,
) -> dict[str, object]:
    """Return a mutable resource checkpoint."""
    resources = checkpoint["resources"]
    assert isinstance(resources, dict)
    value = resources[resource]
    assert isinstance(value, dict)
    return value


def save_checkpoint(paths: LibrarySyncPaths, checkpoint: dict[str, object]) -> None:
    """Persist the current sync position."""
    write_json_atomic(paths.checkpoint, checkpoint)


def update_progress(
    callback: ProgressCallback | None,
    resource: ResourceName,
    checkpoint: dict[str, object],
    description: str,
) -> None:
    """Report one resource's current checkpoint state."""
    if callback is None:
        return
    total_value = checkpoint.get("total")
    total = int(total_value) if isinstance(total_value, int) else None
    callback(resource, int(checkpoint.get("fetched", 0)), total, description)


def validate_completed_count(
    resource: ResourceName,
    models: list[BaseModel],
    state: dict[str, object],
) -> None:
    """Ensure completed staging accounts for Spotify's full reported total."""
    total = state.get("total")
    if not isinstance(total, int):
        raise IncompleteLiveResourceError(
            f"The completed {resource} checkpoint has no total."
        )
    represented = len(models) + int(state.get("skipped", 0))
    if represented != total:
        raise IncompleteLiveResourceError(
            f"Completed {resource} staging accounts for {represented}/{total} "
            "Spotify items; refusing to publish it."
        )


def album_from_saved_item(item: object) -> YourLibraryAlbum | None:
    """Convert one Spotify saved-album item to the local mirror model."""
    if not isinstance(item, dict) or not isinstance(item.get("album"), dict):
        return None
    album = item["album"]
    artists = album.get("artists")
    if not isinstance(artists, list) or not artists or not isinstance(artists[0], dict):
        return None
    spotify_id = str(album.get("id") or "").strip()
    if not spotify_id:
        return None
    return YourLibraryAlbum(
        artist=str(artists[0].get("name") or "Unknown artist"),
        album=str(album.get("name") or spotify_id),
        uri=str(album.get("uri") or f"spotify:album:{spotify_id}"),
    )


def track_from_saved_item(item: object) -> YourLibraryTrack | None:
    """Convert one Spotify saved-track item to the local mirror model."""
    if not isinstance(item, dict) or not isinstance(item.get("track"), dict):
        return None
    track = item["track"]
    artists = track.get("artists")
    album = track.get("album")
    if not isinstance(artists, list) or not artists or not isinstance(artists[0], dict):
        return None
    if not isinstance(album, dict):
        return None
    spotify_id = str(track.get("id") or "").strip()
    if not spotify_id:
        return None
    return YourLibraryTrack(
        artist=str(artists[0].get("name") or "Unknown artist"),
        album=str(album.get("name") or "Unknown album"),
        track=str(track.get("name") or spotify_id),
        uri=str(track.get("uri") or f"spotify:track:{spotify_id}"),
    )


def check_library_contains(sp: Spotify, uris: list[str]) -> list[bool]:
    """Check saved-item status through Spotify's current generic endpoint."""
    return list(sp._get("me/library/contains", uris=",".join(uris)))


def existing_track_mirror(paths: LibrarySyncPaths) -> list[YourLibraryTrack]:
    """Load the newest available local liked-track mirror."""
    source_path = (
        paths.liked_tracks_total
        if paths.liked_tracks_total.exists()
        else paths.liked_tracks_legacy
    )
    return load_model_list(source_path, YourLibraryTrack)


def begin_track_discovery(
    state: dict[str, object],
    candidate_count: int,
    discovery_pass: int,
) -> None:
    """Reset the short newest-track scan for one discovery pass."""
    state.update(
        {
            "status": "discovering_head",
            "offset": 0,
            "discovery_pass": discovery_pass,
            "discovery_baseline_count": candidate_count,
            "stable_pages": 0,
            "new_in_pass": 0,
            "total": candidate_count,
        }
    )


def prepare_track_sync(
    fallback_tracks: list[YourLibraryTrack],
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    progress_callback: ProgressCallback | None,
) -> None:
    """Seed track candidates from the export and the previous local mirror."""
    existing_tracks = existing_track_mirror(paths)
    candidates = deduplicate_models([*existing_tracks, *fallback_tracks])
    candidates.sort(key=track_sort_key)
    write_models_jsonl(paths.stage("track_candidates"), candidates)
    write_models_jsonl(paths.stage("tracks_verified"), [])
    write_models_jsonl(paths.stage("tracks"), [])

    state = resource_checkpoint(checkpoint, "tracks")
    state.update(
        {
            "source": "seeded_live_verified",
            "fetched": 0,
            "skipped": 0,
            "candidate_index": 0,
            "last_seen_live_total": None,
        }
    )
    begin_track_discovery(state, len(candidates), discovery_pass=1)
    save_checkpoint(paths, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "track_candidates_seeded",
        existing_count=len(existing_tracks),
        export_count=len(fallback_tracks),
        candidate_count=len(candidates),
    )
    update_progress(
        progress_callback,
        "tracks",
        state,
        "Discovering recent additions",
    )


def complete_verified_track_sync(
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryTrack]:
    """Publish verified staging as the completed track resource."""
    candidates = load_models_jsonl(paths.stage("track_candidates"), YourLibraryTrack)
    tracks = load_models_jsonl(paths.stage("tracks_verified"), YourLibraryTrack)
    state = resource_checkpoint(checkpoint, "tracks")
    state.update(
        {
            "status": "complete",
            "fetched": len(candidates),
            "skipped": len(candidates) - len(tracks),
            "total": len(candidates),
        }
    )
    write_models_jsonl(paths.stage("tracks"), tracks)
    save_checkpoint(paths, checkpoint)
    validate_completed_count("tracks", tracks, state)
    update_progress(progress_callback, "tracks", state, "Complete")
    return tracks


def complete_unverified_track_fallback(
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    http_status: int,
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryTrack]:
    """Use merged candidates when Spotify cannot verify their saved status."""
    candidates = load_models_jsonl(paths.stage("track_candidates"), YourLibraryTrack)
    state = resource_checkpoint(checkpoint, "tracks")
    state.update(
        {
            "status": "complete",
            "source": "merged_track_fallback",
            "fetched": len(candidates),
            "skipped": 0,
            "total": len(candidates),
        }
    )
    write_models_jsonl(paths.stage("tracks"), candidates)
    save_checkpoint(paths, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "track_verification_fallback_activated",
        http_status=http_status,
        candidate_count=len(candidates),
    )
    echo(
        "Live liked-track verification unavailable "
        f"({http_status}); using the merged export/local candidates."
    )
    update_progress(progress_callback, "tracks", state, "Fallback complete")
    return candidates


def discover_recent_tracks(
    sp: Spotify,
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    retry_call: Callable[[Callable[[], object], str], object],
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryTrack] | None:
    """Scan only the newest pages until they overlap a stable seeded boundary."""
    state = resource_checkpoint(checkpoint, "tracks")
    candidates = load_models_jsonl(paths.stage("track_candidates"), YourLibraryTrack)
    baseline_count = int(state["discovery_baseline_count"])
    if baseline_count > len(candidates):
        raise LibrarySyncError("The track discovery checkpoint is inconsistent.")
    baseline_ids = {candidate.spotify_id for candidate in candidates[:baseline_count]}
    candidate_ids = {candidate.spotify_id for candidate in candidates}
    state["new_in_pass"] = max(
        int(state["new_in_pass"]),
        len(candidates) - baseline_count,
    )

    while state["status"] == "discovering_head":
        offset = int(state["offset"])
        discovery_pass = int(state["discovery_pass"])
        try:
            response = retry_call(
                partial(
                    sp.current_user_saved_tracks, limit=TRACK_PAGE_LIMIT, offset=offset
                ),
                f"discovering recent liked tracks at offset {offset}",
            )
        except SpotifyException as exc:
            if exc.http_status not in FALLBACK_HTTP_STATUSES:
                raise
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "track_discovery_unavailable",
                http_status=exc.http_status,
                discovery_pass=discovery_pass,
            )
            if discovery_pass == 1:
                state["source"] = "seeded_live_verified_no_discovery"
                state["status"] = "verifying_candidates"
                save_checkpoint(paths, checkpoint)
                echo(
                    "Recent liked-track discovery unavailable "
                    f"({exc.http_status}); verifying the seeded candidates."
                )
                return None
            echo(
                "Final liked-track discovery unavailable "
                f"({exc.http_status}); keeping the already verified result."
            )
            return complete_verified_track_sync(
                paths,
                checkpoint,
                progress_callback,
            )

        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise IncompleteLiveResourceError(
                f"Spotify returned an invalid tracks page at offset {offset}."
            )
        raw_items = response["items"]
        response_offset = response.get("offset", offset)
        if response_offset != offset:
            raise IncompleteLiveResourceError(
                f"Spotify returned tracks offset {response_offset}; expected {offset}."
            )
        total = response.get("total")
        if not isinstance(total, int) or total < 0:
            raise IncompleteLiveResourceError(
                f"Spotify omitted the total tracks count at offset {offset}."
            )
        converted = [track_from_saved_item(item) for item in raw_items]
        if any(track is None for track in converted):
            raise IncompleteLiveResourceError(
                f"Spotify returned an incomplete track at offset {offset}."
            )
        page_tracks = [track for track in converted if track is not None]
        page_has_unseeded_track = any(
            track.spotify_id not in baseline_ids for track in page_tracks
        )
        new_tracks = [
            track for track in page_tracks if track.spotify_id not in candidate_ids
        ]
        append_models_jsonl(paths.stage("track_candidates"), new_tracks)
        candidate_ids.update(track.spotify_id for track in new_tracks)
        candidates.extend(new_tracks)

        state["new_in_pass"] = len(candidates) - baseline_count
        state["stable_pages"] = (
            0 if page_has_unseeded_track else int(state["stable_pages"]) + 1
        )
        state["offset"] = offset + len(raw_items)
        state["total"] = len(candidates)
        state["last_seen_live_total"] = total
        has_next = bool(response.get("next"))
        if not raw_items and has_next:
            raise IncompleteLiveResourceError(
                "Spotify returned an empty tracks page with a next link."
            )
        reached_boundary = int(state["stable_pages"]) >= TRACK_DISCOVERY_STABLE_PAGES
        pass_complete = not has_next or reached_boundary
        if pass_complete:
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "track_discovery_completed",
                discovery_pass=discovery_pass,
                scanned=int(state["offset"]),
                new_tracks=int(state["new_in_pass"]),
                live_total=total,
                stopped_at_stable_boundary=reached_boundary,
            )
            if discovery_pass > 1 and int(state["new_in_pass"]) == 0:
                save_checkpoint(paths, checkpoint)
                return complete_verified_track_sync(
                    paths,
                    checkpoint,
                    progress_callback,
                )
            state["status"] = "verifying_candidates"

        save_checkpoint(paths, checkpoint)
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "track_discovery_page_fetched",
            discovery_pass=discovery_pass,
            offset=offset,
            received=len(raw_items),
            new_tracks=len(new_tracks),
            live_total=total,
        )
        update_progress(
            progress_callback,
            "tracks",
            state,
            "Discovering recent additions",
        )

    return None


def verify_track_candidates(
    sp: Spotify,
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    retry_call: Callable[[Callable[[], object], str], object],
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryTrack] | None:
    """Live-check seeded track candidates in 40-URI batches."""
    state = resource_checkpoint(checkpoint, "tracks")
    candidates = load_models_jsonl(paths.stage("track_candidates"), YourLibraryTrack)
    state["total"] = len(candidates)

    while int(state["candidate_index"]) < len(candidates):
        start = int(state["candidate_index"])
        batch = candidates[start : start + LIBRARY_CONTAINS_LIMIT]
        try:
            response = retry_call(
                partial(check_library_contains, sp, [track.uri for track in batch]),
                f"verifying liked tracks {start + 1}-{start + len(batch)}",
            )
        except SpotifyException as exc:
            if exc.http_status not in FALLBACK_HTTP_STATUSES:
                raise
            return complete_unverified_track_fallback(
                paths,
                checkpoint,
                exc.http_status,
                echo,
                progress_callback,
            )

        statuses = list(response)
        if len(statuses) != len(batch) or any(
            not isinstance(status, bool) for status in statuses
        ):
            raise IncompleteLiveResourceError(
                "Spotify returned an incomplete liked-track verification batch."
            )
        saved_tracks = [
            track for track, is_saved in zip(batch, statuses, strict=True) if is_saved
        ]
        append_models_jsonl(paths.stage("tracks_verified"), saved_tracks)
        state["candidate_index"] = start + len(batch)
        state["fetched"] = int(state["candidate_index"])
        state["skipped"] = int(state["skipped"]) + len(batch) - len(saved_tracks)
        save_checkpoint(paths, checkpoint)
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "track_candidates_verified",
            start=start,
            checked=len(batch),
            saved=len(saved_tracks),
        )
        update_progress(
            progress_callback,
            "tracks",
            state,
            "Verifying seeded tracks",
        )

    discovery_pass = int(state["discovery_pass"])
    if discovery_pass >= TRACK_DISCOVERY_MAX_PASSES:
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "track_discovery_pass_limit_reached",
            discovery_pass=discovery_pass,
        )
        return complete_verified_track_sync(
            paths,
            checkpoint,
            progress_callback,
        )

    begin_track_discovery(
        state,
        len(candidates),
        discovery_pass=discovery_pass + 1,
    )
    save_checkpoint(paths, checkpoint)
    return None


def sync_tracks(
    sp: Spotify,
    fallback_tracks: list[YourLibraryTrack],
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    retry_call: Callable[[Callable[[], object], str], object],
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryTrack]:
    """Synchronize tracks from seeded data plus targeted live checks."""
    state = resource_checkpoint(checkpoint, "tracks")
    if state["status"] == "complete":
        tracks = load_models_jsonl(paths.stage("tracks"), YourLibraryTrack)
        validate_completed_count("tracks", tracks, state)
        return tracks
    if state["status"] == "pending":
        prepare_track_sync(
            fallback_tracks,
            paths,
            checkpoint,
            progress_callback,
        )

    while state["status"] != "complete":
        if state["status"] == "discovering_head":
            result = discover_recent_tracks(
                sp,
                paths,
                checkpoint,
                retry_call,
                echo,
                progress_callback,
            )
        elif state["status"] == "verifying_candidates":
            result = verify_track_candidates(
                sp,
                paths,
                checkpoint,
                retry_call,
                echo,
                progress_callback,
            )
        else:
            raise LibrarySyncError(
                f"The saved track-sync status is invalid: {state['status']}."
            )
        if result is not None:
            return result

    tracks = load_models_jsonl(paths.stage("tracks"), YourLibraryTrack)
    validate_completed_count("tracks", tracks, state)
    return tracks


def artist_from_api_item(item: object) -> YourLibraryArtist | None:
    """Convert one Spotify artist object to the local mirror model."""
    if not isinstance(item, dict):
        return None
    spotify_id = str(item.get("id") or "").strip()
    if not spotify_id:
        return None
    return YourLibraryArtist(
        name=str(item.get("name") or spotify_id),
        uri=str(item.get("uri") or f"spotify:artist:{spotify_id}"),
    )


def fallback_resource(
    resource: ResourceName,
    models: list[BaseModel],
    stage_path: Path,
    state: dict[str, object],
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    http_status: int,
    echo: Echo,
) -> None:
    """Replace partial live staging with explicit export fallback data."""
    write_models_jsonl(stage_path, models)
    state.update(
        {
            "status": "complete",
            "source": "export_fallback",
            "offset": len(models),
            "fetched": len(models),
            "skipped": 0,
            "total": len(models),
        }
    )
    save_checkpoint(paths, checkpoint)
    run_id = str(checkpoint["run_id"])
    append_event(
        paths,
        run_id,
        "fallback_activated",
        resource=resource,
        http_status=http_status,
        fallback_count=len(models),
    )
    echo(
        f"{resource.title()} live endpoint unavailable ({http_status}); "
        "using YourLibrary.json fallback."
    )


def sync_offset_resource[T: BaseModel](
    sp: Spotify,
    resource: Literal["albums", "tracks"],
    endpoint: Callable[..., dict],
    page_limit: int,
    converter: Callable[[object], T | None],
    model_type: type[T],
    fallback_models: list[T],
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    retry_call: Callable[[Callable[[], object], str], object],
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> list[T]:
    """Collect an offset-paginated resource with restart-safe staging."""
    state = resource_checkpoint(checkpoint, resource)
    stage_path = paths.stage(resource)
    if state["status"] == "complete":
        models = load_models_jsonl(stage_path, model_type)
        validate_completed_count(resource, models, state)
        return models

    state["status"] = "collecting_live"
    state["source"] = "live_api"
    save_checkpoint(paths, checkpoint)

    while state["status"] != "complete":
        offset = int(state["offset"])
        try:
            response = retry_call(
                partial(endpoint, limit=page_limit, offset=offset),
                f"fetching {resource} at offset {offset}",
            )
        except SpotifyException as exc:
            if exc.http_status not in FALLBACK_HTTP_STATUSES:
                raise
            fallback_resource(
                resource,
                fallback_models,
                stage_path,
                state,
                paths,
                checkpoint,
                exc.http_status,
                echo,
            )
            break

        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise IncompleteLiveResourceError(
                f"Spotify returned an invalid {resource} page at offset {offset}."
            )
        raw_items = response["items"]
        total = response.get("total")
        if not isinstance(total, int) or total < 0:
            raise IncompleteLiveResourceError(
                f"Spotify omitted the total {resource} count at offset {offset}."
            )
        response_offset = response.get("offset", offset)
        if response_offset != offset:
            raise IncompleteLiveResourceError(
                f"Spotify returned {resource} offset {response_offset}; "
                f"expected {offset}."
            )

        expected_total = state.get("total")
        if expected_total is not None and expected_total != total:
            if int(state["restart_count"]) >= 2:
                raise IncompleteLiveResourceError(
                    f"Spotify's {resource} total kept changing during synchronization."
                )
            write_models_jsonl(stage_path, [])
            state.update(
                {
                    "offset": 0,
                    "fetched": 0,
                    "skipped": 0,
                    "total": total,
                    "restart_count": int(state["restart_count"]) + 1,
                }
            )
            save_checkpoint(paths, checkpoint)
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "resource_restarted",
                resource=resource,
                reason="live_total_changed",
                new_total=total,
            )
            continue

        state["total"] = total
        converted = [model for item in raw_items if (model := converter(item))]
        skipped = len(raw_items) - len(converted)
        append_models_jsonl(stage_path, converted)
        next_offset = offset + len(raw_items)
        state["offset"] = next_offset
        state["fetched"] = int(state["fetched"]) + len(raw_items)
        state["skipped"] = int(state["skipped"]) + skipped

        has_next = bool(response.get("next"))
        if not has_next:
            if next_offset < total:
                raise IncompleteLiveResourceError(
                    f"Spotify ended {resource} pagination at {next_offset}/{total}."
                )
            state["status"] = "complete"

        save_checkpoint(paths, checkpoint)
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "resource_page_fetched",
            resource=resource,
            offset=offset,
            received=len(raw_items),
            skipped=skipped,
            total=total,
        )
        update_progress(
            progress_callback,
            resource,
            state,
            "Live API" if state["status"] != "complete" else "Complete",
        )

        if not raw_items and has_next:
            raise IncompleteLiveResourceError(
                f"Spotify returned an empty {resource} page with a next link."
            )

    models = load_models_jsonl(stage_path, model_type)
    validate_completed_count(resource, models, state)
    update_progress(progress_callback, resource, state, "Complete")
    return models


def prepare_artist_fallback(
    fallback_library: YourLibraryFile,
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    http_status: int,
    echo: Echo,
) -> list[YourLibraryArtist]:
    """Build a stable artist candidate union for live follow verification."""
    existing_artists = load_model_list(paths.artists_total, YourLibraryArtist)
    partial_live_artists = load_models_jsonl(
        paths.stage("artists_live"), YourLibraryArtist
    )
    candidates = deduplicate_models(
        [*existing_artists, *fallback_library.artists, *partial_live_artists]
    )
    candidates.sort(key=artist_sort_key)
    write_models_jsonl(paths.stage("artist_candidates"), candidates)
    write_models_jsonl(paths.stage("artists_verified"), [])

    state = resource_checkpoint(checkpoint, "artists")
    state.update(
        {
            "status": "verifying_fallback",
            "source": "verified_fallback",
            "candidate_index": 0,
            "fetched": 0,
            "skipped": 0,
            "total": len(candidates),
        }
    )
    save_checkpoint(paths, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "artist_fallback_activated",
        http_status=http_status,
        candidates=len(candidates),
        existing_candidates=len(existing_artists),
        export_candidates=len(fallback_library.artists),
        partial_live_candidates=len(partial_live_artists),
    )
    echo(
        f"Followed-artists endpoint unavailable ({http_status}); "
        f"live-verifying {len(candidates)} merged candidates."
    )
    return candidates


def verify_artist_candidates(
    sp: Spotify,
    candidates: list[YourLibraryArtist],
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    retry_call: Callable[[Callable[[], object], str], object],
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryArtist]:
    """Keep only merged artist candidates confirmed followed by Spotify."""
    state = resource_checkpoint(checkpoint, "artists")
    while int(state["candidate_index"]) < len(candidates):
        start = int(state["candidate_index"])
        batch = candidates[start : start + LIBRARY_CONTAINS_LIMIT]
        ids = [artist.spotify_id for artist in batch]
        try:
            response = retry_call(
                partial(sp.current_user_following_artists, ids),
                f"verifying followed artists {start + 1}-{start + len(batch)}",
            )
        except SpotifyException as exc:
            raise ArtistVerificationUnavailableError(
                "The merged artist fallback cannot be published because Spotify "
                f"could not verify follow status (HTTP {exc.http_status})."
            ) from exc

        statuses = list(response)
        if len(statuses) != len(batch):
            raise ArtistVerificationUnavailableError(
                "Spotify returned an incomplete artist-follow verification batch."
            )
        followed = [
            artist
            for artist, is_followed in zip(batch, statuses, strict=True)
            if is_followed
        ]
        append_models_jsonl(paths.stage("artists_verified"), followed)
        state["candidate_index"] = start + len(batch)
        state["fetched"] = int(state["candidate_index"])
        state["skipped"] = int(state["skipped"]) + len(batch) - len(followed)
        save_checkpoint(paths, checkpoint)
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "artist_candidates_verified",
            start=start,
            checked=len(batch),
            followed=len(followed),
        )
        update_progress(
            progress_callback,
            "artists",
            state,
            "Verifying merged fallback",
        )

    state["status"] = "complete"
    save_checkpoint(paths, checkpoint)
    update_progress(progress_callback, "artists", state, "Complete")
    artists = load_models_jsonl(paths.stage("artists_verified"), YourLibraryArtist)
    validate_completed_count("artists", artists, state)
    return artists


def sync_artists(
    sp: Spotify,
    fallback_library: YourLibraryFile,
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    retry_call: Callable[[Callable[[], object], str], object],
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> list[YourLibraryArtist]:
    """Collect followed artists live or verify a merged local/export fallback."""
    state = resource_checkpoint(checkpoint, "artists")
    if state["status"] == "complete":
        stage_name = (
            "artists_live" if state["source"] == "live_api" else "artists_verified"
        )
        artists = load_models_jsonl(paths.stage(stage_name), YourLibraryArtist)
        validate_completed_count("artists", artists, state)
        return artists
    if state["status"] == "verifying_fallback":
        candidates = load_models_jsonl(
            paths.stage("artist_candidates"), YourLibraryArtist
        )
        return verify_artist_candidates(
            sp,
            candidates,
            paths,
            checkpoint,
            retry_call,
            progress_callback,
        )

    state["status"] = "collecting_live"
    state["source"] = "live_api"
    save_checkpoint(paths, checkpoint)
    while state["status"] == "collecting_live":
        after = state.get("after")

        try:
            response = retry_call(
                partial(fetch_followed_artists_page, sp, after),
                "fetching followed artists",
            )
        except _FollowedArtistsEndpointUnavailableError as exc:
            candidates = prepare_artist_fallback(
                fallback_library,
                paths,
                checkpoint,
                exc.http_status,
                echo,
            )
            return verify_artist_candidates(
                sp,
                candidates,
                paths,
                checkpoint,
                retry_call,
                progress_callback,
            )
        except SpotifyException as exc:
            if exc.http_status not in FALLBACK_HTTP_STATUSES:
                raise
            candidates = prepare_artist_fallback(
                fallback_library,
                paths,
                checkpoint,
                exc.http_status,
                echo,
            )
            return verify_artist_candidates(
                sp,
                candidates,
                paths,
                checkpoint,
                retry_call,
                progress_callback,
            )

        artist_page = response.get("artists") if isinstance(response, dict) else None
        if not isinstance(artist_page, dict) or not isinstance(
            artist_page.get("items"), list
        ):
            raise IncompleteLiveResourceError(
                "Spotify returned an invalid followed-artists page."
            )
        raw_items = artist_page["items"]
        total = artist_page.get("total")
        if not isinstance(total, int) or total < 0:
            raise IncompleteLiveResourceError(
                "Spotify omitted the total followed-artists count."
            )

        expected_total = state.get("total")
        if expected_total is not None and expected_total != total:
            if int(state["restart_count"]) >= 2:
                raise IncompleteLiveResourceError(
                    "Spotify's followed-artist total kept changing during sync."
                )
            write_models_jsonl(paths.stage("artists_live"), [])
            state.update(
                {
                    "after": None,
                    "fetched": 0,
                    "skipped": 0,
                    "total": total,
                    "restart_count": int(state["restart_count"]) + 1,
                }
            )
            save_checkpoint(paths, checkpoint)
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "resource_restarted",
                resource="artists",
                reason="live_total_changed",
                new_total=total,
            )
            continue

        state["total"] = total
        converted = [
            artist for item in raw_items if (artist := artist_from_api_item(item))
        ]
        skipped = len(raw_items) - len(converted)
        append_models_jsonl(paths.stage("artists_live"), converted)
        state["fetched"] = int(state["fetched"]) + len(raw_items)
        state["skipped"] = int(state["skipped"]) + skipped

        has_next = bool(artist_page.get("next"))
        cursors = artist_page.get("cursors")
        next_after = cursors.get("after") if isinstance(cursors, dict) else None
        if has_next and not next_after:
            raise IncompleteLiveResourceError(
                "Spotify returned a followed-artists next page without a cursor."
            )
        state["after"] = next_after
        if not has_next:
            if int(state["fetched"]) < total:
                raise IncompleteLiveResourceError(
                    "Spotify ended followed-artist pagination before its total."
                )
            state["status"] = "complete"

        save_checkpoint(paths, checkpoint)
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "resource_page_fetched",
            resource="artists",
            received=len(raw_items),
            skipped=skipped,
            total=total,
        )
        update_progress(
            progress_callback,
            "artists",
            state,
            "Live API" if state["status"] != "complete" else "Complete",
        )

    artists = load_models_jsonl(paths.stage("artists_live"), YourLibraryArtist)
    validate_completed_count("artists", artists, state)
    return artists


def model_diff[T: SpotifyIdentified](
    previous: list[T],
    current: list[T],
) -> tuple[list[T], list[T]]:
    """Return models added to and removed from a Spotify-id keyed mirror."""
    previous_by_id = {item.spotify_id: item for item in previous}
    current_by_id = {item.spotify_id: item for item in current}
    added = [
        item
        for spotify_id, item in current_by_id.items()
        if spotify_id not in previous_by_id
    ]
    removed = [
        item
        for spotify_id, item in previous_by_id.items()
        if spotify_id not in current_by_id
    ]
    return added, removed


def stats_report_for_sync(
    previous_albums: list[YourLibraryAlbum],
    albums: list[YourLibraryAlbum],
    previous_tracks: list[YourLibraryTrack],
    tracks: list[YourLibraryTrack],
    previous_artists: list[YourLibraryArtist],
    artists: list[YourLibraryArtist],
) -> StatsReport:
    """Build a stats report from the exact pre/post publication mirrors."""
    added_albums, removed_albums = model_diff(previous_albums, albums)
    added_tracks, removed_tracks = model_diff(previous_tracks, tracks)
    added_artists, removed_artists = model_diff(previous_artists, artists)
    artist_count = max(1, len(artists))
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=len(albums),
            removed_albums=len(removed_albums),
            added_albums=len(added_albums),
            growth=calculate_growth(len(albums), len(previous_albums)),
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=len(artists),
            removed_artists=len(removed_artists),
            added_artists=len(added_artists),
            growth=calculate_growth(len(artists), len(previous_artists)),
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=len(tracks),
            removed_tracks=len(removed_tracks),
            added_tracks=len(added_tracks),
            growth=calculate_growth(len(tracks), len(previous_tracks)),
        ),
        avg_albums_per_artists=len(albums) // artist_count,
        avg_liked_tracks_per_artists=len(tracks) // artist_count,
    )


def resource_summary(
    resource: ResourceName,
    source: str,
    previous: list[BaseModel],
    current: list[BaseModel],
    skipped: int,
) -> ResourceSyncSummary:
    """Build one resource summary and exact diff counts."""
    added, removed = model_diff(previous, current)
    return ResourceSyncSummary(
        resource=resource,
        source=source,
        previous=len(previous),
        current=len(current),
        added=len(added),
        removed=len(removed),
        skipped=skipped,
    )


def backup_targets(paths: LibrarySyncPaths) -> dict[str, Path]:
    """Return every generated file changed by final publication."""
    return {
        "albums": paths.albums_total,
        "tracks": paths.liked_tracks_total,
        "artists": paths.artists_total,
        "stats_history": paths.stats_history,
    }


def create_backup_manifest(
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
    previous_albums: list[YourLibraryAlbum],
    albums: list[YourLibraryAlbum],
    previous_tracks: list[YourLibraryTrack],
    tracks: list[YourLibraryTrack],
    previous_artists: list[YourLibraryArtist],
    artists: list[YourLibraryArtist],
    report: StatsReport,
    summaries: tuple[ResourceSyncSummary, ...],
) -> dict[str, object]:
    """Snapshot generated files and record exact changes for review/undo."""
    run_id = str(checkpoint["run_id"])
    backup_dir = paths.backups_dir / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    targets: dict[str, dict[str, object]] = {}
    for name, target_path in backup_targets(paths).items():
        backup_name = f"{name}.before.json"
        existed = target_path.exists()
        if existed:
            shutil.copy2(target_path, backup_dir / backup_name)
        targets[name] = {
            "target_name": target_path.name,
            "existed": existed,
            "backup_file": backup_name if existed else None,
        }

    changes: dict[str, object] = {}
    for name, before, after in (
        ("albums", previous_albums, albums),
        ("tracks", previous_tracks, tracks),
        ("artists", previous_artists, artists),
    ):
        added, removed = model_diff(before, after)
        changes[name] = {
            "added": [item.model_dump() for item in added],
            "removed": [item.model_dump() for item in removed],
        }

    manifest: dict[str, object] = {
        "version": 1,
        "run_id": run_id,
        "created_at": utc_now(),
        "targets": targets,
        "changes": changes,
        "stats_report": report.model_dump(),
        "summaries": [asdict(summary) for summary in summaries],
    }
    write_json_atomic(backup_dir / "manifest.json", manifest)
    append_event(
        paths,
        run_id,
        "backup_created",
        backup_dir=str(backup_dir),
    )
    return manifest


def load_pre_sync_stats_history(
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
) -> dict[str, object]:
    """Load stats from the backup so interrupted finalization is repeatable."""
    backup_run_id = str(checkpoint["backup_run_id"])
    backup_dir = paths.backups_dir / backup_run_id
    manifest = load_json(backup_dir / "manifest.json")
    target = manifest["targets"]["stats_history"]
    if not target["existed"]:
        return {}
    raw_history = load_json(backup_dir / str(target["backup_file"]), default={})
    if not isinstance(raw_history, dict):
        raise LibrarySyncError("The backed-up stats history is invalid.")
    return raw_history


def finalize_sync(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
    paths: LibrarySyncPaths,
    checkpoint: dict[str, object],
) -> LibrarySyncSummary:
    """Atomically publish completed staging data and create an undo snapshot."""
    albums = sorted(deduplicate_models(albums), key=album_sort_key)
    tracks = sorted(deduplicate_models(tracks), key=track_sort_key)
    artists = sorted(deduplicate_models(artists), key=artist_sort_key)

    if checkpoint["status"] != "finalizing":
        previous_albums = load_model_list(paths.albums_total, YourLibraryAlbum)
        previous_track_path = (
            paths.liked_tracks_total
            if paths.liked_tracks_total.exists()
            else paths.liked_tracks_legacy
        )
        previous_tracks = load_model_list(previous_track_path, YourLibraryTrack)
        previous_artists = load_model_list(paths.artists_total, YourLibraryArtist)
        report = stats_report_for_sync(
            previous_albums,
            albums,
            previous_tracks,
            tracks,
            previous_artists,
            artists,
        )
        resources = checkpoint["resources"]
        assert isinstance(resources, dict)
        summaries = (
            resource_summary(
                "albums",
                str(resources["albums"]["source"]),
                previous_albums,
                albums,
                int(resources["albums"]["skipped"]),
            ),
            resource_summary(
                "tracks",
                str(resources["tracks"]["source"]),
                previous_tracks,
                tracks,
                int(resources["tracks"]["skipped"]),
            ),
            resource_summary(
                "artists",
                str(resources["artists"]["source"]),
                previous_artists,
                artists,
                int(resources["artists"]["skipped"]),
            ),
        )
        manifest = create_backup_manifest(
            paths,
            checkpoint,
            previous_albums,
            albums,
            previous_tracks,
            tracks,
            previous_artists,
            artists,
            report,
            summaries,
        )
        checkpoint["status"] = "finalizing"
        checkpoint["backup_run_id"] = checkpoint["run_id"]
        save_checkpoint(paths, checkpoint)
    else:
        backup_dir = paths.backups_dir / str(checkpoint["backup_run_id"])
        manifest = load_json(backup_dir / "manifest.json")
        report = StatsReport.model_validate(manifest["stats_report"])
        summaries = tuple(
            ResourceSyncSummary(**summary) for summary in manifest["summaries"]
        )

    write_models(paths.albums_total, albums)
    write_models(paths.liked_tracks_total, tracks)
    write_models(paths.artists_total, artists)
    stats_history = load_pre_sync_stats_history(paths, checkpoint)
    stats_history[current_stats_history_key()] = report.model_dump()
    write_json_atomic(paths.stats_history, stats_history)

    checkpoint["status"] = "complete"
    checkpoint["completed_at"] = utc_now()
    save_checkpoint(paths, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "run_completed",
        backup_dir=str(paths.backups_dir / str(checkpoint["backup_run_id"])),
        summaries=[asdict(summary) for summary in summaries],
    )
    return LibrarySyncSummary(
        run_id=str(checkpoint["run_id"]),
        backup_dir=str(paths.backups_dir / str(checkpoint["backup_run_id"])),
        resources=summaries,
    )


def analyse_library_routine(
    sp: Spotify,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    paths: LibrarySyncPaths = DEFAULT_PATHS,
    sleep: Sleep = default_sleep,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
) -> LibrarySyncSummary:
    """Build local library mirrors from Spotify, with cautious fallbacks."""
    fallback_library = load_your_library(paths)
    checkpoint = load_or_create_checkpoint(paths, fallback_library)

    def retry_call[T](operation: Callable[[], T], description: str) -> T:
        return retry_spotify_server_errors(
            operation,
            description,
            echo,
            sleep,
            transient_retry_delay_seconds,
            transient_max_attempts,
        )

    if checkpoint["status"] == "finalizing":
        albums = load_models_jsonl(paths.stage("albums"), YourLibraryAlbum)
        tracks = load_models_jsonl(paths.stage("tracks"), YourLibraryTrack)
        artist_state = resource_checkpoint(checkpoint, "artists")
        artist_stage = (
            "artists_live"
            if artist_state["source"] == "live_api"
            else "artists_verified"
        )
        artists = load_models_jsonl(paths.stage(artist_stage), YourLibraryArtist)
        return finalize_sync(albums, tracks, artists, paths, checkpoint)

    albums = sync_offset_resource(
        sp,
        "albums",
        sp.current_user_saved_albums,
        ALBUM_PAGE_LIMIT,
        album_from_saved_item,
        YourLibraryAlbum,
        fallback_library.albums,
        paths,
        checkpoint,
        retry_call,
        echo,
        progress_callback,
    )
    tracks = sync_tracks(
        sp,
        fallback_library.tracks,
        paths,
        checkpoint,
        retry_call,
        echo,
        progress_callback,
    )
    artists = sync_artists(
        sp,
        fallback_library,
        paths,
        checkpoint,
        retry_call,
        echo,
        progress_callback,
    )
    return finalize_sync(albums, tracks, artists, paths, checkpoint)


def restore_library_sync(
    run_id: str,
    paths: LibrarySyncPaths = DEFAULT_PATHS,
) -> tuple[str, ...]:
    """Restore generated files from a completed sync's backup manifest."""
    if not run_id or any(part in run_id for part in ("/", "\\", "..")):
        raise LibrarySyncRestoreError("Invalid library-sync run id.")
    backup_dir = paths.backups_dir / run_id
    manifest_path = backup_dir / "manifest.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        raise LibrarySyncRestoreError(f"No valid backup found for run {run_id}.")

    restored: list[str] = []
    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        raise LibrarySyncRestoreError("The backup manifest has no target list.")
    current_targets = backup_targets(paths)
    for name, target_details in targets.items():
        if name not in current_targets or not isinstance(target_details, dict):
            continue
        target_path = current_targets[name]
        if target_details.get("existed"):
            backup_file = backup_dir / str(target_details["backup_file"])
            if not backup_file.exists():
                raise LibrarySyncRestoreError(
                    f"Backup file missing for {target_path.name}."
                )
            temporary_path = target_path.with_suffix(f"{target_path.suffix}.restore")
            shutil.copy2(backup_file, temporary_path)
            temporary_path.replace(target_path)
        else:
            target_path.unlink(missing_ok=True)
        restored.append(target_path.name)

    append_event(
        paths,
        run_id,
        "run_restored",
        restored_files=restored,
    )
    return tuple(restored)


__all__ = [
    "ArtistVerificationUnavailableError",
    "DEFAULT_PATHS",
    "IncompleteLiveResourceError",
    "LibrarySyncError",
    "LibrarySyncPaths",
    "LibrarySyncRestoreError",
    "LibrarySyncSummary",
    "SpotifyRateLimitError",
    "SpotifyTransientServerError",
    "analyse_library_routine",
    "restore_library_sync",
]
