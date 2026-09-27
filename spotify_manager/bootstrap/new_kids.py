"""Compose ordinary discovery review decisions with caller-owned integrations."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.composer_routes import ReleaseChoiceReader
from spotify_manager.application.discovery_completion import DiscoveryCompletion
from spotify_manager.application.discovery_library import DiscoveryLibraryReconciliation
from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.new_kids_execution import NewKidsExecution
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryAudit
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryCatalog
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryLibrary
from spotify_manager.infrastructure.legacy.discovery_execution import (
    LegacyDiscoveryEffects,
)
from spotify_manager.interfaces.presenters.new_kids import NewKidsPresenter


def review_planner(
    client: Spotify,
    retry: RetryCall,
    choose: ReleaseChoiceReader,
    *,
    year: int,
    dry_run: bool,
    history: AnnualScrobbleIndex,
    release_limit: int,
    studio_minimum: int,
    log_path: Path,
    echo: Callable[[str], None],
    catalogs: dict[str, tuple[RankedRelease, ...]],
    tracks: dict[str, tuple[CatalogTrack, ...]],
    liked: dict[str, bool],
    works: dict[str, tuple[PlaylistTrack, ...]],
) -> NewKidsPlanner:
    """Bind the original shared caches and effect boundaries to the release planner.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        choose: Existing release-choice callback.
        year: Original active year.
        dry_run: Whether planned results describe a preview.
        history: Current-year normalized listening observations.
        release_limit: Original studio preference and completion count.
        studio_minimum: Original studio distinct-title completion minimum.
        log_path: Existing routine audit destination.
        echo: Existing CLI or job message sink.
        catalogs: Shared accepted artist catalog cache.
        tracks: Shared accepted catalog-track cache.
        liked: Shared accepted live memberships.
        works: Shared accepted works-playlist cache.

    Returns:
        Planner over the existing invocation-owned observations and callbacks.
    """
    access = LegacyDiscoveryCatalog(client, retry)
    observations = DiscoveryObservations(
        access, history, release_limit, studio_minimum, catalogs, tracks, liked, works
    )
    return NewKidsPlanner(
        observations,
        choose,
        LegacyDiscoveryAudit(log_path),
        NewKidsPresenter(echo),
        year,
        dry_run,
    )


def library_reconciliation(
    client: Spotify,
    retry: RetryCall,
    albums_path: Path,
    removed_path: Path,
    log_path: Path,
    echo: Callable[[str], None],
    dry_run: bool,
) -> DiscoveryLibraryReconciliation:
    """Compose release-boundary reconciliation with existing integrations.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry and cancellation callback.
        albums_path: Existing local album mirror.
        removed_path: Existing removed-album recovery log.
        log_path: Existing routine audit destination.
        echo: Existing CLI or job message sink.
        dry_run: Whether to suppress remote and mirror writes.

    Returns:
        Reconciliation service retaining the original effect boundaries.
    """
    return DiscoveryLibraryReconciliation(
        LegacyDiscoveryLibrary(client, retry, albums_path, removed_path),
        LegacyDiscoveryAudit(log_path),
        NewKidsPresenter(echo),
        dry_run,
    )


def review_execution(
    client: Spotify,
    retry: RetryCall,
    *,
    state_access: RoutineState,
    state: dict[str, object],
    live_ids: set[str],
    playlist_id: str,
    label: str,
    newfoundland: str,
    unlucky: str,
    great_seed: str,
    year: int,
    albums_path: Path,
    artists_path: Path,
    removed_path: Path,
    log_path: Path,
    echo: Callable[[str], None],
    dry_run: bool,
    clock: Callable[[], datetime],
) -> NewKidsExecution:
    """Compose review effects with the original invocation-owned state and paths.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        state_access: Existing namespace checkpoint boundary.
        state: Mutable complete namespace.
        live_ids: Shared observed/projected review membership.
        playlist_id: Review playlist identifier.
        label: Original review playlist label.
        newfoundland: Configured promotion destination.
        unlucky: Configured nonqualifying destination.
        great_seed: Configured 2026 Great Discoveries destination.
        year: Original invocation year.
        albums_path: Canonical album mirror.
        artists_path: Canonical artist mirror.
        removed_path: Removed-album recovery log.
        log_path: Original routine audit.
        echo: Existing CLI or job output sink.
        dry_run: Whether writes are suppressed.
        clock: Original UTC clock for progress records.

    Returns:
        Executor over original effects and per-invocation membership projections.
    """
    presentation = NewKidsPresenter(echo)
    access = LegacyDiscoveryEffects(
        client, retry, state_access, artists_path, year, great_seed, echo
    )
    library = library_reconciliation(
        client, retry, albums_path, removed_path, log_path, echo, dry_run
    )
    completion = DiscoveryCompletion(
        access, presentation, state, year, newfoundland, unlucky, dry_run
    )
    return NewKidsExecution(
        access,
        state_access,
        library,
        completion,
        presentation,
        state,
        live_ids,
        playlist_id,
        label,
        dry_run,
        clock,
    )
