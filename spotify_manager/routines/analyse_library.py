"""Preserve public analysis seams while binding typed inner business stages.

The legacy checkpoint dictionaries remain permissive external boundaries. Inner
stages use typed progress views without changing validation or persisted bytes.
"""

from collections.abc import Callable
from collections.abc import Sequence
from datetime import UTC
from datetime import datetime
from pathlib import Path
from time import sleep as default_sleep
from typing import Any
from typing import Literal
from typing import cast

from pydantic import BaseModel
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application import library_analysis_artists as analysis_artists
from spotify_manager.application import (
    library_analysis_checkpoint as analysis_checkpoints,
)
from spotify_manager.application import library_analysis_export as analysis_export
from spotify_manager.application import library_analysis_offsets as analysis_offsets
from spotify_manager.application import (
    library_analysis_publication as analysis_publication_owner,
)
from spotify_manager.application import library_analysis_records as analysis_records
from spotify_manager.application import library_analysis_run as analysis_runs
from spotify_manager.application import library_analysis_values as analysis_values_paths
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import (
    LibraryAnalysisPaths as LibraryAnalysisPaths,
)
from spotify_manager.bootstrap.library_analysis import (
    analysis_files as analysis_storage,
)
from spotify_manager.bootstrap.library_analysis import analysis_publication
from spotify_manager.bootstrap.library_analysis import analysis_session

# UFI
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.domain import library_analysis as analysis_policy
from spotify_manager.domain import library_analysis_values as analysis_values
from spotify_manager.domain.library_analysis_values import (
    ALBUM_PAGE_LIMIT as ALBUM_PAGE_LIMIT,
)
from spotify_manager.domain.library_analysis_values import (
    ARTIST_DIRECT_MAX_PAGES as ARTIST_DIRECT_MAX_PAGES,
)
from spotify_manager.domain.library_analysis_values import (
    ARTIST_PAGE_LIMIT as ARTIST_PAGE_LIMIT,
)
from spotify_manager.domain.library_analysis_values import (
    ARTIST_VERIFICATION_BATCH_LIMIT as ARTIST_VERIFICATION_BATCH_LIMIT,
)
from spotify_manager.domain.library_analysis_values import (
    ARTIST_VERIFICATION_MAX_ATTEMPTS as ARTIST_VERIFICATION_MAX_ATTEMPTS,
)
from spotify_manager.domain.library_analysis_values import (
    OFFSET_RECONCILIATION_STABLE_PAGES as OFFSET_RECONCILIATION_STABLE_PAGES,
)
from spotify_manager.domain.library_analysis_values import (
    RECONCILIATION_STABLE_PASSES as RECONCILIATION_STABLE_PASSES,
)
from spotify_manager.domain.library_analysis_values import (
    TRACK_PAGE_LIMIT as TRACK_PAGE_LIMIT,
)
from spotify_manager.domain.library_analysis_values import (
    IncompleteLiveResourceError as IncompleteLiveResourceError,
)
from spotify_manager.domain.library_analysis_values import (
    LibraryAnalysisCancelledError as LibraryAnalysisCancelledError,
)
from spotify_manager.domain.library_analysis_values import (
    LibrarySyncError as LibrarySyncError,
)
from spotify_manager.domain.library_analysis_values import (
    LibrarySyncRestoreError as LibrarySyncRestoreError,
)
from spotify_manager.domain.library_analysis_values import (
    LibrarySyncSummary as LibrarySyncSummary,
)
from spotify_manager.domain.library_analysis_values import (
    ResourceSyncSummary as ResourceSyncSummary,
)
from spotify_manager.domain.library_analysis_values import RetryNotice as RetryNotice
from spotify_manager.infrastructure import library_analysis_backups as analysis_backups
from spotify_manager.infrastructure import library_analysis_files as analysis_files
from spotify_manager.infrastructure import library_analysis_restore as analysis_restore
from spotify_manager.infrastructure.library_analysis_errors import AnalysisFailure
from spotify_manager.infrastructure.library_analysis_retry import LibraryRetry
from spotify_manager.infrastructure.library_records import (
    current_stats_history_key as current_stats_history_key,
)
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


