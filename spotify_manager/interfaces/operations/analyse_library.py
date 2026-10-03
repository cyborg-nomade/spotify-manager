"""Invoke analyse library use cases for CLI and HTTP features."""

from time import sleep as default_sleep
from typing import cast as cast

from spotipy import Spotify as Spotify

from spotify_manager.application import library_analysis_run as analysis_runs
from spotify_manager.application.library_analysis_checkpoint import (
    load_or_create_checkpoint,
)
from spotify_manager.application.library_analysis_values import Checkpoint as Checkpoint
from spotify_manager.application.library_analysis_values import (
    LibraryAnalysisPaths as LibraryAnalysisPaths,
)
from spotify_manager.application.library_analysis_values import (
    scoped_paths as live_mirror_resource_paths,
)
from spotify_manager.bootstrap.library_analysis import _publish as _publish_restored
from spotify_manager.bootstrap.library_analysis import (
    analysis_files as analysis_storage,
)
from spotify_manager.bootstrap.library_analysis import (
    analysis_publication as analysis_publication,
)
from spotify_manager.bootstrap.library_analysis import (
    analysis_session as analysis_session,
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
from spotify_manager.infrastructure import library_analysis_restore as analysis_restore
from spotify_manager.infrastructure.library_analysis_errors import (
    AnalysisFailure as AnalysisFailure,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyRateLimitError as SpotifyRateLimitError,
)
from spotify_manager.routines.analyse_library import (
    DEFAULT_ASYNC_PATHS as DEFAULT_ASYNC_PATHS,
)
from spotify_manager.routines.analyse_library import (
    DEFAULT_LIVE_MIRROR_PATHS as DEFAULT_LIVE_MIRROR_PATHS,
)
from spotify_manager.routines.analyse_library import (
    DEFAULT_SYNC_PATHS as DEFAULT_SYNC_PATHS,
)
from spotify_manager.routines.analyse_library import (
    TRANSIENT_RETRY_BASE_SECONDS as TRANSIENT_RETRY_BASE_SECONDS,
)
from spotify_manager.routines.analyse_library import (
    TRANSIENT_RETRY_MAX_SECONDS as TRANSIENT_RETRY_MAX_SECONDS,
)
from spotify_manager.routines.analyse_library import AnalysisMode as AnalysisMode
from spotify_manager.routines.analyse_library import CancelCheck as CancelCheck
from spotify_manager.routines.analyse_library import Echo as Echo
from spotify_manager.routines.analyse_library import (
    MirrorRefreshMode as MirrorRefreshMode,
)
from spotify_manager.routines.analyse_library import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.analyse_library import ResourceName as ResourceName
from spotify_manager.routines.analyse_library import RetryWait as RetryWait
from spotify_manager.routines.analyse_library import Sleep as Sleep


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
    checkpoint = load_or_create_checkpoint(analysis_storage(), paths)
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
    checkpoint = load_or_create_checkpoint(analysis_storage(), paths)
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
    checkpoint = load_or_create_checkpoint(analysis_storage(), paths, refresh_mode)
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
    checkpoint = load_or_create_checkpoint(analysis_storage(), paths, refresh_mode)
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
    run_id: str, paths: LibraryAnalysisPaths | None = None
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
