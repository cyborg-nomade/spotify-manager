"""Build export-only and live-only Spotify library mirrors."""

import json
import shutil
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep
from typing import Any
from typing import Literal

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
from spotify_manager.routines.review_album_limits import SpotifyRateLimitError
from spotify_manager.routines.review_album_limits import current_stats_history_key
from spotify_manager.routines.review_album_limits import get_retry_after_seconds
from spotify_manager.utils.growth import calculate_growth
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key
from spotify_manager.utils.sorting import track_sort_key


ALBUM_PAGE_LIMIT = 50
TRACK_PAGE_LIMIT = 10
ARTIST_PAGE_LIMIT = 50
RECONCILIATION_STABLE_PASSES = 2
OFFSET_RECONCILIATION_STABLE_PAGES = {
    "albums": 2,
    "tracks": 3,
}
TRANSIENT_RETRY_BASE_SECONDS = 2 * 60
TRANSIENT_RETRY_MAX_SECONDS = 30 * 60
CHECKPOINT_VERSION = 1

AnalysisMode = Literal["async", "sync"]
ResourceName = Literal["albums", "tracks", "artists"]
Echo = Callable[[str], None]
ProgressCallback = Callable[[ResourceName, int, int | None, str], None]
CancelCheck = Callable[[], bool]
Sleep = Callable[[float], None]
LibraryModel = YourLibraryAlbum | YourLibraryTrack | YourLibraryArtist


@dataclass(frozen=True)
class RetryNotice:
    """One scheduled retry after a transient Spotify server response."""

    http_status: int
    operation: str
    attempt: int
    delay_seconds: int


RetryWait = Callable[[RetryNotice], bool]


@dataclass(frozen=True)
class LibraryAnalysisPaths:
    """Filesystem paths for one independent analysis output family."""

    mode: AnalysisMode
    files_dir: Path
    your_library: Path
    albums_total: Path
    liked_tracks_total: Path
    artists_total: Path
    stats_history: Path
    checkpoint: Path
    staging_dir: Path
    event_log: Path
    backups_dir: Path

    @classmethod
    def for_files_dir(
        cls,
        files_dir: Path,
        mode: AnalysisMode = "sync",
    ) -> LibraryAnalysisPaths:
        """Build conventional paths beneath ``files_dir`` for one mode."""
        workspace = files_dir / f"library_analysis_{mode}"
        return cls(
            mode=mode,
            files_dir=files_dir,
            your_library=files_dir / "YourLibrary.json",
            albums_total=files_dir / f"albums_total_new_{mode}.json",
            liked_tracks_total=files_dir / f"liked_tracks_total_{mode}.json",
            artists_total=files_dir / f"artists_total_{mode}.json",
            stats_history=files_dir / f"stats_history_{mode}.json",
            checkpoint=workspace / "checkpoint.json",
            staging_dir=workspace / "staging",
            event_log=files_dir / f"library_analysis_{mode}_log.jsonl",
            backups_dir=files_dir / f"library_analysis_{mode}_backups",
        )

    def stage(self, resource: ResourceName) -> Path:
        """Return the staging path for one resource."""
        suffix = ".json" if self.mode == "async" else ".jsonl"
        return self.staging_dir / f"{resource}{suffix}"


# Backwards-compatible type name for callers that supplied custom paths.
LibrarySyncPaths = LibraryAnalysisPaths
FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_ASYNC_PATHS = LibraryAnalysisPaths.for_files_dir(FILES_DIR, "async")
DEFAULT_SYNC_PATHS = LibraryAnalysisPaths.for_files_dir(FILES_DIR, "sync")
DEFAULT_PATHS = DEFAULT_SYNC_PATHS


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
    """Final outcome of one completed library analysis."""

    run_id: str
    mode: AnalysisMode
    backup_dir: str
    resources: tuple[ResourceSyncSummary, ...]


class LibrarySyncError(RuntimeError):
    """Base exception for an analysis that cannot safely publish output."""


class LibraryAnalysisCancelledError(LibrarySyncError):
    """Raised after a user requests a clean, checkpointed stop."""


class IncompleteLiveResourceError(LibrarySyncError):
    """Raised when Spotify returns a structurally incomplete page sequence."""


class LibrarySyncRestoreError(LibrarySyncError):
    """Raised when a requested analysis backup cannot be restored."""


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    """Return a sortable identifier for one analysis run."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def write_json_atomic(path: Path, value: object) -> None:
    """Write JSON through a sibling temporary file and atomically replace it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(path: Path, default: object | None = None) -> Any:
    """Load JSON, returning ``default`` when the file does not exist."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibrarySyncError(f"Could not read valid JSON from {path}.") from exc


def append_event(
    paths: LibraryAnalysisPaths,
    run_id: str,
    event: str,
    **details: object,
) -> None:
    """Append one durable JSON-lines audit event."""
    paths.event_log.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "mode": paths.mode,
        "event": event,
        **details,
    }
    with paths.event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_models(path: Path, models: Sequence[BaseModel]) -> None:
    """Atomically write a list of Pydantic models."""
    write_json_atomic(path, [model.model_dump() for model in models])


def append_models_jsonl(path: Path, models: Sequence[BaseModel]) -> None:
    """Append models to a resumable JSON-lines staging file."""
    if not models:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for model in models:
            handle.write(json.dumps(model.model_dump(), ensure_ascii=False) + "\n")


def load_model_list[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load a JSON array of models, treating a missing file as empty."""
    raw = load_json(path, default=[])
    if not isinstance(raw, list):
        raise LibrarySyncError(f"Expected a JSON list in {path}.")
    return [model.model_validate(item) for item in raw]