TRANSIENT_RETRY_BASE_SECONDS = 10
TRANSIENT_RETRY_MAX_SECONDS = 30 * 60
CHECKPOINT_VERSION = 1
_FollowedArtistsEndpointUnavailableError = (
    analysis_values._FollowedArtistsEndpointUnavailableError
)

AnalysisMode = Literal["async", "sync", "mirrors"]
ResourceName = Literal["albums", "tracks", "artists"]
MirrorRefreshMode = Literal["incremental", "full"]
Echo = Callable[[str], None]
ProgressCallback = Callable[[ResourceName, int, int | None, str], None]
CancelCheck = Callable[[], bool]
Sleep = Callable[[float], None]
LibraryModel = YourLibraryAlbum | YourLibraryTrack | YourLibraryArtist


RetryWait = Callable[[RetryNotice], bool]


# Backwards-compatible type name for callers that supplied custom paths.
LibrarySyncPaths = LibraryAnalysisPaths
FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_ASYNC_PATHS = LibraryAnalysisPaths.for_files_dir(FILES_DIR, "async")
DEFAULT_SYNC_PATHS = LibraryAnalysisPaths.for_files_dir(FILES_DIR, "sync")
DEFAULT_LIVE_MIRROR_PATHS = LibraryAnalysisPaths.for_files_dir(FILES_DIR, "mirrors")
DEFAULT_PATHS = DEFAULT_SYNC_PATHS


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp.

    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    """Return a sortable identifier for one analysis run.

    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def write_json_atomic(path: Path, value: object) -> None:
    """Write JSON through a sibling temporary file and atomically replace it.

    Args:
        path: Original complete file or staging location.
        value: Original complete JSON value to accept.
    """
    return analysis_files.write_json_atomic(path, value)


def load_json(path: Path, default: object | None = None) -> Any:
    """Load JSON, returning ``default`` when the file does not exist.

    Args:
        path: Original complete file or staging location.
        default: Original value returned when the file is absent.


    Returns:
        Unvalidated original external JSON or the caller-supplied default.
    """
    return analysis_files.load_json(path, default)


def append_event(
    paths: LibraryAnalysisPaths,
    run_id: str,
    event: str,
    **details: object,
) -> None:
    """Append one durable JSON-lines audit event.

    Args:
        paths: Original independent output family.
        run_id: Original sortable run identity.
        event: Original audit event name.
        details: Original complete audit facts, including unknown keys.
    """
    return analysis_files.append_event(utc_now, paths, run_id, event, **details)


def write_models(path: Path, models: Sequence[BaseModel]) -> None:
    """Atomically write a list of Pydantic models.

    Args:
        path: Original complete file or staging location.
        models: Original complete ordered model values.
    """
    return analysis_files.write_models(
        path, models, write=write_json_atomic, publish=_publish_restored
    )


def append_models_jsonl(path: Path, models: Sequence[BaseModel]) -> None:
    """Append models to a resumable JSON-lines staging file.

    Args:
        path: Original complete file or staging location.
        models: Original complete ordered model values.
    """
    return analysis_files.append_models_jsonl(path, models)


def load_model_list[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load a JSON array of models, treating a missing file as empty.

    Args:
        path: Original complete file or staging location.
        model: Original tolerant model constructor.


    Returns:
        Original complete models in stored array order.
    """
    return analysis_files.load_model_list(path, model, read=load_json)


def load_models_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load models from JSON-lines staging, ignoring a torn final line.

    Args:
        path: Original complete file or staging location.
        model: Original tolerant model constructor.


    Returns:
        Original accepted staged models before a torn final record.
    """
    return analysis_files.load_models_jsonl(path, model)


def deduplicate_models[T: LibraryModel](models: Sequence[T]) -> list[T]:
    """Deduplicate models by Spotify id while preserving the newest value.

    Args:
        models: Original complete ordered model values.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    from spotify_manager.infrastructure.library_models import (
        deduplicate_models as deduplicate,
    )

    return deduplicate(models)


def load_your_library(paths: LibraryAnalysisPaths) -> YourLibraryFile:
    """Load the Spotify export used exclusively by async analysis.

    Args:
        paths: Original independent output family.


    Returns:
        Original validated export authority.
    """
    return analysis_files.load_your_library(paths, read=load_json)


