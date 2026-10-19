"""Invoke Queue 3 application stages with invocation-owned resources."""

import json as json
from datetime import UTC as UTC
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.ports.listening import RetryCall as RetryCall
from spotify_manager.application.queue_3_execution import (
    Queue3LiveQueue as Queue3LiveQueue,
)
from spotify_manager.application.queue_3_import_review import AnnualImportReview
from spotify_manager.application.queue_3_review import (
    Queue3Observations as Queue3Observations,
)
from spotify_manager.application.queue_3_review import Queue3Review as Queue3Review
from spotify_manager.application.queue_3_run import Queue3Run as Queue3Run
from spotify_manager.application.queue_3_run import run_summary as run_summary
from spotify_manager.application.queue_3_values import (
    AnnualImportResult as AnnualImportResult,
)
from spotify_manager.application.queue_3_values import (
    AnnualImportSummary as AnnualImportSummary,
)
from spotify_manager.application.queue_3_values import FlushResult as FlushResult
from spotify_manager.application.queue_3_values import FlushSummary as FlushSummary
from spotify_manager.application.queue_3_values import (
    Queue3CancelledError as Queue3CancelledError,
)
from spotify_manager.application.queue_3_values import (
    Queue3ConfigError as Queue3ConfigError,
)
from spotify_manager.application.queue_3_values import Queue3Error as Queue3Error
from spotify_manager.bootstrap.queue_3 import _datetime
from spotify_manager.bootstrap.queue_3 import _direct_call
from spotify_manager.bootstrap.queue_3 import annual_import
from spotify_manager.bootstrap.queue_3 import annual_inputs
from spotify_manager.bootstrap.queue_3 import review_execution
from spotify_manager.bootstrap.queue_3 import review_planner
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.infrastructure.legacy.queue_3 import (
    LegacyAnnualImport as LegacyAnnualImport,
)
from spotify_manager.infrastructure.legacy.queue_3 import (
    LegacyQueue3Catalog as LegacyQueue3Catalog,
)
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.interfaces.presenters.queue_3 import (
    Queue3Presenter as Queue3Presenter,
)
from spotify_manager.interfaces.requests.queue_3 import Queue3Callbacks
from spotify_manager.interfaces.requests.queue_3 import Queue3Options
from spotify_manager.interfaces.requests.queue_3 import Queue3Resources
from spotify_manager.routines import queue_3 as legacy
from spotify_manager.routines.queue_3 import CHOICE_ADVANCE as CHOICE_ADVANCE
from spotify_manager.routines.queue_3 import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.queue_3 import DEFAULT_ALBUMS_PATH as DEFAULT_ALBUMS_PATH
from spotify_manager.routines.queue_3 import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.queue_3 import DEFAULT_STATE_PATH as DEFAULT_STATE_PATH
from spotify_manager.routines.queue_3 import (
    ComposerPlaylistReader as ComposerPlaylistReader,
)
from spotify_manager.routines.queue_3 import Echo as Echo
from spotify_manager.routines.queue_3 import OwnedPlaylist as OwnedPlaylist
from spotify_manager.routines.queue_3 import ProgressCallback as ProgressCallback
from spotify_manager.routines.queue_3 import (
    ReleaseTransitionReader as ReleaseTransitionReader,
)
from spotify_manager.routines.queue_3 import _default_state as _default_state
from spotify_manager.routines.queue_3 import parse_playlist_id as parse_playlist_id
from spotify_manager.routines.queue_3 import validate_state as validate_state


def flush_queue_3(
    sp: Spotify,
    options: Queue3Options,
    callbacks: Queue3Callbacks,
    resources: Queue3Resources | None = None,
) -> FlushSummary:
    """Import the previous year once, then advance the first ten Queue 3 artists.

    Args:
        sp: Caller-owned client.
        options: Destinations and execution mode.
        callbacks: Operator decisions, notifications and retry ownership.
        resources: Persistent files and checkpoint authority.

    Returns:
        The original typed summary and accepted effects.

    Raises:
        RuntimeError: Observations, selections or persistence cannot complete.
    """
    resources = resources or Queue3Resources()
    retry = callbacks.retry_call or _direct_call
    year = options.active_year or legacy.datetime.now(UTC).year
    inputs = annual_inputs(
        sp,
        options.playlist_id,
        retry,
        options.dry_run,
        resources.state_path,
        resources.state_service,
        resources.log_path,
        callbacks.echo,
    )
    current, annual = inputs.importer.run(
        options.playlist_id,
        inputs.current,
        inputs.state,
        inputs.owned,
        year,
        options.dry_run,
    )
    queue = Queue3LiveQueue(
        options.playlist_id, current, {track.spotify_id for track in current}
    )
    session = Queue3Run(
        inputs.state,
        inputs.state_access,
        _datetime,
        options.dry_run,
        legacy.DAILY_ARTIST_LIMIT,
    )
    snapshot = session.start(queue)
    liked: dict[str, bool] = {}
    planner = review_planner(
        sp, retry, {}, liked, snapshot.orders, session, callbacks.transition_reader
    )
    execution = review_execution(
        sp,
        retry,
        resources.albums_path,
        resources.removed_albums_log_path,
        resources.log_path,
        callbacks.echo,
        options.dry_run,
    )
    catalog = LegacyQueue3Catalog(sp, retry, liked)
    observations = Queue3Observations(catalog, inputs.access)
    review = Queue3Review(
        session,
        snapshot,
        queue,
        planner,
        execution,
        observations,
        inputs.owned,
        callbacks.composer_playlist_reader,
        inputs.access,
        Queue3Presenter(callbacks.echo, callbacks.progress_callback),
    )
    results, paused = review.run()
    session.finish(snapshot, paused)
    return run_summary(snapshot, results, annual, paused, options.dry_run)


def import_previous_year_discoveries(
    sp: Spotify,
    playlist_id: str,
    *,
    active_year: int | None = None,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> AnnualImportSummary:
    """Import last year's Great Discoveries without advancing Queue 3.

    Args:
        sp: Caller-owned Spotify sp.
        playlist_id: Configured Queue 3 destination.
        active_year: Explicit checkpoint year, or the current UTC year.
        dry_run: Whether to clone state and suppress writes.
        echo: Existing output sink.
        progress_callback: Optional progress sink.
        retry_call: Optional retry and cancellation callback.
        state_path: Existing legacy namespace path.
        state_service: Optional shared state service.
        log_path: Original audit destination.

    Returns:
        Original annual import summary with source-ordered artist decisions.

    Raises:
        Queue3Error: Configuration, playlist observation or state handling fails.
    """
    from spotify_manager.routines.queue_3 import _state_access
    from spotify_manager.routines.queue_3 import load_owned_playlists

    retry = retry_call or _direct_call
    year = active_year or legacy.datetime.now(UTC).year
    presentation = Queue3Presenter(echo, progress_callback)
    presentation.loading(year - 1)
    owned = load_owned_playlists(sp, retry, playlist_id)
    access = LegacyAnnualImport(sp, retry, log_path)
    current = list(access.read(playlist_id))
    state_access = _state_access(state_path, state_service)
    persisted = state_access.load()
    state = json.loads(json.dumps(persisted)) if dry_run else persisted
    importer = annual_import(sp, retry, log_path, state_access, echo)
    return AnnualImportReview(importer, presentation).run(
        playlist_id, current, state, owned, year, dry_run
    )
