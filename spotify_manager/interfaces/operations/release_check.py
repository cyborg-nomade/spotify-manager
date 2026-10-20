"""Invoke release check use cases for CLI and HTTP features."""

from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify

from spotify_manager.application.release_check_values import (
    ReleaseCheckConfigError as ReleaseCheckConfigError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckError as ReleaseCheckError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckStateError as ReleaseCheckStateError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckSummary as ReleaseCheckSummary,
)
from spotify_manager.bootstrap.artist_mapping import artist_mapping
from spotify_manager.bootstrap.release_opening import release_opening
from spotify_manager.bootstrap.release_run import release_review
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import (
    ReleaseCandidate as ReleaseCandidate,
)
from spotify_manager.domain.release_check_values import (
    ReleaseCheckResult as ReleaseCheckResult,
)
from spotify_manager.domain.release_check_values import ReleaseTrack as ReleaseTrack
from spotify_manager.interfaces.requests.release_check import ReleaseCheckCallbacks
from spotify_manager.interfaces.requests.release_check import ReleaseCheckOptions
from spotify_manager.interfaces.requests.release_check import ReleaseCheckResources
from spotify_manager.routines import release_check as legacy
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines.release_check import CHOICE_ADD as CHOICE_ADD
from spotify_manager.routines.release_check import CHOICE_PENDING as CHOICE_PENDING
from spotify_manager.routines.release_check import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.release_check import (
    CHOICE_SEARCH_PREFIX as CHOICE_SEARCH_PREFIX,
)
from spotify_manager.routines.release_check import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.release_check import (
    CHOICE_SKIP_ARTIST as CHOICE_SKIP_ARTIST,
)
from spotify_manager.routines.release_check import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.release_check import (
    DEFAULT_STATE_BACKUP_DIR as DEFAULT_STATE_BACKUP_DIR,
)
from spotify_manager.routines.release_check import (
    DEFAULT_STATE_PATH as DEFAULT_STATE_PATH,
)
from spotify_manager.routines.release_check import (
    ArtistChoiceReader as ArtistChoiceReader,
)
from spotify_manager.routines.release_check import LastFmReader as LastFmReader
from spotify_manager.routines.release_check import ProgressCallback as ProgressCallback
from spotify_manager.routines.release_check import (
    ReleaseCheckPlaylists as ReleaseCheckPlaylists,
)
from spotify_manager.routines.release_check import (
    ReleaseChoiceReader as ReleaseChoiceReader,
)
from spotify_manager.routines.release_check import RetryCall as RetryCall
from spotify_manager.routines.release_check import _default_state as _default_state
from spotify_manager.routines.release_check import _direct_retry as _direct_retry
from spotify_manager.routines.release_check import release_tags as release_tags
from spotify_manager.routines.release_check import save_state as save_state
from spotify_manager.routines.release_check import (
    state_fingerprint as state_fingerprint,
)
from spotify_manager.routines.release_check import state_updated_at as state_updated_at
from spotify_manager.routines.release_check import validate_state as validate_state


def run_release_check(
    sp: Spotify,
    lastfm: LastFmReader,
    options: ReleaseCheckOptions,
    callbacks: ReleaseCheckCallbacks,
    resources: ReleaseCheckResources | None = None,
) -> ReleaseCheckSummary:
    """Refresh history, resume release review, and present the completed outcome.

    Args:
        sp: Caller-owned client.
        lastfm: Caller-owned client.
        options: Destinations and execution mode.
        callbacks: Operator decisions, notifications and retry ownership.
        resources: Persistent files and checkpoint authority.

    Returns:
        The original typed summary and accepted effects.

    Raises:
        RuntimeError: Observations, selections or persistence cannot complete.
    """
    resources = resources or ReleaseCheckResources()
    workflow, effects = release_opening(
        lastfm,
        options.expected_username,
        resources.state_path,
        resources.state_service,
        resources.log_path,
        resources.export_path,
        resources.legacy_delta_path,
        resources.backup_dir,
        resources.history_log_path,
        options.now,
        callbacks.progress_callback,
    )
    opening = workflow.run(options.dry_run)
    configured = release_review(
        opening,
        effects.state_access,
        sp,
        options.playlists,
        resources.log_path,
        callbacks.artist_choice_reader,
        callbacks.release_choice_reader,
        callbacks.progress_callback,
        callbacks.retry_call,
        options.dry_run,
    )
    return configured.run()


def resolve_artist(
    sp: Spotify,
    artist: RankedArtist,
    reader: legacy.ArtistChoiceReader | None,
    retry: legacy.RetryCall,
) -> SpotifyArtistCandidate | str | None:
    """Retain original catalog retries, mapping controls and custom-query semantics.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original ranked Last.fm evidence.
        reader: Original interaction callback, when present.
        retry: Original retry policy.

    Returns:
        Original mapping, control response or absent noninteractive result.

    Raises:
        ReleaseCheckSpotifyError: Original mapping or interaction is invalid.
    """
    return artist_mapping(sp, reader, retry).run(artist)