def album_from_saved_item(item: object) -> YourLibraryAlbum | None:
    """Convert one Spotify saved-album item into the local model.

    Args:
        item: Original unvalidated Spotify boundary row.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    from spotify_manager.infrastructure.library_models import (
        album_from_saved_item as parse_album,
    )

    return parse_album(item)


def track_from_saved_item(item: object) -> YourLibraryTrack | None:
    """Convert one Spotify saved-track item into the local model.

    Args:
        item: Original unvalidated Spotify boundary row.


    Returns:
        Original saved-track model or none for unusable raw facts.
    """
    return analysis_files.track_from_saved_item(item)


def artist_from_api_item(item: object) -> YourLibraryArtist | None:
    """Convert one Spotify artist object into the local model.

    Args:
        item: Original unvalidated Spotify boundary row.


    Returns:
        Original artist model or none for unusable raw facts.
    """
    return analysis_files.artist_from_api_item(item)


def model_diff(
    previous: Sequence[LibraryModel],
    current: Sequence[LibraryModel],
) -> tuple[list[LibraryModel], list[LibraryModel]]:
    """Return models added to and removed from a Spotify-id keyed mirror.

    Args:
        previous: Original complete models before analysis.
        current: Original complete models after analysis.


    Returns:
        Original added and removed newest-value models in encounter order.
    """
    return analysis_policy.model_diff(previous, current)


def stats_report_for_analysis(
    previous_albums: Sequence[YourLibraryAlbum],
    albums: Sequence[YourLibraryAlbum],
    previous_tracks: Sequence[YourLibraryTrack],
    tracks: Sequence[YourLibraryTrack],
    previous_artists: Sequence[YourLibraryArtist],
    artists: Sequence[YourLibraryArtist],
) -> StatsReport:
    """Build a stats report from exact pre/post analysis mirrors.

    Args:
        previous_albums: Original pre-analysis saved albums.
        albums: Original complete saved-album facts.
        previous_tracks: Original pre-analysis liked tracks.
        tracks: Original complete liked-track facts.
        previous_artists: Original pre-analysis followed artists.
        artists: Original complete followed-artist facts.


    Returns:
        Original size, membership-difference and growth counts.
    """
    return analysis_records.stats_report_for_analysis(
        previous_albums, albums, previous_tracks, tracks, previous_artists, artists
    )


def resource_summary(
    resource: ResourceName,
    source: str,
    previous: Sequence[LibraryModel],
    current: Sequence[LibraryModel],
    skipped: int,
) -> ResourceSyncSummary:
    """Build one resource summary and exact diff counts.

    Args:
        resource: Original active library resource identity.
        source: Original source authority or publication label.
        previous: Original complete models before analysis.
        current: Original complete models after analysis.
        skipped: Original skipped raw-row count.


    Returns:
        Original source and exact pre/post difference counts.
    """
    return analysis_policy.resource_summary(
        resource, source, previous, current, skipped
    )


def backup_targets(paths: LibraryAnalysisPaths) -> dict[str, Path]:
    """Return every generated file changed by publication.

    Args:
        paths: Original independent output family.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_backups.backup_targets(paths)


def create_backup_manifest(
    paths: LibraryAnalysisPaths,
    run_id: str,
    previous: dict[ResourceName, Sequence[LibraryModel]],
    current: dict[ResourceName, Sequence[LibraryModel]],
    report: StatsReport,
    summaries: tuple[ResourceSyncSummary, ...],
) -> Path:
    """Snapshot generated files and record exact changes for review and undo.

    Args:
        paths: Original independent output family.
        run_id: Original sortable run identity.
        previous: Original complete models before analysis.
        current: Original complete models after analysis.
        report: Original complete pre/post analysis statistics.
        summaries: Original ordered resource outcomes.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_backups.create_backup_manifest(
        paths, run_id, previous, current, report, summaries, analysis_storage()
    )


def pre_analysis_stats_history(
    paths: LibraryAnalysisPaths,
    backup_dir: Path,
) -> dict[str, object]:
    """Load stats from the backup so interrupted publication is repeatable.

    Args:
        paths: Original independent output family.
        backup_dir: Original accepted undo snapshot directory.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_backups.pre_analysis_stats_history(
        paths, backup_dir, analysis_storage()
    )


