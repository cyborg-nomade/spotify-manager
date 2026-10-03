"""Invoke new kids use cases for CLI and HTTP features."""

import json as json
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
from spotify_manager.bootstrap.new_kids import entry_review
from spotify_manager.bootstrap.new_kids import queue_transfer
from spotify_manager.bootstrap.new_kids import review_execution
from spotify_manager.bootstrap.new_kids import review_inputs
from spotify_manager.bootstrap.new_kids import review_planner
from spotify_manager.bootstrap.new_kids import review_run
from spotify_manager.core.state import StateService as StateService
from spotify_manager.domain.catalog import PlaylistTrack as PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack as CatalogTrack
from spotify_manager.domain.discovery import RankedRelease as RankedRelease
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.routines import new_kids as legacy
from spotify_manager.routines import new_wine as new_wine
from spotify_manager.routines import scrobble_history as scrobble_history
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
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    lastfm: scrobble_history.LastFmReader | None = None,
    lastfm_username: str | None = None,
    _playlist_label: str = "New Kids",
    _active_run_key: str = "active_run",
    _blocking_active_run_key: str = "queue_2_active_run",
    _fill_from_queue: bool = True,
    _initial_tracks: list[new_wine.PlaylistTrack] | None = None,
    _live_tracks: list[new_wine.PlaylistTrack] | None = None,
) -> FlushSummary:
    """Advance one playlist snapshot using the shared four-release rules."""
    from spotify_manager.routines.new_kids import _utc_now

    inputs = review_inputs(
        sp,
        new_kids_playlist_id,
        queue_2_playlist_id,
        retry_call,
        year,
        lastfm,
        lastfm_username,
        scrobbles_path,
        echo,
        progress_callback,
        state_path,
        state_service,
        dry_run,
    )
    lifecycle = review_run(
        sp,
        inputs.retry,
        inputs.state_access,
        inputs.state,
        new_kids_playlist_id,
        queue_2_playlist_id,
        _active_run_key,
        _blocking_active_run_key,
        _fill_from_queue,
        dry_run,
        legacy.PLAYLIST_CAP,
        log_path,
        echo,
        _utc_now,
    )
    snapshot = lifecycle.prepare(_initial_tracks, _live_tracks)
    catalog_cache: dict[str, tuple[RankedRelease, ...]] = {}
    track_cache: dict[str, tuple[CatalogTrack, ...]] = {}
    composer_track_cache: dict[str, tuple[PlaylistTrack, ...]] = {}
    liked_cache: dict[str, bool] = {}
    planner = review_planner(
        sp,
        inputs.retry,
        choice_reader,
        year=inputs.active_year,
        dry_run=dry_run,
        history=inputs.annual_scrobbles,
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
        inputs.retry,
        state_access=inputs.state_access,
        state=inputs.state,
        live_ids=snapshot.live_ids,
        playlist_id=new_kids_playlist_id,
        label=_playlist_label,
        newfoundland=newfoundland_playlist_id,
        unlucky=unlucky_ones_playlist_id,
        great_seed=great_discoveries_2026_playlist_id,
        year=inputs.active_year,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_path=removed_albums_log_path,
        log_path=log_path,
        echo=echo,
        dry_run=dry_run,
        clock=_utc_now,
    )
    reviewer = entry_review(
        planner,
        execution,
        inputs.owned_playlists,
        frozenset({new_kids_playlist_id, queue_2_playlist_id}),
        _utc_now,
        legacy.COMPOSER_TRACKS_PER_ARTIST,
        progress_callback,
        echo,
    )
    reviewed, paused = reviewer.review(snapshot.entries, snapshot.run.get("run_id"))
    return lifecycle.finish(snapshot, reviewed, paused)


def flush_new_kids(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    lastfm: scrobble_history.LastFmReader | None = None,
    lastfm_username: str | None = None,
) -> FlushSummary:
    """Advance every snapshotted artist once, then refill New Kids to ten.

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
    return _flush_review_playlist(
        sp,
        new_kids_playlist_id,
        queue_2_playlist_id,
        great_discoveries_2026_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
        choice_reader,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_albums_log_path=removed_albums_log_path,
        scrobbles_path=scrobbles_path,
        lastfm=lastfm,
        lastfm_username=lastfm_username,
    )


def flush_queue_2(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_QUEUE_2_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    lastfm: scrobble_history.LastFmReader | None = None,
    lastfm_username: str | None = None,
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
    from spotify_manager.infrastructure.discovery_history import (
        refresh_release_history as _refresh_history,
    )
    from spotify_manager.routines.new_kids import _direct_call
    from spotify_manager.routines.new_kids import _state_access

    _refresh_history(
        lastfm, lastfm_username, "Queue 2", scrobbles_path, echo, progress_callback
    )
    retry = retry_call or _direct_call
    state_access = _state_access(state_path, state_service)
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
    review = _flush_review_playlist(
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