def load_models_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load models from JSON-lines staging, ignoring a torn final line."""
    if not path.exists():
        return []
    models: list[T] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        try:
            models.append(model.model_validate_json(line))
        except ValueError, json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise LibrarySyncError(f"Invalid staging data in {path}.") from None
    return models


def deduplicate_models[T: LibraryModel](models: Sequence[T]) -> list[T]:
    """Deduplicate models by Spotify id while preserving the newest value."""
    by_id: dict[str, T] = {}
    for model in models:
        spotify_id = getattr(model, "spotify_id", "")
        if spotify_id:
            by_id[spotify_id] = model
    return list(by_id.values())


def load_your_library(paths: LibraryAnalysisPaths) -> YourLibraryFile:
    """Load the Spotify export used exclusively by async analysis."""
    raw = load_json(paths.your_library)
    if raw is None:
        raise LibrarySyncError(f"Your Library export not found: {paths.your_library}")
    try:
        return YourLibraryFile.model_validate(raw)
    except ValueError as exc:
        raise LibrarySyncError(
            f"Your Library export is invalid: {paths.your_library}"
        ) from exc


def album_from_saved_item(item: object) -> YourLibraryAlbum | None:
    """Convert one Spotify saved-album item into the local model."""
    if not isinstance(item, dict) or not isinstance(item.get("album"), dict):
        return None
    album = item["album"]
    artists = album.get("artists")
    primary = artists[0] if isinstance(artists, list) and artists else {}
    spotify_id = album.get("id")
    name = album.get("name")
    artist_name = primary.get("name") if isinstance(primary, dict) else None
    if not spotify_id or not name or not artist_name:
        return None
    return YourLibraryAlbum(
        artist=str(artist_name),
        album=str(name),
        uri=str(album.get("uri") or f"spotify:album:{spotify_id}"),
    )


def track_from_saved_item(item: object) -> YourLibraryTrack | None:
    """Convert one Spotify saved-track item into the local model."""
    if not isinstance(item, dict) or not isinstance(item.get("track"), dict):
        return None
    track = item["track"]
    artists = track.get("artists")
    primary = artists[0] if isinstance(artists, list) and artists else {}
    album = track.get("album")
    spotify_id = track.get("id")
    name = track.get("name")
    artist_name = primary.get("name") if isinstance(primary, dict) else None
    album_name = album.get("name") if isinstance(album, dict) else None
    if not spotify_id or not name or not artist_name or not album_name:
        return None
    return YourLibraryTrack(
        artist=str(artist_name),
        album=str(album_name),
        track=str(name),
        uri=str(track.get("uri") or f"spotify:track:{spotify_id}"),
    )


def artist_from_api_item(item: object) -> YourLibraryArtist | None:
    """Convert one Spotify artist object into the local model."""
    if not isinstance(item, dict):
        return None
    spotify_id = item.get("id")
    name = item.get("name")
    if not spotify_id or not name:
        return None
    return YourLibraryArtist(
        name=str(name),
        uri=str(item.get("uri") or f"spotify:artist:{spotify_id}"),
    )


def model_diff(
    previous: Sequence[LibraryModel],
    current: Sequence[LibraryModel],
) -> tuple[list[LibraryModel], list[LibraryModel]]:
    """Return models added to and removed from a Spotify-id keyed mirror."""
    previous_by_id = {item.spotify_id: item for item in previous}
    current_by_id = {item.spotify_id: item for item in current}
    added = [item for key, item in current_by_id.items() if key not in previous_by_id]
    removed = [item for key, item in previous_by_id.items() if key not in current_by_id]
    return added, removed


def stats_report_for_analysis(
    previous_albums: Sequence[YourLibraryAlbum],
    albums: Sequence[YourLibraryAlbum],
    previous_tracks: Sequence[YourLibraryTrack],
    tracks: Sequence[YourLibraryTrack],
    previous_artists: Sequence[YourLibraryArtist],
    artists: Sequence[YourLibraryArtist],
) -> StatsReport:
    """Build a stats report from exact pre/post analysis mirrors."""
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
    previous: Sequence[LibraryModel],
    current: Sequence[LibraryModel],
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


def backup_targets(paths: LibraryAnalysisPaths) -> dict[str, Path]:
    """Return every generated file changed by publication."""
    return {
        "albums": paths.albums_total,
        "tracks": paths.liked_tracks_total,
        "artists": paths.artists_total,
        "stats_history": paths.stats_history,
    }


def create_backup_manifest(
    paths: LibraryAnalysisPaths,
    run_id: str,
    previous: dict[ResourceName, Sequence[LibraryModel]],
    current: dict[ResourceName, Sequence[LibraryModel]],
    report: StatsReport,
    summaries: tuple[ResourceSyncSummary, ...],
) -> Path:
    """Snapshot generated files and record exact changes for review and undo."""
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
    for resource in ("albums", "tracks", "artists"):
        added, removed = model_diff(previous[resource], current[resource])
        changes[resource] = {
            "added": [item.model_dump() for item in added],
            "removed": [item.model_dump() for item in removed],
        }

    manifest = {
        "version": 1,
        "run_id": run_id,
        "mode": paths.mode,
        "created_at": utc_now(),
        "targets": targets,
        "changes": changes,
        "stats_report": report.model_dump(),
        "summaries": [asdict(summary) for summary in summaries],
    }
    write_json_atomic(backup_dir / "manifest.json", manifest)
    append_event(paths, run_id, "backup_created", backup_dir=str(backup_dir))
    return backup_dir


def pre_analysis_stats_history(
    paths: LibraryAnalysisPaths,
    backup_dir: Path,
) -> dict[str, object]:
    """Load stats from the backup so interrupted publication is repeatable."""
    manifest = load_json(backup_dir / "manifest.json")
    if not isinstance(manifest, dict):
        raise LibrarySyncError("The analysis backup manifest is invalid.")
    target = manifest["targets"]["stats_history"]
    if not target["existed"]:
        return {}
    raw = load_json(backup_dir / str(target["backup_file"]), default={})
    if not isinstance(raw, dict):
        raise LibrarySyncError("The backed-up stats history is invalid.")
    return raw


def sort_resources(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
) -> tuple[list[YourLibraryAlbum], list[YourLibraryTrack], list[YourLibraryArtist]]:
    """Deduplicate and apply Spotify-like output ordering."""
    return (
        sorted(deduplicate_models(albums), key=album_sort_key),
        sorted(deduplicate_models(tracks), key=track_sort_key),
        sorted(deduplicate_models(artists), key=artist_sort_key),
    )


def finalize_analysis(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
) -> LibrarySyncSummary:
    """Publish completed staging data with an idempotent undo snapshot."""
    albums, tracks, artists = sort_resources(albums, tracks, artists)
    current: dict[ResourceName, Sequence[LibraryModel]] = {
        "albums": albums,
        "tracks": tracks,
        "artists": artists,
    }

    if checkpoint["status"] != "finalizing":
        previous_albums = load_model_list(paths.albums_total, YourLibraryAlbum)
        previous_tracks = load_model_list(paths.liked_tracks_total, YourLibraryTrack)
        previous_artists = load_model_list(paths.artists_total, YourLibraryArtist)
        previous: dict[ResourceName, Sequence[LibraryModel]] = {
            "albums": previous_albums,
            "tracks": previous_tracks,
            "artists": previous_artists,
        }
        report = stats_report_for_analysis(
            previous_albums,
            albums,
            previous_tracks,
            tracks,
            previous_artists,
            artists,
        )
        source = "YourLibrary.json" if paths.mode == "async" else "live_api"
        resource_names: tuple[ResourceName, ...] = ("albums", "tracks", "artists")
        summaries = tuple(
            resource_summary(
                resource,
                source,
                previous[resource],
                current[resource],
                int(checkpoint["resources"][resource].get("skipped", 0)),
            )
            for resource in resource_names
        )
        backup_dir = create_backup_manifest(
            paths,
            str(checkpoint["run_id"]),
            previous,
            current,
            report,
            summaries,
        )
        checkpoint["status"] = "finalizing"
        checkpoint["backup_dir"] = str(backup_dir)
        write_json_atomic(paths.checkpoint, checkpoint)
    else:
        backup_dir = Path(str(checkpoint["backup_dir"]))
        manifest = load_json(backup_dir / "manifest.json")
        if not isinstance(manifest, dict):
            raise LibrarySyncError("The analysis backup manifest is invalid.")
        report = StatsReport.model_validate(manifest["stats_report"])
        summaries = tuple(ResourceSyncSummary(**item) for item in manifest["summaries"])

    write_models(paths.albums_total, albums)
    write_models(paths.liked_tracks_total, tracks)
    write_models(paths.artists_total, artists)
    history = pre_analysis_stats_history(paths, backup_dir)
    history[current_stats_history_key()] = report.model_dump()
    write_json_atomic(paths.stats_history, history)

    checkpoint["status"] = "complete"
    checkpoint["completed_at"] = utc_now()
    write_json_atomic(paths.checkpoint, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "run_completed",
        backup_dir=str(backup_dir),
        summaries=[asdict(summary) for summary in summaries],
    )
    return LibrarySyncSummary(
        run_id=str(checkpoint["run_id"]),
        mode=paths.mode,
        backup_dir=str(backup_dir),
        resources=summaries,
    )


def export_fingerprint(path: Path) -> dict[str, int]:
    """Return enough metadata to detect an export replaced between resumes."""
    try:
        stat = path.stat()
    except OSError as exc:
        raise LibrarySyncError(f"Your Library export not found: {path}") from exc
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def new_checkpoint(paths: LibraryAnalysisPaths) -> dict[str, Any]:
    """Create a fresh checkpoint for one mode."""
    checkpoint: dict[str, Any] = {
        "version": CHECKPOINT_VERSION,
        "mode": paths.mode,
        "run_id": new_run_id(),
        "status": "running",
        "created_at": utc_now(),
        "resources": {
            resource: {
                "status": "pending",
                "offset": 0,
                "after": None,
                "total": None,
                "pages": 0,
                "skipped": 0,
                "stable_passes": 0,
            }
            for resource in ("albums", "tracks", "artists")
        },
    }
    if paths.mode == "async":
        checkpoint["export_fingerprint"] = export_fingerprint(paths.your_library)
    return checkpoint


def load_or_create_checkpoint(paths: LibraryAnalysisPaths) -> dict[str, Any]:
    """Resume a compatible incomplete checkpoint or start a fresh run."""
    raw = load_json(paths.checkpoint)
    compatible = (
        isinstance(raw, dict)
        and raw.get("version") == CHECKPOINT_VERSION
        and raw.get("mode") == paths.mode
        and raw.get("status") != "complete"
    )
    if compatible and paths.mode == "async":
        compatible = raw.get("export_fingerprint") == export_fingerprint(
            paths.your_library
        )
    if compatible:
        append_event(paths, str(raw["run_id"]), "run_resumed")
        return raw

    if paths.staging_dir.exists():
        shutil.rmtree(paths.staging_dir)
    paths.staging_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = new_checkpoint(paths)
    write_json_atomic(paths.checkpoint, checkpoint)
    append_event(paths, str(checkpoint["run_id"]), "run_started")
    return checkpoint


def prepare_export_resource[T: LibraryModel](
    resource: ResourceName,
    models: list[T],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    model_type: type[T],
    sort_key: Callable[[T], tuple[int, ...]],
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> list[T]:
    """Prepare and stage one export resource, with resumable boundaries."""
    state = checkpoint["resources"][resource]
    if state["status"] == "complete":
        completed = load_model_list(paths.stage(resource), model_type)
        if progress_callback:
            progress_callback(resource, len(completed), len(completed), "Complete")
        return completed

    total = len(models)
    if progress_callback:
        progress_callback(resource, 0, total, "Reading YourLibrary.json")
    by_id: dict[str, T] = {}
    update_every = max(1, total // 100)
    for index, model in enumerate(models, start=1):
        if index == 1 or index % update_every == 0:
            check_cancel(cancel_check)
        by_id[model.spotify_id] = model
        if progress_callback and (index == total or index % update_every == 0):
            progress_callback(resource, index, total, "Reading YourLibrary.json")
    prepared = sorted(by_id.values(), key=sort_key)
    write_models(paths.stage(resource), prepared)
    state["status"] = "complete"
    state["total"] = len(prepared)
    state["skipped"] = total - len(prepared)
    write_json_atomic(paths.checkpoint, checkpoint)
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "resource_completed",
        resource=resource,
        count=len(prepared),
        skipped=total - len(prepared),
    )
    if progress_callback:
        progress_callback(resource, total, total, "Complete")
    return prepared


def analyse_library_async_routine(
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_ASYNC_PATHS,
) -> LibrarySyncSummary:
    """Build ``*_async`` mirrors exclusively from ``YourLibrary.json``."""
    del echo
    if paths.mode != "async":
        raise LibrarySyncError("Export analysis requires async output paths.")
    checkpoint = load_or_create_checkpoint(paths)
    try:
        if checkpoint["status"] == "finalizing":
            return finalize_analysis(
                load_model_list(paths.stage("albums"), YourLibraryAlbum),
                load_model_list(paths.stage("tracks"), YourLibraryTrack),
                load_model_list(paths.stage("artists"), YourLibraryArtist),
                paths,
                checkpoint,
            )
        library = load_your_library(paths)
        albums = prepare_export_resource(
            "albums",
            library.albums,
            paths,
            checkpoint,
            YourLibraryAlbum,
            album_sort_key,
            progress_callback,
            cancel_check,
        )
        tracks = prepare_export_resource(
            "tracks",
            library.tracks,
            paths,
            checkpoint,
            YourLibraryTrack,
            track_sort_key,
            progress_callback,
            cancel_check,
        )
        artists = prepare_export_resource(
            "artists",
            library.artists,
            paths,
            checkpoint,
            YourLibraryArtist,
            artist_sort_key,
            progress_callback,
            cancel_check,
        )
        return finalize_analysis(albums, tracks, artists, paths, checkpoint)
    except LibraryAnalysisCancelledError:
        append_event(paths, str(checkpoint["run_id"]), "run_paused")
        raise
    except KeyboardInterrupt:
        append_event(paths, str(checkpoint["run_id"]), "run_paused")
        raise
    except LibrarySyncError:
        append_event(paths, str(checkpoint["run_id"]), "run_failed")
        raise
    except Exception as exc:
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "run_failed",
            error=type(exc).__name__,
            detail=str(exc),
        )
        raise LibrarySyncError(f"Export analysis failed: {exc}") from exc


def retry_delay(base: int, maximum: int, attempt: int) -> int:
    """Return the capped exponential delay for a one-based attempt."""
    if base <= 0 or maximum <= 0:
        return 0
    exponent = min(max(0, attempt - 1), maximum.bit_length())
    return min(maximum, base * (1 << exponent))


def spotify_call[T](
    operation: Callable[[], T],
    description: str,
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    retry_wait: RetryWait | None,
    sleep: Sleep,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> T:
    """Call Spotify, retrying only 5xx responses with exponential backoff."""
    attempt = 0
    while True:
        try:
            return operation()
        except SpotifyException as exc:
            if exc.http_status == 429:
                raise SpotifyRateLimitError(get_retry_after_seconds(exc)) from exc
            if exc.http_status is None or not 500 <= exc.http_status <= 599:
                raise LibrarySyncError(
                    f"Spotify request failed while {description} "
                    f"(HTTP {exc.http_status}): {exc.msg}"
                ) from exc
            attempt += 1
            delay = retry_delay(retry_base_seconds, retry_max_seconds, attempt)
            notice = RetryNotice(exc.http_status, description, attempt, delay)
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "server_retry_scheduled",
                http_status=exc.http_status,
                operation=description,
                attempt=attempt,
                delay_seconds=delay,
            )
            echo(
                f"Spotify HTTP {exc.http_status} while {description}; "
                f"retrying in {delay} seconds (attempt {attempt})."
            )
            should_continue = (
                retry_wait(notice)
                if retry_wait is not None
                else _default_retry_wait(delay, sleep)
            )
            if not should_continue:
                raise LibraryAnalysisCancelledError(
                    "Live analysis paused during a Spotify retry wait."
                ) from exc


def _default_retry_wait(delay: int, sleep: Sleep) -> bool:
    """Wait for a retry when no interactive callback was supplied."""
    sleep(delay)
    return True


def check_cancel(cancel_check: CancelCheck | None) -> None:
    """Raise a clean pause signal at a durable page boundary."""
    if cancel_check is not None and cancel_check():
        raise LibraryAnalysisCancelledError("Live analysis paused by request.")


def page_items(page: object, resource: ResourceName) -> list[object]:
    """Validate and return the item list from an offset page."""
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise IncompleteLiveResourceError(
            f"Spotify returned an invalid {resource} page."
        )
    return page["items"]


def followed_artist_page_items(page: object) -> tuple[list[object], dict[str, Any]]:
    """Validate and unpack a followed-artists cursor page."""
    if not isinstance(page, dict) or not isinstance(page.get("artists"), dict):
        raise IncompleteLiveResourceError(
            "Spotify returned an invalid followed-artists page."
        )
    artists = page["artists"]
    if not isinstance(artists.get("items"), list):
        raise IncompleteLiveResourceError(
            "Spotify returned an invalid followed-artists item list."
        )
    return artists["items"], artists


def sync_initial_offset_resource(
    sp: Spotify,
    resource: Literal["albums", "tracks"],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None,
    cancel_check: CancelCheck | None,
    sleep: Sleep,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    """Scan one offset resource monotonically without reacting to total changes."""
    state = checkpoint["resources"][resource]
    if state["status"] != "pending" and state["status"] != "scanning":
        return
    state["status"] = "scanning"
    write_json_atomic(paths.checkpoint, checkpoint)
    limit = ALBUM_PAGE_LIMIT if resource == "albums" else TRACK_PAGE_LIMIT
    method = (
        sp.current_user_saved_albums
        if resource == "albums"
        else sp.current_user_saved_tracks
    )
    converter = album_from_saved_item if resource == "albums" else track_from_saved_item

    while True:
        check_cancel(cancel_check)
        offset = int(state["offset"])
        page = spotify_call(
            partial(method, limit=limit, offset=offset),
            f"reading saved {resource} at offset {offset}",
            paths,
            checkpoint,
            echo,
            retry_wait,
            sleep,
            retry_base_seconds,
            retry_max_seconds,
        )
        raw_items = page_items(page, resource)
        converted = [item for raw in raw_items if (item := converter(raw)) is not None]
        append_models_jsonl(paths.stage(resource), converted)
        state["skipped"] += len(raw_items) - len(converted)
        state["offset"] = offset + len(raw_items)
        state["pages"] += 1
        state["total"] = page.get("total")
        write_json_atomic(paths.checkpoint, checkpoint)
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "page_saved",
            resource=resource,
            offset=offset,
            count=len(converted),
            reported_total=page.get("total"),
        )
        if progress_callback:
            progress_callback(
                resource,
                int(state["offset"]),
                page.get("total") if isinstance(page.get("total"), int) else None,
                "Reading live API",
            )
        if not raw_items and page.get("next"):
            raise IncompleteLiveResourceError(
                f"Spotify returned an empty {resource} page with a next link."
            )
        if not raw_items or not page.get("next"):
            state["status"] = "reconciling"
            state["stable_passes"] = 0
            write_json_atomic(paths.checkpoint, checkpoint)
            return


def reconcile_offset_resource(
    sp: Spotify,
    resource: Literal["albums", "tracks"],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None,
    cancel_check: CancelCheck | None,
    sleep: Sleep,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    """Re-read the newest pages until two passes find no additions."""
    state = checkpoint["resources"][resource]
    if state["status"] == "complete":
        if resource == "albums":
            completed_count = len(
                deduplicate_models(
                    load_models_jsonl(paths.stage(resource), YourLibraryAlbum)
                )
            )
        else:
            completed_count = len(
                deduplicate_models(
                    load_models_jsonl(paths.stage(resource), YourLibraryTrack)
                )
            )
        if progress_callback:
            progress_callback(
                resource,
                completed_count,
                completed_count,
                "Complete",
            )
        return
    limit = ALBUM_PAGE_LIMIT if resource == "albums" else TRACK_PAGE_LIMIT
    method = (
        sp.current_user_saved_albums
        if resource == "albums"
        else sp.current_user_saved_tracks
    )
    converter = album_from_saved_item if resource == "albums" else track_from_saved_item
    stable_pages_required = OFFSET_RECONCILIATION_STABLE_PAGES[resource]

    while int(state["stable_passes"]) < RECONCILIATION_STABLE_PASSES:
        if resource == "albums":
            staged: list[LibraryModel] = load_models_jsonl(
                paths.stage(resource),
                YourLibraryAlbum,
            )
        else:
            staged = load_models_jsonl(paths.stage(resource), YourLibraryTrack)
        known = {item.spotify_id for item in staged}
        offset = 0
        pass_added = 0
        stable_pages = 0
        while True:
            check_cancel(cancel_check)
            page = spotify_call(
                partial(method, limit=limit, offset=offset),
                f"reconciling saved {resource} at offset {offset}",
                paths,
                checkpoint,
                echo,
                retry_wait,
                sleep,
                retry_base_seconds,
                retry_max_seconds,
            )
            raw_items = page_items(page, resource)
            converted = [
                item for raw in raw_items if (item := converter(raw)) is not None
            ]
            unseen = [item for item in converted if item.spotify_id not in known]
            append_models_jsonl(paths.stage(resource), unseen)
            known.update(item.spotify_id for item in unseen)
            pass_added += len(unseen)
            stable_pages = 0 if unseen else stable_pages + 1
            write_json_atomic(paths.checkpoint, checkpoint)
            if progress_callback:
                progress_callback(
                    resource,
                    len(known),
                    page.get("total") if isinstance(page.get("total"), int) else None,
                    f"Checking for additions (pass {int(state['stable_passes']) + 1})",
                )
            if (
                not raw_items
                or not page.get("next")
                or stable_pages >= stable_pages_required
            ):
                break
            offset += len(raw_items)

        if pass_added:
            state["stable_passes"] = 0
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "reconciliation_additions",
                resource=resource,
                count=pass_added,
            )
        else:
            state["stable_passes"] += 1
        write_json_atomic(paths.checkpoint, checkpoint)

    state["status"] = "complete"
    write_json_atomic(paths.checkpoint, checkpoint)
    if resource == "albums":
        completed: list[LibraryModel] = load_models_jsonl(
            paths.stage(resource),
            YourLibraryAlbum,
        )
    else:
        completed = load_models_jsonl(paths.stage(resource), YourLibraryTrack)
    count = len(deduplicate_models(completed))
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "resource_completed",
        resource=resource,
        count=count,
        skipped=state["skipped"],
    )
    if progress_callback:
        progress_callback(resource, count, count, "Complete")


def sync_initial_artists(
    sp: Spotify,
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None,
    cancel_check: CancelCheck | None,
    sleep: Sleep,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    """Scan followed artists once with cursor pagination."""
    state = checkpoint["resources"]["artists"]
    if state["status"] != "pending" and state["status"] != "scanning":
        return
    state["status"] = "scanning"
    write_json_atomic(paths.checkpoint, checkpoint)
    while True:
        check_cancel(cancel_check)
        after = state["after"]
        page = spotify_call(
            partial(
                sp.current_user_followed_artists,
                limit=ARTIST_PAGE_LIMIT,
                after=after,
            ),
            f"reading followed artists after {after or 'the beginning'}",
            paths,
            checkpoint,
            echo,
            retry_wait,
            sleep,
            retry_base_seconds,
            retry_max_seconds,
        )
        raw_items, artists_page = followed_artist_page_items(page)
        converted = [
            item for raw in raw_items if (item := artist_from_api_item(raw)) is not None
        ]
        append_models_jsonl(paths.stage("artists"), converted)
        state["skipped"] += len(raw_items) - len(converted)
        state["pages"] += 1
        state["total"] = artists_page.get("total")
        next_after = (artists_page.get("cursors") or {}).get("after")
        state["after"] = next_after
        write_json_atomic(paths.checkpoint, checkpoint)
        if progress_callback:
            count = len(
                deduplicate_models(
                    load_models_jsonl(paths.stage("artists"), YourLibraryArtist)
                )
            )
            progress_callback(
                "artists",
                count,
                artists_page.get("total")
                if isinstance(artists_page.get("total"), int)
                else None,
                "Reading live API",
            )
        if not raw_items or not artists_page.get("next"):
            state["status"] = "reconciling"
            state["stable_passes"] = 0
            state["after"] = None
            write_json_atomic(paths.checkpoint, checkpoint)
            return
        if next_after is None or next_after == after:
            raise IncompleteLiveResourceError(
                "Spotify did not advance the followed-artists cursor."
            )


def reconcile_artists(
    sp: Spotify,
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None,
    cancel_check: CancelCheck | None,
    sleep: Sleep,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    """Fully rescan cursor-ordered artists until two passes find no additions."""
    state = checkpoint["resources"]["artists"]
    if state["status"] == "complete":
        completed_count = len(
            deduplicate_models(
                load_models_jsonl(paths.stage("artists"), YourLibraryArtist)
            )
        )
        if progress_callback:
            progress_callback(
                "artists",
                completed_count,
                completed_count,
                "Complete",
            )
        return
    while int(state["stable_passes"]) < RECONCILIATION_STABLE_PASSES:
        known = {
            item.spotify_id
            for item in load_models_jsonl(paths.stage("artists"), YourLibraryArtist)
        }
        after: str | None = None
        pass_added = 0
        while True:
            check_cancel(cancel_check)
            page = spotify_call(
                partial(
                    sp.current_user_followed_artists,
                    limit=ARTIST_PAGE_LIMIT,
                    after=after,
                ),
                f"reconciling followed artists after {after or 'the beginning'}",
                paths,
                checkpoint,
                echo,
                retry_wait,
                sleep,
                retry_base_seconds,
                retry_max_seconds,
            )
            raw_items, artists_page = followed_artist_page_items(page)
            converted = [
                item
                for raw in raw_items
                if (item := artist_from_api_item(raw)) is not None
            ]
            unseen = [item for item in converted if item.spotify_id not in known]
            append_models_jsonl(paths.stage("artists"), unseen)
            known.update(item.spotify_id for item in unseen)
            pass_added += len(unseen)
            write_json_atomic(paths.checkpoint, checkpoint)
            if progress_callback:
                progress_callback(
                    "artists",
                    len(known),
                    artists_page.get("total")
                    if isinstance(artists_page.get("total"), int)
                    else None,
                    f"Checking for additions (pass {int(state['stable_passes']) + 1})",
                )
            next_after = (artists_page.get("cursors") or {}).get("after")
            if not raw_items or not artists_page.get("next"):
                break
            if next_after is None or next_after == after:
                raise IncompleteLiveResourceError(
                    "Spotify did not advance the followed-artists cursor."
                )
            after = str(next_after)

        if pass_added:
            state["stable_passes"] = 0
            append_event(
                paths,
                str(checkpoint["run_id"]),
                "reconciliation_additions",
                resource="artists",
                count=pass_added,
            )
        else:
            state["stable_passes"] += 1
        write_json_atomic(paths.checkpoint, checkpoint)

    state["status"] = "complete"
    write_json_atomic(paths.checkpoint, checkpoint)
    count = len(
        deduplicate_models(load_models_jsonl(paths.stage("artists"), YourLibraryArtist))
    )
    append_event(
        paths,
        str(checkpoint["run_id"]),
        "resource_completed",
        resource="artists",
        count=count,
        skipped=state["skipped"],
    )
    if progress_callback:
        progress_callback("artists", count, count, "Complete")


def analyse_library_sync_routine(
    sp: Spotify,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_SYNC_PATHS,
    sleep: Sleep = default_sleep,
    retry_base_seconds: int = TRANSIENT_RETRY_BASE_SECONDS,
    retry_max_seconds: int = TRANSIENT_RETRY_MAX_SECONDS,
) -> LibrarySyncSummary:
    """Build ``*_sync`` mirrors exclusively from the live Spotify API."""
    if paths.mode != "sync":
        raise LibrarySyncError("Live analysis requires sync output paths.")
    checkpoint = load_or_create_checkpoint(paths)
    try:
        if checkpoint["status"] == "finalizing":
            return finalize_analysis(
                load_models_jsonl(paths.stage("albums"), YourLibraryAlbum),
                load_models_jsonl(paths.stage("tracks"), YourLibraryTrack),
                load_models_jsonl(paths.stage("artists"), YourLibraryArtist),
                paths,
                checkpoint,
            )
        for resource in ("albums", "tracks"):
            sync_initial_offset_resource(
                sp,
                resource,
                paths,
                checkpoint,
                echo,
                progress_callback,
                retry_wait,
                cancel_check,
                sleep,
                retry_base_seconds,
                retry_max_seconds,
            )
            reconcile_offset_resource(
                sp,
                resource,
                paths,
                checkpoint,
                echo,
                progress_callback,
                retry_wait,
                cancel_check,
                sleep,
                retry_base_seconds,
                retry_max_seconds,
            )
        sync_initial_artists(
            sp,
            paths,
            checkpoint,
            echo,
            progress_callback,
            retry_wait,
            cancel_check,
            sleep,
            retry_base_seconds,
            retry_max_seconds,
        )
        reconcile_artists(
            sp,
            paths,
            checkpoint,
            echo,
            progress_callback,
            retry_wait,
            cancel_check,
            sleep,
            retry_base_seconds,
            retry_max_seconds,
        )
        return finalize_analysis(
            load_models_jsonl(paths.stage("albums"), YourLibraryAlbum),
            load_models_jsonl(paths.stage("tracks"), YourLibraryTrack),
            load_models_jsonl(paths.stage("artists"), YourLibraryArtist),
            paths,
            checkpoint,
        )
    except LibraryAnalysisCancelledError, SpotifyRateLimitError:
        append_event(paths, str(checkpoint["run_id"]), "run_paused")
        raise
    except KeyboardInterrupt:
        append_event(paths, str(checkpoint["run_id"]), "run_paused")
        raise
    except LibrarySyncError:
        append_event(paths, str(checkpoint["run_id"]), "run_failed")
        raise
    except Exception as exc:
        append_event(
            paths,
            str(checkpoint["run_id"]),
            "run_failed",
            error=type(exc).__name__,
            detail=str(exc),
        )
        raise LibrarySyncError(f"Live analysis failed: {exc}") from exc


def restore_library_sync(
    run_id: str,
    paths: LibraryAnalysisPaths | None = None,
) -> tuple[str, ...]:
    """Restore generated files from one completed async or sync backup."""
    if not run_id or any(part in run_id for part in ("/", "\\", "..")):
        raise LibrarySyncRestoreError("Invalid library-analysis run id.")
    candidates = (
        [paths] if paths is not None else [DEFAULT_SYNC_PATHS, DEFAULT_ASYNC_PATHS]
    )
    selected: LibraryAnalysisPaths | None = None
    backup_dir: Path | None = None
    manifest: dict[str, Any] | None = None
    for candidate in candidates:
        if candidate is None:
            continue
        possible_dir = candidate.backups_dir / run_id
        raw = load_json(possible_dir / "manifest.json")
        if isinstance(raw, dict) and raw.get("run_id") == run_id:
            selected = candidate
            backup_dir = possible_dir
            manifest = raw
            break
    if selected is None or backup_dir is None or manifest is None:
        raise LibrarySyncRestoreError(f"No valid backup found for run {run_id}.")

    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        raise LibrarySyncRestoreError("The backup manifest has no target list.")
    current_targets = backup_targets(selected)
    restored: list[str] = []
    for name, details in targets.items():
        if name not in current_targets or not isinstance(details, dict):
            continue
        target = current_targets[name]
        if details.get("existed"):
            backup_file = backup_dir / str(details["backup_file"])
            if not backup_file.exists():
                raise LibrarySyncRestoreError(f"Backup file missing for {target.name}.")
            temporary = target.with_suffix(f"{target.suffix}.restore")
            shutil.copy2(backup_file, temporary)
            temporary.replace(target)
        else:
            target.unlink(missing_ok=True)
        restored.append(target.name)

    append_event(selected, run_id, "run_restored", restored_files=restored)
    return tuple(restored)


# Compatibility alias for integrations that imported the old hybrid entry point.
analyse_library_routine = analyse_library_sync_routine


__all__ = [
    "DEFAULT_ASYNC_PATHS",
    "DEFAULT_SYNC_PATHS",
    "IncompleteLiveResourceError",
    "LibraryAnalysisCancelledError",
    "LibraryAnalysisPaths",
    "LibrarySyncError",
    "LibrarySyncPaths",
    "LibrarySyncRestoreError",
    "LibrarySyncSummary",
    "ResourceSyncSummary",
    "RetryNotice",
    "SpotifyRateLimitError",
    "analyse_library_async_routine",
    "analyse_library_sync_routine",
    "restore_library_sync",
]