def sort_resources(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
) -> tuple[list[YourLibraryAlbum], list[YourLibraryTrack], list[YourLibraryArtist]]:
    """Deduplicate and apply Spotify-like output ordering.

    Args:
        albums: Original complete saved-album facts.
        tracks: Original complete liked-track facts.
        artists: Original complete followed-artist facts.


    Returns:
        Original deduplicated albums, tracks and artists in output order.
    """
    return analysis_records.sort_resources(albums, tracks, artists)


def finalize_analysis(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
) -> LibrarySyncSummary:
    """Publish completed staging data with an idempotent undo snapshot.

    Args:
        albums: Original complete saved-album facts.
        tracks: Original complete liked-track facts.
        artists: Original complete followed-artist facts.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_publication_owner.finalize_analysis(
        analysis_session(paths, cast(Checkpoint, checkpoint)),
        analysis_publication(),
        albums,
        tracks,
        artists,
    )


def create_live_mirror_backup_manifest(
    paths: LibraryAnalysisPaths,
    run_id: str,
    previous: dict[ResourceName, Sequence[LibraryModel]],
    current: dict[ResourceName, Sequence[LibraryModel]],
    summaries: tuple[ResourceSyncSummary, ...],
) -> Path:
    """Back up the two canonical mirrors before a live refresh publishes.

    Args:
        paths: Original independent output family.
        run_id: Original sortable run identity.
        previous: Original complete models before analysis.
        current: Original complete models after analysis.
        summaries: Original ordered resource outcomes.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_backups.create_live_mirror_backup_manifest(
        paths, run_id, previous, current, summaries, analysis_storage()
    )


def finalize_live_mirrors(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
) -> LibrarySyncSummary:
    """Atomically publish canonical album and liked-track mirrors.

    Args:
        albums: Original complete saved-album facts.
        tracks: Original complete liked-track facts.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_publication_owner.finalize_mirrors(
        analysis_session(paths, cast(Checkpoint, checkpoint)),
        analysis_publication(),
        albums,
        tracks,
    )


def live_mirror_resource_paths(
    paths: LibraryAnalysisPaths,
    resource: ResourceName,
) -> LibraryAnalysisPaths:
    """Give each canonical resource an independent resumable workspace.

    Args:
        paths: Original independent output family.
        resource: Original active library resource identity.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_values_paths.scoped_paths(paths, resource)


def _live_resource_config(
    paths: LibraryAnalysisPaths,
    resource: ResourceName,
) -> tuple[
    Path,
    type[LibraryModel],
    Callable[[LibraryModel], tuple[int, ...]],
]:
    """Return the output path, model, and ordering key for one live mirror."""
    return analysis_values_paths.resource_config(paths, resource)


def finalize_live_mirror_resource(
    resource: ResourceName,
    models: list[LibraryModel],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
) -> LibrarySyncSummary:
    """Atomically publish exactly one canonical mirror with an undo snapshot.

    Args:
        resource: Original active library resource identity.
        models: Original complete ordered model values.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_publication_owner.finalize_resource(
        analysis_session(paths, cast(Checkpoint, checkpoint)),
        analysis_publication(),
        resource,
        models,
    )


def export_fingerprint(path: Path) -> dict[str, int]:
    """Return enough metadata to detect an export replaced between resumes.

    Args:
        path: Original complete file or staging location.


    Returns:
        Original export size and nanosecond modification time.
    """
    return analysis_files.export_fingerprint(path)


def new_checkpoint(
    paths: LibraryAnalysisPaths,
    mirror_refresh_mode: MirrorRefreshMode | None = None,
) -> dict[str, Any]:
    """Create a fresh checkpoint for one mode.

    Args:
        paths: Original independent output family.
        mirror_refresh_mode: Original explicit full-versus-incremental choice.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return cast(
        dict[str, Any],
        analysis_checkpoints.new_checkpoint(
            analysis_storage(), paths, mirror_refresh_mode
        ),
    )


