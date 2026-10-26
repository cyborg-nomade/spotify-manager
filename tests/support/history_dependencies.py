"""Adapt existing observed history callbacks to explicit workflow dependencies."""

from collections.abc import Callable
from datetime import datetime
from typing import cast

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.application.ports.runtime import ReviewProgressMessages
from spotify_manager.bootstrap.history import HistoryCancellation
from spotify_manager.bootstrap.new_year import AnnualResources
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryReader
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryStorage
from spotify_manager.infrastructure.legacy.queue_fill import LegacyQueueFill


def annual_history(
    workflow: HistoryRefresh,
    observe: Callable[..., ScrobbleHistorySummary],
    username: str | None,
    preview: bool,
    rebuild: bool,
) -> ScrobbleHistorySummary:
    """Supply original annual history through its explicit named stage.

    Args:
        workflow: Configured complete history stage.
        observe: Existing frozen observation boundary.
        username: Original expected account.
        preview: Original publication behavior.
        rebuild: Original full-rebuild flag.

    Returns:
        Original complete refresh result.
    """
    reader = cast(LegacyHistoryReader, workflow.reader)
    return observe(
        reader.client,
        expected_username=username,
        full_rebuild=rebuild,
        dry_run=preview,
        progress_callback=cast(OptionalMessages, workflow.progress).output,
        cancel_check=cast(HistoryCancellation, workflow.check_cancel).state,
    )


def annual_discoveries(
    workflow: AnnualDiscoveries,
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
    resources = cast(AnnualResources, workflow.source)
    options: dict[str, object] = {}
    if preview:
        options["dry_run"] = True
    observe(
        resources.sp,
        resources.playlists["queue3"],
        active_year=active_year,
        state_service=resources.selected_service,
        retry_call=resources.retry,
        echo=resources.output,
        **options,
    )


def _release_progress(callback: Callable[[int, int, str], None], message: str) -> None:
    callback(0, 0, message)


def release_history(
    workflow: HistoryRefresh,
    observe: Callable[..., ScrobbleHistorySummary],
    username: str | None,
    preview: bool,
    rebuild: bool,
    stamp: datetime,
) -> ScrobbleHistorySummary:
    """Supply original refresh observations through the explicit named stage.

    Args:
        workflow: Configured original history stage.
        observe: Existing frozen refresh observation.
        username: Original expected account.
        preview: Original history preview behavior.
        rebuild: Original full rebuild behavior.
        stamp: Original effective UTC timestamp.

    Returns:
        Original complete canonical refresh summary.
    """
    storage = cast(LegacyHistoryStorage, workflow.storage)
    reader = cast(LegacyHistoryReader, workflow.reader)
    progress = cast(OptionalMessages, workflow.progress).output
    return observe(
        reader.client,
        expected_username=username,
        export_path=storage.export_path,
        legacy_delta_path=storage.legacy_path,
        backup_dir=storage.backup_dir,
        log_path=storage.log_path,
        dry_run=preview,
        now=stamp,
        progress_callback=progress,
    )


something_old_history = release_history


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
    progress = (
        ReviewProgressMessages(resources)
        if resources.callbacks.progress_callback is not None
        else None
    )
    return observe(
        resources.lastfm,
        export_path=resources.resources.export_path,
        recent_path=resources.resources.recent_path,
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
