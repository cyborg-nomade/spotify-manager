"""Preserve public analysis seams while binding typed inner business stages.

The legacy checkpoint dictionaries remain permissive external boundaries. Inner
stages use typed progress views without changing validation or persisted bytes.
"""

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Literal
from typing import Protocol
from typing import cast

from pydantic import BaseModel
from spotipy import Spotify as LegacySpotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application import library_analysis_artists as analysis_artists
from spotify_manager.application import (
    library_analysis_checkpoint as analysis_checkpoints,
)
from spotify_manager.application import library_analysis_offsets as analysis_offsets
from spotify_manager.application import (
    library_analysis_publication as analysis_publication_owner,
)
from spotify_manager.application import library_analysis_records as analysis_records
from spotify_manager.application import library_analysis_values as analysis_values_paths
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import (
    LibraryAnalysisPaths as LibraryAnalysisPaths,
)
from spotify_manager.application.ports.runtime import AnalysisProgress
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Wait
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.bootstrap.library_analysis import (
    analysis_files as analysis_storage,
)
from spotify_manager.bootstrap.library_analysis import analysis_publication
from spotify_manager.bootstrap.library_analysis import analysis_session
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
from spotify_manager.infrastructure.library_records import (
    current_stats_history_key as current_stats_history_key,
)
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.python_compat.runtime import (
    BlockingAnalysisWait as LegacyAnalysisWait,
)
from spotify_manager.infrastructure.python_compat.runtime import (
    BlockingWait as LegacyWait,
)
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


# UFI


type CancelCheck = CancellationState
type Sleep = Wait


type ProgressCallback = AnalysisProgress


type Echo = Messages


TRANSIENT_RETRY_BASE_SECONDS = 10
TRANSIENT_RETRY_MAX_SECONDS = 30 * 60
CHECKPOINT_VERSION = 1
_FollowedArtistsEndpointUnavailableError = (
    analysis_values._FollowedArtistsEndpointUnavailableError
)

AnalysisMode = Literal["async", "sync", "mirrors"]
ResourceName = Literal["albums", "tracks", "artists"]
MirrorRefreshMode = Literal["incremental", "full"]


LibraryModel = YourLibraryAlbum | YourLibraryTrack | YourLibraryArtist


class RetryWait(Protocol):
    """Own an operator's wait or pause decision after a scheduled retry."""

    async def wait(self, notice: RetryNotice) -> bool:
        """Wait or request a clean pause using the original notice.

        Args:
            notice: Original retry status, attempt and delay.

        Returns:
            Whether the original request should continue.
        """
        ...


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
    return analysis_files.append_event(
        _CompatibilityStorage(), paths, run_id, event, **details
    )


def write_models(path: Path, models: Sequence[BaseModel]) -> None:
    """Atomically write a list of Pydantic models.

    Args:
        path: Original complete file or staging location.
        models: Original complete ordered model values.
    """
    return analysis_files.write_models(path, models, storage=_CompatibilityStorage())


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
    return analysis_files.load_model_list(path, model, storage=_CompatibilityStorage())


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
    return analysis_files.load_your_library(paths, storage=_CompatibilityStorage())


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
        paths, run_id, previous, current, report, summaries, analysis_storage().source
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
        paths, backup_dir, analysis_storage().source
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