def load_or_create_checkpoint(
    paths: LibraryAnalysisPaths,
    mirror_refresh_mode: MirrorRefreshMode | None = None,
) -> dict[str, Any]:
    """Resume a compatible incomplete checkpoint or start a fresh run.

    Args:
        paths: Original independent output family.
        mirror_refresh_mode: Original explicit full-versus-incremental choice.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return cast(
        dict[str, Any],
        analysis_checkpoints.load_or_create_checkpoint(
            analysis_storage(), paths, mirror_refresh_mode
        ),
    )


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
    """Prepare and stage one export resource, with resumable boundaries.

    Args:
        resource: Original active library resource identity.
        models: Original complete ordered model values.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        model_type: Original tolerant resource model constructor.
        sort_key: Original resource-specific output ordering rule.
        progress_callback: Original optional resource-level progress callback.
        cancel_check: Original optional durable cancellation observation.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_export.prepare_export_resource(
        analysis_session(
            paths,
            cast(Checkpoint, checkpoint),
            progress=progress_callback,
            cancel_check=cancel_check,
        ),
        resource,
        models,
        model_type,
        sort_key,
    )


def analyse_library_async_routine(
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_ASYNC_PATHS,
) -> LibrarySyncSummary:
    """Build ``*_async`` mirrors exclusively from ``YourLibrary.json``.

    Args:
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        cancel_check: Original optional durable cancellation observation.
        paths: Original independent output family.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    del echo
    if paths.mode != "async":
        raise LibrarySyncError("Export analysis requires async output paths.")
    checkpoint = load_or_create_checkpoint(paths)
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        progress=progress_callback,
        cancel_check=cancel_check,
    )
    with AnalysisFailure(
        session,
        "Export analysis failed",
        (LibraryAnalysisCancelledError, KeyboardInterrupt),
    ):
        return analysis_runs.analyse_export(session, analysis_publication())


def retry_delay(base: int, maximum: int, attempt: int) -> int:
    """Return the capped exponential delay for a one-based attempt.

    Args:
        base: Original first transient retry delay.
        maximum: Original maximum transient retry delay.
        attempt: Original one-based transient attempt.


    Returns:
        Original capped exponential delay, including zero-wait semantics.
    """
    return analysis_policy.retry_delay(base, maximum, attempt)


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
    max_attempts: int | None = None,
) -> T:
    """Call Spotify, retrying 5xx and transport failures with backoff.

    Args:
        operation: Original complete caller-supplied live request.
        description: Original visible operation label.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        retry_wait: Original optional interactive retry decision.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
        max_attempts: Original optional maximum request attempts.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    retry = LibraryRetry(
        paths,
        cast(Checkpoint, checkpoint),
        analysis_storage(),
        echo,
        retry_wait,
        sleep,
        retry_base_seconds,
        retry_max_seconds,
    )
    return retry.call(operation, description, max_attempts)


def _default_retry_wait(delay: int, sleep: Sleep) -> bool:
    """Wait for a retry when no interactive callback was supplied."""
    sleep(delay)
    return True


def check_cancel(cancel_check: CancelCheck | None) -> None:
    """Raise a clean pause signal at a durable page boundary.

    Args:
        cancel_check: Original optional durable cancellation observation.
    """
    if cancel_check is not None and cancel_check():
        raise LibraryAnalysisCancelledError("Live analysis paused by request.")


def page_items(page: object, resource: ResourceName) -> list[object]:
    """Validate and return the item list from an offset page.

    Args:
        page: Original unvalidated live page envelope.
        resource: Original active library resource identity.


    Returns:
        The original mutable raw offset-page item list.
    """
    return analysis_files.page_items(page, resource)


def followed_artist_page_items(page: object) -> tuple[list[object], dict[str, object]]:
    """Validate and unpack a followed-artists cursor page.

    Args:
        page: Original unvalidated live page envelope.


    Returns:
        Original mutable artist items and page envelope.
    """
    return analysis_files.followed_artist_page_items(page)


