"""Adapt existing observed history callbacks to explicit workflow dependencies."""

from collections.abc import Callable
from datetime import datetime
from functools import partial

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.bootstrap.new_year import AnnualResources
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryStorage
from spotify_manager.infrastructure.legacy.queue_fill import LegacyQueueFill
from spotify_manager.infrastructure.legacy.release_opening import LegacyReleaseOpening
from spotify_manager.infrastructure.legacy.something_old_run import LegacySomethingOld


def annual_history(
    resources: AnnualResources,
    observe: Callable[..., ScrobbleHistorySummary],
    preview: bool,
) -> tuple[Scrobble, ...]:
    """Supply the same observed annual history through the resource boundary.

    Args:
        resources: Original caller-owned annual resources.
        observe: Existing observed history callback.
        preview: Original publication preview flag.

    Returns:
        The original ordered canonical plays.
    """
    summary = observe(
        resources.lastfm,
        expected_username=resources.configuration.lastfm_username,
        full_rebuild=True,
        dry_run=preview,
        progress_callback=resources.echo,
        cancel_check=resources.cancel_check,
    )
    return summary.history


def annual_discoveries(
    resources: AnnualResources,
    observe: Callable[..., object],
    active_year: int,
    preview: bool,
) -> None:
    """Observe the same annual discovery import through the resource boundary.

    Args:
        resources: Original caller-owned annual resources.
        observe: Existing observed import callback.
        active_year: Original source year plus one.
        preview: Original discovery preview flag.
    """
    options: dict[str, object] = {}
    if preview:
        options["dry_run"] = True
    observe(
        resources.sp,
        resources.playlists["queue3"],
        active_year=active_year,
        state_service=resources.selected_service,
        retry_call=resources.retry,
        echo=resources.echo,
        **options,
    )


def _release_progress(callback: Callable[[int, int, str], None], message: str) -> None:
    callback(0, 0, message)


def release_history(
    resources: LegacyReleaseOpening,
    observe: Callable[..., ScrobbleHistorySummary],
    stamp: datetime,
) -> ScrobbleHistorySummary:
    """Supply the same observed release history at its acquisition boundary.

    Args:
        resources: Original release startup resources.
        observe: Existing observed canonical history callback.
        stamp: Original effective UTC timestamp.

    Returns:
        The original complete canonical history summary.
    """
    progress = None
    if resources.progress is not None:
        progress = partial(_release_progress, resources.progress)
    return observe(
        resources.lastfm,
        expected_username=resources.expected_username,
        export_path=resources.export_path,
        legacy_delta_path=resources.legacy_delta_path,
        backup_dir=resources.backup_dir,
        log_path=resources.history_log_path,
        dry_run=False,
        now=stamp,
        progress_callback=progress,
    )


def something_old_history(
    resources: LegacySomethingOld,
    observe: Callable[..., ScrobbleHistorySummary],
    now: datetime,
    preview: bool,
) -> ScrobbleHistorySummary:
    """Supply the same observed history before Something Old ranking.

    Args:
        resources: Original caller-owned routine resources.
        observe: Existing observed history callback.
        now: Original effective UTC timestamp.
        preview: Original history publication preview flag.

    Returns:
        The original canonical history summary.
    """
    return observe(
        resources.lastfm,
        expected_username=resources.username,
        export_path=resources.export_path,
        legacy_delta_path=resources.legacy_delta_path,
        backup_dir=resources.backup_dir,
        log_path=resources.history_log_path,
        dry_run=preview,
        now=now,
        progress_callback=resources.callback,
    )


def queue_history(
    resources: LegacyQueueFill,
    observe: Callable[..., tuple[list[Scrobble], int]],
    preview: bool,
    now: datetime,
) -> tuple[list[Scrobble], int]:
    """Supply the same observed recommendation history before Queue selection.

    Args:
        resources: Original caller-owned Queue resources.
        observe: Existing observed recommendation history callback.
        preview: Original history preview flag.
        now: Original effective UTC timestamp.

    Returns:
        The original ordered plays and live addition count.
    """
    progress = resources._history_progress if resources.callback is not None else None
    return observe(
        resources.lastfm,
        export_path=resources.export_path,
        recent_path=resources.recent_path,
        dry_run=preview,
        now=now,
        progress_callback=progress,
    )


def hydrate_history(storage: LegacyHistoryStorage, service: LibraryDataService) -> None:
    """Inject the original observed managed service at the storage port.

    Args:
        storage: Invocation-owned history storage adapter.
        service: Existing observed hydration and publication fixture.
    """
    storage.data_service = service
    service.hydrate("scrobbles")
