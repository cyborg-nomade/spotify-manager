"""Invoke release check use cases for CLI and HTTP features."""

from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify as Spotify

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
from spotify_manager.bootstrap.release_opening import release_opening
from spotify_manager.bootstrap.release_run import release_review
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.artist_mapping import (
    SpotifyArtistCandidate as SpotifyArtistCandidate,
)
from spotify_manager.domain.release_check_values import RankedArtist as RankedArtist
from spotify_manager.domain.release_check_values import (
    ReleaseCandidate as ReleaseCandidate,
)
from spotify_manager.domain.release_check_values import (
    ReleaseCheckResult as ReleaseCheckResult,
)
from spotify_manager.domain.release_check_values import ReleaseTrack as ReleaseTrack
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
    playlists: ReleaseCheckPlaylists,
    *,
    expected_username: str | None,
    artist_choice_reader: ArtistChoiceReader | None = None,
    release_choice_reader: ReleaseChoiceReader | None = None,
    dry_run: bool = False,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    export_path: Path = scrobble_history.DEFAULT_SCROBBLES_PATH,
    legacy_delta_path: Path | None = scrobble_history.DEFAULT_LEGACY_DELTA_PATH,
    backup_dir: Path = scrobble_history.DEFAULT_BACKUP_DIR,
    history_log_path: Path = scrobble_history.DEFAULT_LOG_PATH,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
) -> ReleaseCheckSummary:
    """Refresh history, resume release review, and present the completed outcome.

    Args:
        sp: Caller-owned synchronous Spotify client.
        lastfm: Caller-owned canonical history reader.
        playlists: Existing Wine Cellar and New Vintage destinations.
        expected_username: Expected owner of the history export.
        artist_choice_reader: Optional artist-mapping interaction.
        release_choice_reader: Optional release-review interaction.
        dry_run: Preserve original preview semantics and checkpoints.
        state_path: Existing release-review namespace location.
        state_service: Optional shared namespace authority.
        log_path: Original release audit destination.
        export_path: Canonical history location.
        legacy_delta_path: Optional recent-history delta.
        backup_dir: Existing compressed-history backup directory.
        history_log_path: Original history audit destination.
        now: Optional effective UTC observation time.
        progress_callback: Invocation-owned progress presenter.
        retry_call: Caller-owned retry boundary for Spotify operations.

    Returns:
        The original release-check summary, including resume and pause results.

    Raises:
        ReleaseCheckError: History, state, catalog or accepted effects fail.
    """
    workflow, effects = release_opening(
        lastfm,
        expected_username,
        state_path,
        state_service,
        log_path,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        now,
        progress_callback,
    )
    opening = workflow.run(dry_run)
    configured = release_review(
        opening,
        effects.state_access,
        sp,
        playlists,
        log_path,
        artist_choice_reader,
        release_choice_reader,
        progress_callback,
        retry_call,
        dry_run,
    )
    return configured.run()
