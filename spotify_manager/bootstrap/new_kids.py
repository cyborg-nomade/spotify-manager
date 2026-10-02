"""Compose ordinary discovery review decisions with caller-owned integrations."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.composer_routes import ReleaseChoiceReader
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
from spotify_manager.application.new_kids_values import FlushSummary
from spotify_manager.application.new_kids_values import Queue2Summary
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.queue_2 import prepare_queue_review
from spotify_manager.application.queue_2 import queue_review_result
from spotify_manager.core.state import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
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
from spotify_manager.interfaces.presenters.new_kids import NewKidsPresenter
from spotify_manager.routines import new_kids as legacy
from spotify_manager.routines import scrobble_history


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
    retry: RetryCall,
    state_access: RoutineState,
    state: dict[str, object],
    playlist_id: str,
    queue_id: str,
    active_key: str,
    blocking_key: str,
    fill_from_queue: bool,
    dry_run: bool,
    capacity: int,
    log_path: Path,
    echo: Callable[[str], None],
    clock: Callable[[], datetime],
) -> DiscoveryRun:
    """Compose original run preparation and finalization over existing boundaries.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        state_access: Original namespace checkpoint boundary.
        state: Mutable complete namespace.
        playlist_id: Review playlist identifier.
        queue_id: Queue transfer source identifier.
        active_key: Original active-run namespace key.
        blocking_key: Other review's active-run key.
        fill_from_queue: Whether to prefill and refill this review playlist.
        dry_run: Whether to suppress remote and namespace writes.
        capacity: Original New Kids playlist marker cap.
        log_path: Existing routine audit destination.
        echo: Existing CLI or job message sink.
        clock: Original UTC clock for new runs.

    Returns:
        Run lifecycle service sharing original state and playlist integrations.
    """
    transfer = queue_transfer(
        client, retry, playlist_id, queue_id, capacity, dry_run, log_path, echo
    )
    return DiscoveryRun(
        state_access,
        transfer,
        state,
        playlist_id,
        active_key,
        blocking_key,
        fill_from_queue,
        dry_run,
        clock,
    )


def run_review(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool,
    year: int | None,
    echo: Callable[[str], None],
    progress_callback: ProgressCallback | None,
    retry_call: RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    albums_path: Path,
    artists_path: Path,
    removed_albums_log_path: Path,
    scrobbles_path: Path,
    lastfm: scrobble_history.LastFmReader | None,
    lastfm_username: str | None,
    _playlist_label: str,
    _active_run_key: str,
    _blocking_active_run_key: str,
    _fill_from_queue: bool,
    _initial_tracks: list[PlaylistTrack] | None,
    _live_tracks: list[PlaylistTrack] | None,
) -> FlushSummary:
    """Advance one playlist snapshot using the shared four-release rules.

    Args:
        sp: Caller-owned synchronous Spotify client.
        new_kids_playlist_id: Configured New Kids review destination.
        queue_2_playlist_id: Configured Queue 2 source or review playlist.
        great_discoveries_2026_playlist_id: Existing 2026 promotion playlist seed.
        unlucky_ones_playlist_id: Destination for liked but nonqualifying artists.
        newfoundland_playlist_id: Additional destination for qualifying artists.
        choice_reader: Composer/release choice callback, including skip and quit.
        dry_run: Project changes without playlist/library writes or state checkpoints.
        year: Review year; false or absent values retain the local current-year default.
        echo: Existing CLI or background-job output sink.
        progress_callback: Optional original progress callback.
        retry_call: Retry/cancellation callback, or direct execution when absent.
        state_path: Explicit legacy state path or the default shared namespace selector.
        state_service: Optional caller-supplied shared state service.
        log_path: Existing routine audit destination, including preview events.
        albums_path: Canonical album mirror used at completed-release boundaries.
        artists_path: Canonical artist mirror used after accepted unfollowing.
        removed_albums_log_path: Original removed-album recovery log.
        scrobbles_path: Existing Last.fm history export.
        lastfm: Optional history reader; requested refresh also runs during previews.
        lastfm_username: Required expected username when a history reader is supplied.
        _playlist_label: Original progress and retry display label.
        _active_run_key: Namespace key for this review's active snapshot.
        _blocking_active_run_key: Other review's active-run key checked before startup.
        _fill_from_queue: Whether this invocation performs initial and final transfers.
        _initial_tracks: Optional daily selection supplied for a fresh snapshot.
        _live_tracks: Optional complete live sequence supplied for resume/execution.

    Returns:
        Original public summary with accepted results, counts and pause/resume flags.

    Raises:
        NewKidsConfigError: A requested history refresh lacks its expected username.
        NewKidsStateError: Saved progress is invalid or another run blocks execution.
        NewKidsError: Catalog observations or operator selections are invalid.
    """
    retry = retry_call or legacy._direct_call
    active_year = year or legacy.datetime.now().year
    legacy._refresh_history(
        lastfm, lastfm_username, "New Kids", scrobbles_path, echo, progress_callback
    )
    if progress_callback:
        progress_callback(0, 0, f"Loading {active_year} Last.fm release history")
    annual_scrobbles = legacy.load_annual_scrobble_index(
        scrobbles_path, year=active_year
    )
    state_access = legacy._state_access(state_path, state_service)
    persisted_state = state_access.load()
    state = json.loads(json.dumps(persisted_state)) if dry_run else persisted_state
    try:
        owned_playlists = legacy.composer_playlists.load_owned_playlists(
            sp, retry, frozenset({new_kids_playlist_id, queue_2_playlist_id})
        )
    except legacy.composer_playlists.ComposerPlaylistError as exc:
        raise legacy.NewKidsError(str(exc)) from exc
    lifecycle = review_run(
        sp,
        retry,
        state_access,
        state,
        new_kids_playlist_id,
        queue_2_playlist_id,
        _active_run_key,
        _blocking_active_run_key,
        _fill_from_queue,
        dry_run,
        legacy.PLAYLIST_CAP,
        log_path,
        echo,
        legacy._utc_now,
    )
    snapshot = lifecycle.prepare(_initial_tracks, _live_tracks)
    catalog_cache: dict[str, tuple[RankedRelease, ...]] = {}
    track_cache: dict[str, tuple[CatalogTrack, ...]] = {}
    composer_track_cache: dict[str, tuple[PlaylistTrack, ...]] = {}
    liked_cache: dict[str, bool] = {}
    planner = review_planner(
        sp,
        retry,
        choice_reader,
        year=active_year,
        dry_run=dry_run,
        history=annual_scrobbles,
        release_limit=legacy.RELEASES_PER_ARTIST,
        studio_minimum=legacy.MIN_SCROBBLED_TRACKS_PER_RELEASE,
        log_path=log_path,
        echo=echo,
        catalogs=catalog_cache,
        tracks=track_cache,
        liked=liked_cache,
        works=composer_track_cache,
    )
    execution = review_execution(
        sp,
        retry,
        state_access=state_access,
        state=state,
        live_ids=snapshot.live_ids,
        playlist_id=new_kids_playlist_id,
        label=_playlist_label,
        newfoundland=newfoundland_playlist_id,
        unlucky=unlucky_ones_playlist_id,
        great_seed=great_discoveries_2026_playlist_id,
        year=active_year,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_path=removed_albums_log_path,
        log_path=log_path,
        echo=echo,
        dry_run=dry_run,
        clock=legacy._utc_now,
    )
    reviewer = entry_review(
        planner,
        execution,
        owned_playlists,
        frozenset({new_kids_playlist_id, queue_2_playlist_id}),
        legacy._utc_now,
        legacy.COMPOSER_TRACKS_PER_ARTIST,
        progress_callback,
        echo,
    )
    reviewed, paused = reviewer.review(snapshot.entries, snapshot.run.get("run_id"))
    return lifecycle.finish(snapshot, reviewed, paused)


def run_queue_review(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool,
    year: int | None,
    echo: Callable[[str], None],
    progress_callback: ProgressCallback | None,
    retry_call: RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    albums_path: Path,
    artists_path: Path,
    removed_albums_log_path: Path,
    scrobbles_path: Path,
    lastfm: scrobble_history.LastFmReader | None,
    lastfm_username: str | None,
) -> Queue2Summary:
    """Fill New Kids, then advance the first ten remaining Queue 2 artists.

    Args:
        sp: Caller-owned synchronous Spotify client.
        new_kids_playlist_id: Configured New Kids review destination.
        queue_2_playlist_id: Configured Queue 2 source or review playlist.
        great_discoveries_2026_playlist_id: Existing 2026 promotion playlist seed.
        unlucky_ones_playlist_id: Destination for liked but nonqualifying artists.
        newfoundland_playlist_id: Additional destination for qualifying artists.
        choice_reader: Composer/release choice callback, including skip and quit.
        dry_run: Project changes without playlist/library writes or state checkpoints.
        year: Review year; false or absent values retain the local current-year default.
        echo: Existing CLI or background-job output sink.
        progress_callback: Optional original progress callback.
        retry_call: Retry/cancellation callback, or direct execution when absent.
        state_path: Explicit legacy state path or the default shared namespace selector.
        state_service: Optional caller-supplied shared state service.
        log_path: Existing routine audit destination, including preview events.
        albums_path: Canonical album mirror used at completed-release boundaries.
        artists_path: Canonical artist mirror used after accepted unfollowing.
        removed_albums_log_path: Original removed-album recovery log.
        scrobbles_path: Existing Last.fm history export.
        lastfm: Optional history reader; requested refresh also runs during previews.
        lastfm_username: Required expected username when a history reader is supplied.

    Returns:
        Original public summary with accepted results, counts and pause/resume flags.

    Raises:
        NewKidsConfigError: A requested history refresh lacks its expected username.
        NewKidsStateError: Saved progress is invalid or another run blocks execution.
        NewKidsError: Catalog observations or operator selections are invalid.
    """
    legacy._refresh_history(
        lastfm, lastfm_username, "Queue 2", scrobbles_path, echo, progress_callback
    )
    retry = retry_call or legacy._direct_call
    state_access = legacy._state_access(state_path, state_service)
    persisted_state = state_access.load()
    state = json.loads(json.dumps(persisted_state)) if dry_run else persisted_state
    transfer = queue_transfer(
        sp,
        retry,
        new_kids_playlist_id,
        queue_2_playlist_id,
        legacy.PLAYLIST_CAP,
        dry_run,
        log_path,
        echo,
    )
    snapshot = prepare_queue_review(transfer, state, legacy.QUEUE_2_DAILY_LIMIT)
    review = legacy._flush_review_playlist(
        sp,
        queue_2_playlist_id,
        queue_2_playlist_id,
        great_discoveries_2026_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
        choice_reader,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_albums_log_path=removed_albums_log_path,
        scrobbles_path=scrobbles_path,
        _playlist_label="Queue 2",
        _active_run_key="queue_2_active_run",
        _blocking_active_run_key="active_run",
        _fill_from_queue=False,
        _initial_tracks=snapshot.selected,
        _live_tracks=snapshot.remaining,
    )
    return queue_review_result(snapshot, review, dry_run)