async def async_finalize_analysis(
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
    return await analysis_publication_owner.finalize_analysis(
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
        paths, run_id, previous, current, summaries, analysis_storage().source
    )


async def async_finalize_live_mirrors(
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
    return await analysis_publication_owner.finalize_mirrors(
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


async def async_finalize_live_mirror_resource(
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
    return await analysis_publication_owner.finalize_resource(
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


async def async_new_checkpoint(
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
        (
            await analysis_checkpoints.new_checkpoint(
                analysis_storage(), paths, mirror_refresh_mode
            )
        ),
    )


async def async_load_or_create_checkpoint(
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
        (
            await analysis_checkpoints.load_or_create_checkpoint(
                analysis_storage(), paths, mirror_refresh_mode
            )
        ),
    )


async def async_analyse_library_async_routine(
    echo: Echo = STANDARD_OUTPUT,
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
    from spotify_manager.interfaces.operations.analyse_library import (
        analyse_library_async_routine as operation,
    )

    return await operation(echo, progress_callback, cancel_check, paths)


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


async def _default_retry_wait(delay: int, sleep: Sleep) -> bool:
    """Wait for a retry when no interactive callback was supplied."""
    await sleep.sleep(delay)
    return True


def check_cancel(cancel_check: CancelCheck | None) -> None:
    """Raise a clean pause signal at a durable page boundary.

    Args:
        cancel_check: Original optional durable cancellation observation.
    """
    if cancel_check is not None and cancel_check.is_set():
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


async def async_fetch_followed_artists_page(
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
        return await sp.current_user_followed_artists(
            limit=ARTIST_PAGE_LIMIT,
            after=after,
        )
    except SpotifyException as exc:
        if exc.http_status == 502:
            raise _FollowedArtistsEndpointUnavailableError(
                "the followed-artists endpoint returned HTTP 502"
            ) from exc
        raise


async def async_sync_initial_offset_resource(
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
    await analysis_offsets.scan_initial(session, resource)


async def async_reconcile_offset_resource(
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
    await analysis_offsets.reconcile(session, resource)


async def async_seed_incremental_offset_resource(
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
    await analysis_offsets.seed_incremental(session, resource)


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
    return [] if not paths.your_library.exists() else load_your_library(paths).artists


async def async_prepare_artist_verification(
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
    await analysis_artists.prepare_verification(
        session, full_rebuild=full_rebuild, reason=reason
    )


async def async_verify_artist_candidates(
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
    await analysis_artists.verify(session)


async def async_sync_initial_artists(
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
    await analysis_artists.scan_initial(session)


async def async_reconcile_artists(
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
    await analysis_artists.reconcile(session)


async def async_analyse_library_sync_routine(
    sp: Spotify,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_SYNC_PATHS,
    sleep: Sleep = asyncio,
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
    from spotify_manager.interfaces.operations.analyse_library import (
        analyse_library_sync_routine as operation,
    )

    return await operation(
        sp,
        echo,
        progress_callback,
        retry_wait,
        cancel_check,
        paths,
        sleep,
        retry_base_seconds,
        retry_max_seconds,
    )


async def async_refresh_live_library_mirrors_routine(
    sp: Spotify,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_LIVE_MIRROR_PATHS,
    sleep: Sleep = asyncio,
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
    from spotify_manager.interfaces.operations.analyse_library import (
        refresh_live_library_mirrors_routine as operation,
    )

    return await operation(
        sp,
        echo,
        progress_callback,
        retry_wait,
        cancel_check,
        paths,
        sleep,
        retry_base_seconds,
        retry_max_seconds,
        full_rebuild,
    )


async def async_refresh_live_library_resource_routine(
    sp: Spotify,
    resource: ResourceName,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_LIVE_MIRROR_PATHS,
    sleep: Sleep = asyncio,
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
    from spotify_manager.interfaces.operations.analyse_library import (
        refresh_live_library_resource_routine as operation,
    )

    return await operation(
        sp,
        resource,
        echo,
        progress_callback,
        retry_wait,
        cancel_check,
        paths,
        sleep,
        retry_base_seconds,
        retry_max_seconds,
        full_rebuild,
    )


async def async_restore_library_sync(
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
    from spotify_manager.interfaces.operations.analyse_library import (
        restore_library_sync as operation,
    )

    return await operation(run_id, paths)


# Compatibility alias for integrations that imported the old hybrid entry point.
analyse_library_routine = async_analyse_library_sync_routine


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
) -> Callable[..., Awaitable[object]]:
    return (
        sp.current_user_saved_albums
        if resource == "albums"
        else sp.current_user_saved_tracks
    )


def _reconcile_offset_reader(
    sp: Spotify, resource: ResourceName
) -> Callable[..., Awaitable[object]]:
    return (
        sp.current_user_saved_albums
        if resource == "albums"
        else sp.current_user_saved_tracks
    )


async def _reconcile_artist_page(sp: Spotify, after: str | None) -> object:
    return await sp.current_user_followed_artists(limit=ARTIST_PAGE_LIMIT, after=after)


async def _following_artists(sp: Spotify, identities: list[str]) -> object:
    return await sp.current_user_following_artists(identities)


def _publish_restored(path: Path, source: str) -> None:
    publish_managed_path(path, source=source)


class _CompatibilityStorage:
    """Adapt the retained public file helpers at their external compatibility edge."""

    def read(self, path: Path, default: object | None = None) -> object:
        """Read the retained public JSON seam.

        Args:
            path: File location.
            default: Missing-file result.

        Returns:
            Unvalidated stored value.
        """
        if default is None:
            return load_json(path)
        return load_json(path, default=default)

    def write(self, path: Path, value: object) -> None:
        """Accept complete JSON atomically.

        Args:
            path: Destination.
            value: Complete payload.
        """
        write_json_atomic(path, value)

    def publish_path(self, path: Path, source: str) -> None:
        """Publish an accepted managed artifact.

        Args:
            path: Accepted file.
            source: Provenance label.
        """
        _publish_restored(path, source)

    def clock(self) -> str:
        """Observe the original audit clock.

        Returns:
            Current UTC timestamp.
        """
        return utc_now()


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
    from spotify_manager.bootstrap.execution import run_python

    return run_python(
        async_finalize_analysis(albums, tracks, artists, paths, checkpoint)
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
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_finalize_live_mirrors(albums, tracks, paths, checkpoint))


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
    from spotify_manager.bootstrap.execution import run_python

    return run_python(
        async_finalize_live_mirror_resource(resource, models, paths, checkpoint)
    )


def new_checkpoint(
    paths: LibraryAnalysisPaths, mirror_refresh_mode: MirrorRefreshMode | None = None
) -> dict[str, Any]:
    """Create a fresh checkpoint for one mode.

    Args:
        paths: Original independent output family.
        mirror_refresh_mode: Original explicit full-versus-incremental choice.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_new_checkpoint(paths, mirror_refresh_mode))


def load_or_create_checkpoint(
    paths: LibraryAnalysisPaths, mirror_refresh_mode: MirrorRefreshMode | None = None
) -> dict[str, Any]:
    """Resume a compatible incomplete checkpoint or start a fresh run.

    Args:
        paths: Original independent output family.
        mirror_refresh_mode: Original explicit full-versus-incremental choice.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_load_or_create_checkpoint(paths, mirror_refresh_mode))


def analyse_library_async_routine(
    echo: Echo = STANDARD_OUTPUT,
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
    from spotify_manager.bootstrap.execution import run_python

    return run_python(
        async_analyse_library_async_routine(
            echo, progress_callback, cancel_check, paths
        )
    )


def fetch_followed_artists_page(sp: LegacySpotify, after: str | None) -> object:
    """Read one cursor page, surfacing Spotify's common 502 immediately.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        after: Original current or stored artist cursor.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_fetch_followed_artists_page(legacy_spotify(sp), after))


def sync_initial_offset_resource(
    sp: LegacySpotify,
    resource: Literal["albums", "tracks"],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None | LegacyAnalysisWait,
    cancel_check: CancelCheck | None,
    sleep: Sleep | LegacyWait,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_sync_initial_offset_resource(
            legacy_spotify(sp),
            resource,
            paths,
            checkpoint,
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
        )
    )


def reconcile_offset_resource(
    sp: LegacySpotify,
    resource: Literal["albums", "tracks"],
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None | LegacyAnalysisWait,
    cancel_check: CancelCheck | None,
    sleep: Sleep | LegacyWait,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_reconcile_offset_resource(
            legacy_spotify(sp),
            resource,
            paths,
            checkpoint,
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
        )
    )


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
    from spotify_manager.bootstrap.execution import run_python

    return run_python(
        async_seed_incremental_offset_resource(
            resource, paths, checkpoint, echo, progress_callback
        )
    )


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
    from spotify_manager.bootstrap.execution import run_python

    return run_python(
        async_prepare_artist_verification(
            paths, checkpoint, full_rebuild=full_rebuild, echo=echo, reason=reason
        )
    )


def verify_artist_candidates(
    sp: LegacySpotify,
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None | LegacyAnalysisWait,
    cancel_check: CancelCheck | None,
    sleep: Sleep | LegacyWait,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_verify_artist_candidates(
            legacy_spotify(sp),
            paths,
            checkpoint,
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
        )
    )


def sync_initial_artists(
    sp: LegacySpotify,
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None | LegacyAnalysisWait,
    cancel_check: CancelCheck | None,
    sleep: Sleep | LegacyWait,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_sync_initial_artists(
            legacy_spotify(sp),
            paths,
            checkpoint,
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
        )
    )


def reconcile_artists(
    sp: LegacySpotify,
    paths: LibraryAnalysisPaths,
    checkpoint: dict[str, Any],
    echo: Echo,
    progress_callback: ProgressCallback | None,
    retry_wait: RetryWait | None | LegacyAnalysisWait,
    cancel_check: CancelCheck | None,
    sleep: Sleep | LegacyWait,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_reconcile_artists(
            legacy_spotify(sp),
            paths,
            checkpoint,
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
        )
    )


def analyse_library_sync_routine(
    sp: LegacySpotify,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None | LegacyAnalysisWait = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_SYNC_PATHS,
    sleep: Sleep | LegacyWait = asyncio,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_analyse_library_sync_routine(
            legacy_spotify(sp),
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            paths,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
        )
    )


def refresh_live_library_mirrors_routine(
    sp: LegacySpotify,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None | LegacyAnalysisWait = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_LIVE_MIRROR_PATHS,
    sleep: Sleep | LegacyWait = asyncio,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_refresh_live_library_mirrors_routine(
            legacy_spotify(sp),
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            paths,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
            full_rebuild,
        )
    )


def refresh_live_library_resource_routine(
    sp: LegacySpotify,
    resource: ResourceName,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_wait: RetryWait | None | LegacyAnalysisWait = None,
    cancel_check: CancelCheck | None = None,
    paths: LibraryAnalysisPaths = DEFAULT_LIVE_MIRROR_PATHS,
    sleep: Sleep | LegacyWait = asyncio,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.runtime import PythonAnalysisWait
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_refresh_live_library_resource_routine(
            legacy_spotify(sp),
            resource,
            echo,
            progress_callback,
            PythonAnalysisWait(retry_wait) if retry_wait is not None else None,
            cancel_check,
            paths,
            PythonWait(sleep),
            retry_base_seconds,
            retry_max_seconds,
            full_rebuild,
        )
    )


def restore_library_sync(
    run_id: str, paths: LibraryAnalysisPaths | None = None
) -> tuple[str, ...]:
    """Restore generated files from one completed async or sync backup.

    Args:
        run_id: Original sortable run identity.
        paths: Original independent output family.


    Returns:
        Original complete result with unchanged source and recovery semantics.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_restore_library_sync(run_id, paths))
