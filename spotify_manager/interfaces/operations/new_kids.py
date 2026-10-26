"""Invoke new kids use cases for CLI and HTTP features."""

import json as json
from dataclasses import replace
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.composer_routes import (
    ReleaseChoiceReader as ReleaseChoiceReader,
)
from spotify_manager.application.discovery_review import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.application.new_kids_values import FillResult as FillResult
from spotify_manager.application.new_kids_values import FlushResult as FlushResult
from spotify_manager.application.new_kids_values import FlushSummary as FlushSummary
from spotify_manager.application.new_kids_values import (
    NewKidsConfigError as NewKidsConfigError,
)
from spotify_manager.application.new_kids_values import NewKidsError as NewKidsError
from spotify_manager.application.new_kids_values import Queue2Summary as Queue2Summary
from spotify_manager.application.ports.listening import RetryCall as RetryCall
from spotify_manager.application.queue_2 import (
    prepare_queue_review as prepare_queue_review,
)
from spotify_manager.application.queue_2 import (
    queue_review_result as queue_review_result,
)
from spotify_manager.bootstrap.new_kids import ReviewCaches
from spotify_manager.bootstrap.new_kids import entry_review
from spotify_manager.bootstrap.new_kids import queue_transfer
from spotify_manager.bootstrap.new_kids import review_execution
from spotify_manager.bootstrap.new_kids import review_planner
from spotify_manager.bootstrap.new_kids import review_run
from spotify_manager.core.state import StateService as StateService
from spotify_manager.domain.catalog import PlaylistTrack as PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack as CatalogTrack
from spotify_manager.domain.discovery import RankedRelease as RankedRelease
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.interfaces.operations.discovery_inputs import review_inputs
from spotify_manager.interfaces.requests.discovery import DiscoveryInteraction
from spotify_manager.interfaces.requests.discovery import DiscoveryOptions
from spotify_manager.interfaces.requests.discovery import DiscoveryResources
from spotify_manager.interfaces.requests.discovery import DiscoveryReviewMode
from spotify_manager.routines import new_kids as legacy
from spotify_manager.routines import new_wine as new_wine
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines.new_kids import _UTC_NOW_RESOURCE
from spotify_manager.routines.new_kids import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.new_kids import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.new_kids import DEFAULT_ALBUMS_PATH as DEFAULT_ALBUMS_PATH
from spotify_manager.routines.new_kids import (
    DEFAULT_ARTISTS_PATH as DEFAULT_ARTISTS_PATH,
)
from spotify_manager.routines.new_kids import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.new_kids import (
    DEFAULT_QUEUE_2_LOG_PATH as DEFAULT_QUEUE_2_LOG_PATH,
)
from spotify_manager.routines.new_kids import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.new_kids import DEFAULT_STATE_PATH as DEFAULT_STATE_PATH
from spotify_manager.routines.new_kids import ChoiceCandidate as ChoiceCandidate
from spotify_manager.routines.new_kids import Echo as Echo
from spotify_manager.routines.new_kids import _default_state as _default_state
from spotify_manager.routines.new_kids import parse_playlist_id as parse_playlist_id
from spotify_manager.routines.new_kids import validate_state as validate_state


