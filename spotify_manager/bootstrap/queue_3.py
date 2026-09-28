"""Compose Queue 3 business workflows with existing external boundaries."""

import json
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.queue_3_execution import Queue3Execution
from spotify_manager.application.queue_3_import import AnnualDiscoveryImport
from spotify_manager.application.queue_3_import_review import AnnualImportReview
from spotify_manager.application.queue_3_planner import Queue3Planner
from spotify_manager.application.queue_3_planner import TransitionReader
from spotify_manager.application.queue_3_planner import stable_release_order
from spotify_manager.application.queue_3_values import AnnualImportSummary
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.bootstrap.new_kids import library_reconciliation
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.legacy.queue_3 import LegacyAnnualImport
from spotify_manager.infrastructure.legacy.queue_3 import LegacyQueue3Catalog
from spotify_manager.interfaces.presenters.queue_3 import Queue3Presenter
from spotify_manager.routines import queue_3 as legacy


def _now() -> str:
    return legacy.datetime.now(UTC).isoformat()


def annual_import(
    client: Spotify,
    retry: RetryCall,
    log_path: Path,
    state_access: RoutineState,
    echo: Callable[[str], None],
) -> AnnualDiscoveryImport:
    """Bind annual import to the caller's original request and checkpoint context.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing request retry and cancellation boundary.
        log_path: Existing audit destination.
        state_access: Already resolved namespace storage.
        echo: Existing output sink.

    Returns:
        An injected annual import workflow with original effect boundaries.
    """
    access = LegacyAnnualImport(client, retry, log_path)
    presentation = Queue3Presenter(echo)
    return AnnualDiscoveryImport(
        access.read,
        access.append,
        access.audit,
        state_access,
        presentation.imported,
        _now,
    )


def _direct_call(operation: Callable[[], object], _description: str) -> object:
    return operation()


def run_import(
    client: Spotify,
    playlist_id: str,
    *,
    active_year: int | None,
    dry_run: bool,
    echo: Callable[[str], None],
    progress_callback: Callable[[int, int, str], None] | None,
    retry_call: RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
) -> AnnualImportSummary:
    """Prepare the standalone annual import in its original observation order.

    Args:
        client: Caller-owned Spotify client.
        playlist_id: Configured Queue 3 destination.
        active_year: Explicit checkpoint year, or the current UTC year.
        dry_run: Whether to clone state and suppress writes.
        echo: Existing output sink.
        progress_callback: Optional progress sink.
        retry_call: Optional retry and cancellation boundary.
        state_path: Existing legacy namespace path.
        state_service: Optional shared state service.
        log_path: Original audit destination.

    Returns:
        The unchanged public annual import summary.

    Raises:
        Queue3Error: Playlist observation, import or state handling fails.
    """
    retry = retry_call or _direct_call
    year = active_year or legacy.datetime.now(UTC).year
    presentation = Queue3Presenter(echo, progress_callback)
    presentation.loading(year - 1)
    owned = legacy.load_owned_playlists(client, retry, playlist_id)
    access = LegacyAnnualImport(client, retry, log_path)
    current = list(access.read(playlist_id))
    state_access = legacy._state_access(state_path, state_service)
    persisted = state_access.load()
    state = json.loads(json.dumps(persisted)) if dry_run else persisted
    importer = annual_import(client, retry, log_path, state_access, echo)
    return AnnualImportReview(importer, presentation).run(
        playlist_id, current, state, owned, year, dry_run
    )


def review_planner(
    client: Spotify,
    retry: RetryCall,
    tracks: dict[str, tuple[ReleaseTrack, ...]],
    liked: dict[str, bool],
    orders: dict[str, object],
    persist: Callable[[], None],
    choose: TransitionReader,
) -> Queue3Planner:
    """Compose chronological planning with caller-owned observations and checkpoints.

    Args:
        client: Existing Spotify client.
        retry: Existing request retry and cancellation boundary.
        tracks: Shared run-scoped track observations.
        liked: Shared run-scoped liked memberships.
        orders: Mutable saved release ordering preferences.
        persist: Original callback after an accepted order.
        choose: Original release-boundary callback.

    Returns:
        Injected planner retaining original request and choice ordering.
    """
    catalog = LegacyQueue3Catalog(client, retry, liked)
    ordering = ReleaseOrdering(stable_release_order, orders, persist)
    return Queue3Planner(catalog.tracks, catalog.evaluate, tracks, ordering, choose)


def _no_checkpoint() -> None:
    return None


def _datetime() -> datetime:
    return legacy.datetime.now(UTC)


def review_execution(
    client: Spotify,
    retry: RetryCall,
    albums_path: Path,
    removed_path: Path,
    log_path: Path,
    echo: Callable[[str], None],
    dry_run: bool,
) -> Queue3Execution:
    """Bind saved-plan execution to original playlist and library boundaries.

    Args:
        client: Existing Spotify client.
        retry: Existing retry and cancellation callback.
        albums_path: Original local album mirror.
        removed_path: Original removal recovery log.
        log_path: Original Queue 3 audit destination, also used for library events.
        echo: Existing output sink.
        dry_run: Whether remote mutations are suppressed.

    Returns:
        Injected saved-plan executor retaining accepted-effect ordering.
    """
    access = LegacyAnnualImport(client, retry, log_path)
    library = library_reconciliation(
        client, retry, albums_path, removed_path, log_path, echo, dry_run
    )
    return Queue3Execution(
        access.append, access.remove, library.reconcile, Queue3Presenter(echo), dry_run
    )
