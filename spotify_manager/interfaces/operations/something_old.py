"""Invoke something old use cases for CLI and HTTP features."""

from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.something_old_values import (
    SomethingOldConfigError as SomethingOldConfigError,
)
from spotify_manager.application.something_old_values import (
    SomethingOldError as SomethingOldError,
)
from spotify_manager.application.something_old_values import (
    SomethingOldSummary as SomethingOldSummary,
)
from spotify_manager.bootstrap.something_old_run import something_old
from spotify_manager.domain.golden_oldies import GoldenOldieArtist as GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack as SelectedTrack
from spotify_manager.domain.golden_selection import (
    SpotifyArtistCandidate as SpotifyArtistCandidate,
)
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldResources
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines.something_old import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.something_old import (
    AlbumChoiceReader as AlbumChoiceReader,
)
from spotify_manager.routines.something_old import (
    ArtistChoiceReader as ArtistChoiceReader,
)
from spotify_manager.routines.something_old import LastFmReader as LastFmReader
from spotify_manager.routines.something_old import ModeReader as ModeReader
from spotify_manager.routines.something_old import ProgressCallback as ProgressCallback
from spotify_manager.routines.something_old import RetryCall as RetryCall
from spotify_manager.routines.something_old import (
    parse_playlist_id as parse_playlist_id,
)


def run_something_old(
    sp: Spotify,
    lastfm: LastFmReader,
    options: SomethingOldOptions,
    callbacks: SomethingOldCallbacks,
    resources: SomethingOldResources | None = None,
) -> SomethingOldSummary:
    """Refresh history and fill an empty Something Old playlist cautiously.

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
    resources = resources or SomethingOldResources()
    configured = something_old(sp, lastfm, options, callbacks, resources)
    return configured.run(options.playlist_id, options.dry_run)