def fetch_followed_artists_page(
    sp: Spotify,
    after: str | None,
) -> object:
    """Read one cursor page, surfacing Spotify's common 502 immediately.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        after: Original current or stored artist cursor.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    try:
        return sp.current_user_followed_artists(
            limit=ARTIST_PAGE_LIMIT,
            after=after,
        )
    except SpotifyException as exc:
        if exc.http_status == 502:
            raise _FollowedArtistsEndpointUnavailableError(
                "the followed-artists endpoint returned HTTP 502"
            ) from exc
        raise


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
    """Scan one offset resource monotonically without reacting to total changes.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        resource: Original active library resource identity.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
    """
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        echo=echo,
        progress=progress_callback,
        spotify=sp,
        retry_wait=retry_wait,
        cancel_check=cancel_check,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    analysis_offsets.scan_initial(session, resource)


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
    """Re-read the newest pages until two passes find no additions.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        resource: Original active library resource identity.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
    """
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        echo=echo,
        progress=progress_callback,
        spotify=sp,
        retry_wait=retry_wait,
        cancel_check=cancel_check,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    analysis_offsets.reconcile(session, resource)


def seed_incremental_offset_resource(
    resource: Literal["albums", "tracks"],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
) -> None:
    """Seed resource staging from its mirror before scanning the recent edge.

    Args:
        resource: Original active library resource identity.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
    """
    session = analysis_session(
        paths, cast(Checkpoint, checkpoint), echo=echo, progress=progress_callback
    )
    analysis_offsets.seed_incremental(session, resource)


def artist_verification_candidates_path(paths: LibraryAnalysisPaths) -> Path:
    """Return the resumable candidate list used by artist fallback checks.

    Args:
        paths: Original independent output family.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return paths.staging_dir / "artist_candidates.jsonl"


def latest_export_artists(paths: LibraryAnalysisPaths) -> list[YourLibraryArtist]:
    """Load export artist candidates when a durable export is available.

    Args:
        paths: Original independent output family.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    return analysis_files.latest_export_artists(paths, load_your_library)


def prepare_artist_verification(
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    *,
    full_rebuild: bool,
    echo: Echo,
    reason: str,
) -> None:
    """Prepare a live batch verification fallback without losing checkpoints.

    Args:
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        full_rebuild: Whether to rebuild complete original live authority.
        echo: Original visible output callback.
        reason: Original visible fallback explanation.
    """
    session = analysis_session(paths, cast(Checkpoint, checkpoint), echo=echo)
    analysis_artists.prepare_verification(
        session, full_rebuild=full_rebuild, reason=reason
    )


def verify_artist_candidates(
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
    """Verify fallback candidates in bounded, resumable live API batches.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
    """
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        echo=echo,
        progress=progress_callback,
        spotify=sp,
        retry_wait=retry_wait,
        cancel_check=cancel_check,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    analysis_artists.verify(session)


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
    """Scan followed artists once with cursor pagination.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
    """
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        echo=echo,
        progress=progress_callback,
        spotify=sp,
        retry_wait=retry_wait,
        cancel_check=cancel_check,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    analysis_artists.scan_initial(session)


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
    """Fully rescan cursor-ordered artists until two passes find no additions.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        paths: Original independent output family.
        checkpoint: Original durable progress, preserving unknown fields.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
    """
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        echo=echo,
        progress=progress_callback,
        spotify=sp,
        retry_wait=retry_wait,
        cancel_check=cancel_check,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    analysis_artists.reconcile(session)


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
    """Build ``*_sync`` mirrors exclusively from the live Spotify API.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        paths: Original independent output family.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    if paths.mode != "sync":
        raise LibrarySyncError("Live analysis requires sync output paths.")
    checkpoint = load_or_create_checkpoint(paths)
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        progress=progress_callback,
        cancel_check=cancel_check,
        spotify=sp,
        echo=echo,
        retry_wait=retry_wait,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    with AnalysisFailure(
        session,
        "Live analysis failed",
        (LibraryAnalysisCancelledError, SpotifyRateLimitError, KeyboardInterrupt),
    ):
        return analysis_runs.analyse_live(session, analysis_publication())