def _flush_review_playlist(
    sp: Spotify,
    options: DiscoveryOptions,
    interaction: DiscoveryInteraction,
    resources: DiscoveryResources | None = None,
    mode: DiscoveryReviewMode | None = None,
) -> FlushSummary:
    """Advance one playlist snapshot using the shared four-release rules.

    Args:
        sp: Caller-owned synchronous Spotify client.
        options: Destinations and execution mode.
        interaction: Operator decisions and notifications.
        resources: History, checkpoints, mirrors and audit files.
        mode: Review label, checkpoint keys and accepted queue snapshot.

    Returns:
        The original review summary and ordered accepted effects.

    Raises:
        NewKidsError: Observations, decisions or checkpoints are invalid.
    """
    resources = resources or DiscoveryResources()
    mode = mode or DiscoveryReviewMode()

    inputs = review_inputs(sp, options, interaction, resources)
    lifecycle = review_run(
        sp, inputs, options, resources, mode, interaction, _UTC_NOW_RESOURCE
    )
    snapshot = lifecycle.prepare(mode.initial_tracks, mode.live_tracks)
    caches = ReviewCaches()
    planner = review_planner(sp, inputs, options, interaction, resources, caches)
    execution = review_execution(
        sp,
        inputs,
        options,
        resources,
        snapshot.live_ids,
        mode.label,
        interaction,
        _UTC_NOW_RESOURCE,
    )
    reviewer = entry_review(
        planner,
        execution,
        inputs.owned_playlists,
        frozenset({options.new_kids_playlist_id, options.queue_2_playlist_id}),
        _UTC_NOW_RESOURCE,
        legacy.COMPOSER_TRACKS_PER_ARTIST,
        interaction,
        interaction,
    )
    reviewed, paused = reviewer.review(snapshot.entries, snapshot.run.get("run_id"))
    return lifecycle.finish(snapshot, reviewed, paused)


def flush_new_kids(
    sp: Spotify,
    options: DiscoveryOptions,
    interaction: DiscoveryInteraction,
    resources: DiscoveryResources | None = None,
) -> FlushSummary:
    """Advance every snapshotted artist once, then refill New Kids to ten.

    Args:
        sp: Caller-owned synchronous Spotify client.
        options: Destinations and execution mode.
        interaction: Operator decisions and notifications.
        resources: History, checkpoints, mirrors and audit files.

    Returns:
        The original review summary and ordered accepted effects.

    Raises:
        NewKidsError: Observations, decisions or checkpoints are invalid.
    """
    resources = resources or DiscoveryResources()
    return _flush_review_playlist(sp, options, interaction, resources)


def flush_queue_2(
    sp: Spotify,
    options: DiscoveryOptions,
    interaction: DiscoveryInteraction,
    resources: DiscoveryResources | None = None,
) -> Queue2Summary:
    """Fill New Kids, then advance the first ten remaining Queue 2 artists.

    Args:
        sp: Caller-owned synchronous Spotify client.
        options: Destinations and execution mode.
        interaction: Operator decisions and notifications.
        resources: History, checkpoints, mirrors and audit files.

    Returns:
        The original review summary and ordered accepted effects.

    Raises:
        NewKidsError: Observations, decisions or checkpoints are invalid.
    """
    resources = resources or DiscoveryResources(log_path=DEFAULT_QUEUE_2_LOG_PATH)
    from spotify_manager.infrastructure.discovery_history import (
        refresh_release_history as _refresh_history,
    )
    from spotify_manager.routines.new_kids import _state_access

    _refresh_history(
        resources.lastfm,
        resources.lastfm_username,
        "Queue 2",
        resources.scrobbles_path,
        interaction,
        interaction,
    )
    retry = interaction
    state_access = _state_access(resources.state_path, resources.state_service)
    persisted_state = state_access.load()
    state = (
        json.loads(json.dumps(persisted_state)) if options.dry_run else persisted_state
    )
    transfer = queue_transfer(
        sp,
        retry,
        options.new_kids_playlist_id,
        options.queue_2_playlist_id,
        legacy.PLAYLIST_CAP,
        options.dry_run,
        resources.log_path,
        interaction,
    )
    snapshot = prepare_queue_review(transfer, state, legacy.QUEUE_2_DAILY_LIMIT)
    review = _flush_review_playlist(
        sp,
        replace(options, new_kids_playlist_id=options.queue_2_playlist_id),
        interaction,
        replace(resources, lastfm=None, lastfm_username=None),
        DiscoveryReviewMode(
            label="Queue 2",
            active_key="queue_2_active_run",
            blocking_key="active_run",
            fill_from_queue=False,
            initial_tracks=snapshot.selected,
            live_tracks=snapshot.remaining,
        ),
    )
    return queue_review_result(snapshot, review, options.dry_run)
