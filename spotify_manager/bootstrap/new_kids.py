"""Compose ordinary discovery review decisions with caller-owned integrations."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.discovery_completion import DiscoveryCompletion
from spotify_manager.application.discovery_destinations import GreatDiscoveries
from spotify_manager.application.discovery_library import DiscoveryLibraryReconciliation
from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.discovery_review import DiscoveryReview
from spotify_manager.application.discovery_review import ProgressCallback
from spotify_manager.application.discovery_run import DiscoveryRun
from spotify_manager.application.new_kids_execution import NewKidsExecution
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryAudit
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryCatalog
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryLibrary
from spotify_manager.infrastructure.legacy.discovery_execution import (
    LegacyDiscoveryCreation,
)
from spotify_manager.infrastructure.legacy.discovery_execution import (
    LegacyDiscoveryEffects,
)
from spotify_manager.infrastructure.legacy.discovery_execution import (
    LegacyDiscoveryQueue,
)
from spotify_manager.interfaces.operations.discovery_inputs import ReviewInputs
from spotify_manager.interfaces.presenters.new_kids import NewKidsPresenter
from spotify_manager.interfaces.requests.discovery import DiscoveryCallbacks
from spotify_manager.interfaces.requests.discovery import DiscoveryOptions
from spotify_manager.interfaces.requests.discovery import DiscoveryResources
from spotify_manager.interfaces.requests.discovery import DiscoveryReviewMode
from spotify_manager.routines import new_kids as legacy


@dataclass
class ReviewCaches:
    """Keep accepted observations scoped to one discovery review.

    Args:
        catalogs: Ordered ranked releases by artist.
        tracks: Ordered catalog tracks by release.
        liked: Accepted live membership by track.
        works: Accepted works-playlist tracks.
    """

    catalogs: dict[str, tuple[RankedRelease, ...]] = field(default_factory=dict)
    tracks: dict[str, tuple[CatalogTrack, ...]] = field(default_factory=dict)
    liked: dict[str, bool] = field(default_factory=dict)
    works: dict[str, tuple[PlaylistTrack, ...]] = field(default_factory=dict)


def review_planner(
    client: Spotify,
    inputs: ReviewInputs,
    options: DiscoveryOptions,
    callbacks: DiscoveryCallbacks,
    resources: DiscoveryResources,
    caches: ReviewCaches,
) -> NewKidsPlanner:
    """Bind the original shared caches and effect boundaries to the release planner.

    Args:
        client: Caller-owned synchronous Spotify client.
        inputs: History, state and retry observations accepted for this run.
        options: Configured destinations and execution mode.
        callbacks: Operator decisions and notifications.
        resources: History, namespace, mirrors and audit files.
        caches: Invocation-owned accepted catalog and membership caches.

    Returns:
        The typed dependencies for this discovery stage.
    """
    access = LegacyDiscoveryCatalog(client, inputs.retry)
    observations = DiscoveryObservations(
        access,
        inputs.annual_scrobbles,
        legacy.RELEASES_PER_ARTIST,
        legacy.MIN_SCROBBLED_TRACKS_PER_RELEASE,
        caches.catalogs,
        caches.tracks,
        caches.liked,
        caches.works,
    )
    return NewKidsPlanner(
        observations,
        callbacks.choose,
        LegacyDiscoveryAudit(resources.log_path),
        NewKidsPresenter(callbacks.echo),
        inputs.active_year,
        options.dry_run,
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
    inputs: ReviewInputs,
    options: DiscoveryOptions,
    resources: DiscoveryResources,
    live_ids: set[str],
    label: str,
    echo: Callable[[str], None],
    clock: Callable[[], datetime],
) -> NewKidsExecution:
    """Compose review effects with the original invocation-owned state and paths.

    Args:
        client: Caller-owned synchronous Spotify client.
        inputs: History, state and retry observations accepted for this run.
        options: Configured destinations and execution mode.
        resources: History, namespace, mirrors and audit files.
        live_ids: Shared projected review membership.
        label: Original review label.
        echo: Original output sink.
        clock: Original UTC timestamp source.

    Returns:
        The typed dependencies for this discovery stage.
    """
    presentation = NewKidsPresenter(echo)
    access = LegacyDiscoveryEffects(
        client,
        inputs.retry,
        inputs.state_access,
        resources.artists_path,
        inputs.active_year,
        options.great_discoveries_2026_playlist_id,
        echo,
    )
    library = library_reconciliation(
        client,
        inputs.retry,
        resources.albums_path,
        resources.removed_albums_log_path,
        resources.log_path,
        echo,
        options.dry_run,
    )
    completion = DiscoveryCompletion(
        access,
        presentation,
        inputs.state,
        inputs.active_year,
        options.newfoundland_playlist_id,
        options.unlucky_ones_playlist_id,
        options.dry_run,
    )
    return NewKidsExecution(
        access,
        inputs.state_access,
        library,
        completion,
        presentation,
        inputs.state,
        live_ids,
        options.new_kids_playlist_id,
        label,
        options.dry_run,
        clock,
    )


def great_discoveries(
    client: Spotify,
    retry: RetryCall,
    state_access: RoutineState,
    echo: Callable[[str], None],
) -> GreatDiscoveries:
    """Compose yearly playlist creation with original observations and state writes.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        state_access: Original namespace checkpoint boundary.
        echo: Existing CLI or job output sink.

    Returns:
        Yearly destination resolver over the original external boundaries.
    """
    return GreatDiscoveries(
        LegacyDiscoveryCreation(client, retry), state_access, NewKidsPresenter(echo)
    )


def queue_transfer(
    client: Spotify,
    retry: RetryCall,
    destination: str,
    source: str,
    capacity: int,
    dry_run: bool,
    log_path: Path,
    echo: Callable[[str], None],
) -> DiscoveryQueueTransfer:
    """Compose queue transfers over the original observation and audit boundaries.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        destination: New Kids destination identifier.
        source: Queue 2 source identifier.
        capacity: Original destination marker-count cap.
        dry_run: Whether to project transfers without remote writes.
        log_path: Existing routine event log.
        echo: Existing CLI or job output sink.

    Returns:
        Queue transfer service preserving original marker and logical-artist rules.
    """
    return DiscoveryQueueTransfer(
        LegacyDiscoveryQueue(client, retry),
        LegacyDiscoveryAudit(log_path),
        NewKidsPresenter(echo),
        destination,
        source,
        capacity,
        dry_run,
    )


def entry_review(
    planner: NewKidsPlanner,
    execution: NewKidsExecution,
    owned: tuple[OwnedPlaylist, ...],
    excluded: frozenset[str],
    clock: Callable[[], datetime],
    composer_limit: int,
    progress_callback: ProgressCallback | None,
    echo: Callable[[str], None],
) -> DiscoveryReview:
    """Compose entry review over the already accepted run-owned services.

    Args:
        planner: Ordinary release decisions and shared observations.
        execution: Accepted plan effects and namespace.
        owned: Observed owned playlists.
        excluded: Review playlist identifiers excluded from composer routing.
        clock: Original UTC clock for progress and composer route acceptance.
        composer_limit: Original maximum reviewed works.
        progress_callback: Existing progress sink, if configured.
        echo: Existing CLI or job message sink.

    Returns:
        Entry coordinator sharing the original invocation-owned dependencies.
    """
    return DiscoveryReview(
        planner,
        execution,
        execution.state_access,
        execution.library.audit,
        NewKidsPresenter(echo),
        owned,
        excluded,
        clock,
        composer_limit,
        progress_callback,
    )


def review_run(
    client: Spotify,
    inputs: ReviewInputs,
    options: DiscoveryOptions,
    resources: DiscoveryResources,
    mode: DiscoveryReviewMode,
    echo: Callable[[str], None],
    clock: Callable[[], datetime],
) -> DiscoveryRun:
    """Compose original run preparation and finalization over existing boundaries.

    Args:
        client: Caller-owned synchronous Spotify client.
        inputs: History, state and retry observations accepted for this run.
        options: Configured destinations and execution mode.
        resources: History, namespace, mirrors and audit files.
        mode: Review identity and checkpoint keys.
        echo: Original output sink.
        clock: Original UTC timestamp source.

    Returns:
        The typed dependencies for this discovery stage.
    """
    transfer = queue_transfer(
        client,
        inputs.retry,
        options.new_kids_playlist_id,
        options.queue_2_playlist_id,
        legacy.PLAYLIST_CAP,
        options.dry_run,
        resources.log_path,
        echo,
    )
    return DiscoveryRun(
        inputs.state_access,
        transfer,
        inputs.state,
        options.new_kids_playlist_id,
        mode.active_key,
        mode.blocking_key,
        mode.fill_from_queue,
        options.dry_run,
        clock,
    )