def refresh_live_library_mirrors_routine(
    sp: Spotify,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_LIVE_MIRROR_PATHS,
    sleep: Sleep = default_sleep,
    retry_base_seconds: int = TRANSIENT_RETRY_BASE_SECONDS,
    retry_max_seconds: int = TRANSIENT_RETRY_MAX_SECONDS,
    full_rebuild: bool = False,
) -> LibrarySyncSummary:
    """Merge recent album and track additions or fully rebuild both mirrors.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        paths: Original independent output family.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
        full_rebuild: Whether to rebuild complete original live authority.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    if paths.mode != "mirrors":
        raise LibrarySyncError("Canonical mirror refresh requires mirror paths.")
    refresh_mode: MirrorRefreshMode = "full" if full_rebuild else "incremental"
    checkpoint = load_or_create_checkpoint(paths, refresh_mode)
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        progress=progress_callback,
        cancel_check=cancel_check,
        spotify=sp,
        echo=echo,
        retry_wait=retry_wait,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    with AnalysisFailure(
        session,
        "Live mirror refresh failed",
        (LibraryAnalysisCancelledError, SpotifyRateLimitError, KeyboardInterrupt),
    ):
        return analysis_runs.refresh_mirrors(
            session, analysis_publication(), full_rebuild
        )


def refresh_live_library_resource_routine(
    sp: Spotify,
    resource: ResourceName,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_LIVE_MIRROR_PATHS,
    sleep: Sleep = default_sleep,
    retry_base_seconds: int = TRANSIENT_RETRY_BASE_SECONDS,
    retry_max_seconds: int = TRANSIENT_RETRY_MAX_SECONDS,
    full_rebuild: bool = False,
) -> LibrarySyncSummary:
    """Refresh one canonical library mirror without reading or publishing others.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        resource: Original active library resource identity.
        echo: Original visible output callback.
        progress_callback: Original optional resource-level progress callback.
        retry_wait: Original optional interactive retry decision.
        cancel_check: Original optional durable cancellation observation.
        paths: Original independent output family.
        sleep: Original caller-supplied blocking retry wait.
        retry_base_seconds: Original initial transient retry delay.
        retry_max_seconds: Original capped transient retry delay.
        full_rebuild: Whether to rebuild complete original live authority.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    if paths.mode != "mirrors":
        raise LibrarySyncError("Canonical mirror refresh requires mirror paths.")
    paths = live_mirror_resource_paths(paths, resource)
    refresh_mode: MirrorRefreshMode = "full" if full_rebuild else "incremental"
    checkpoint = load_or_create_checkpoint(paths, refresh_mode)
    session = analysis_session(
        paths,
        cast(Checkpoint, checkpoint),
        progress=progress_callback,
        cancel_check=cancel_check,
        spotify=sp,
        echo=echo,
        retry_wait=retry_wait,
        sleep=sleep,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    with AnalysisFailure(
        session,
        f"Live {resource} mirror refresh failed",
        (LibraryAnalysisCancelledError, SpotifyRateLimitError, KeyboardInterrupt),
    ):
        return analysis_runs.refresh_resource(
            session, analysis_publication(), resource, full_rebuild
        )


def restore_library_sync(
    run_id: str,
    paths: LibraryAnalysisPaths | None = None,
) -> tuple[str, ...]:
    """Restore generated files from one completed async or sync backup.

    Args:
        run_id: Original sortable run identity.
        paths: Original independent output family.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    candidates = (
        [paths]
        if paths is not None
        else [DEFAULT_SYNC_PATHS, DEFAULT_ASYNC_PATHS, DEFAULT_LIVE_MIRROR_PATHS]
    )
    return analysis_restore.restore_library_sync(
        run_id, candidates, analysis_storage(), _publish_restored
    )


# Compatibility alias for integrations that imported the old hybrid entry point.
analyse_library_routine = analyse_library_sync_routine


__all__ = [
    "DEFAULT_ASYNC_PATHS",
    "DEFAULT_LIVE_MIRROR_PATHS",
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
    "refresh_live_library_mirrors_routine",
    "refresh_live_library_resource_routine",
    "restore_library_sync",
]


def _initial_offset_reader(
    sp: Spotify, resource: ResourceName
) -> Callable[..., object]:
    return (
        sp.current_user_saved_albums
        if resource == "albums"
        else sp.current_user_saved_tracks
    )


def _reconcile_offset_reader(
    sp: Spotify, resource: ResourceName
) -> Callable[..., object]:
    return (
        sp.current_user_saved_albums
        if resource == "albums"
        else sp.current_user_saved_tracks
    )


def _reconcile_artist_page(sp: Spotify, after: str | None) -> object:
    return sp.current_user_followed_artists(limit=ARTIST_PAGE_LIMIT, after=after)


def _following_artists(sp: Spotify, identities: list[str]) -> object:
    return sp.current_user_following_artists(identities)


def _publish_restored(path: Path, source: str) -> None:
    publish_managed_path(path, source=source)
