"""Invoke palace of memory use cases for CLI and HTTP features."""

from datetime import date as date
from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.palace_values import (
    AlphabeticalCursorUpdate as AlphabeticalCursorUpdate,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemoryConfigError as PalaceOfMemoryConfigError,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemoryError as PalaceOfMemoryError,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemorySummary as PalaceOfMemorySummary,
)
from spotify_manager.application.palace_values import (
    SavedAlbumRefresh as SavedAlbumRefresh,
)
from spotify_manager.bootstrap.palace_cursor import palace_cursor
from spotify_manager.bootstrap.palace_history import palace_history
from spotify_manager.bootstrap.palace_mirror import saved_mirror
from spotify_manager.bootstrap.palace_run import palace
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.palace_values import (
    HistoricalAlbumSelection as HistoricalAlbumSelection,
)
from spotify_manager.domain.palace_values import PalaceAlbumResult as PalaceAlbumResult
from spotify_manager.domain.palace_values import SpotifyAlbum as SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack as SpotifyFirstTrack
from spotify_manager.interfaces.requests.palace import PalaceCallbacks
from spotify_manager.interfaces.requests.palace import PalaceOptions
from spotify_manager.interfaces.requests.palace import PalaceResources
from spotify_manager.models.your_library import YourLibraryAlbum as YourLibraryAlbum
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines.blast_from_past import (
    fetch_random_indexes as fetch_random_indexes,
)
from spotify_manager.routines.palace_of_memory import (
    DEFAULT_ALBUM_BACKUPS_DIR as DEFAULT_ALBUM_BACKUPS_DIR,
)
from spotify_manager.routines.palace_of_memory import (
    DEFAULT_ALBUM_REFRESH_LOG_PATH as DEFAULT_ALBUM_REFRESH_LOG_PATH,
)
from spotify_manager.routines.palace_of_memory import (
    DEFAULT_ALBUMS_PATH as DEFAULT_ALBUMS_PATH,
)
from spotify_manager.routines.palace_of_memory import (
    DEFAULT_LOG_PATH as DEFAULT_LOG_PATH,
)
from spotify_manager.routines.palace_of_memory import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.palace_of_memory import (
    DEFAULT_STATE_PATH as DEFAULT_STATE_PATH,
)
from spotify_manager.routines.palace_of_memory import HISTORY_COUNT as HISTORY_COUNT
from spotify_manager.routines.palace_of_memory import Echo as Echo
from spotify_manager.routines.palace_of_memory import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.palace_of_memory import (
    RandomIndexReader as RandomIndexReader,
)
from spotify_manager.routines.palace_of_memory import RetryCall as RetryCall
from spotify_manager.routines.palace_of_memory import _default_state as _default_state
from spotify_manager.routines.palace_of_memory import (
    parse_playlist_id as parse_playlist_id,
)
from spotify_manager.routines.palace_of_memory import validate_state as validate_state


def refresh_saved_albums(
    spotify: Spotify,
    *,
    path: Path = DEFAULT_ALBUMS_PATH,
    backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
    """Refresh original canonical saved facts before alphabetical selection.

    Args:
        spotify: Caller-owned Spotify client.
        path: Original canonical mirror location.
        backups_dir: Original replaced-mirror backup directory.
        log_path: Original preflight audit location.
        retry_call: Original optional read retry policy.
        progress_callback: Original optional paging presenter.

    Returns:
        Original refreshed mirror and complete preflight outcome.

    Raises:
        PalaceOfMemoryError: Original live paging, replacement or audit fails.
    """
    configured = saved_mirror(
        spotify, path, backups_dir, log_path, retry_call, progress_callback
    )
    return configured.run()


def select_historical_albums(
    *,
    count: int = HISTORY_COUNT,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
) -> tuple[datetime, date, int, tuple[HistoricalAlbumSelection, ...]]:
    """Gather original eligible album ranks and Random.org date selections.

    Args:
        count: Original requested historical selection size.
        path: Original complete scrobble export location.
        today: Original optional effective local date.
        random_index_reader: Original caller-owned index reader.
        progress_callback: Original optional stage presenter.

    Returns:
        Original generated time, cutoff, eligible count and ordered album facts.

    Raises:
        PalaceOfMemoryError: Original history, population or random source fails.
        IndexError: An original custom index is out of range.
    """
    configured = palace_history(path, today, random_index_reader, progress_callback)
    return configured.run(count)


def set_alphabetical_cursor(
    spotify: Spotify,
    position: int,
    *,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    album_backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    album_refresh_log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AlphabeticalCursorUpdate:
    """Refresh live facts before persisting the original manual next position.

    Args:
        spotify: Caller-owned Spotify client.
        position: Original one-based requested next position.
        albums_path: Original canonical mirror location.
        state_path: Original cursor location.
        state_service: Original optional shared state authority.
        album_backups_dir: Original mirror backup directory.
        album_refresh_log_path: Original live preflight audit location.
        retry_call: Original optional retry policy.
        progress_callback: Original optional stage presenter.

    Returns:
        Original next position, full saved model and live preflight outcome.

    Raises:
        PalaceOfMemoryError: Original preflight, position or checkpoint fails.
    """
    configured = palace_cursor(
        spotify,
        albums_path,
        state_path,
        state_service,
        album_backups_dir,
        album_refresh_log_path,
        retry_call,
        progress_callback,
    )
    return configured.update(position)


def fill_palace_of_memory(
    spotify: Spotify,
    options: PalaceOptions,
    callbacks: PalaceCallbacks,
    resources: PalaceResources | None = None,
) -> PalaceOfMemorySummary:
    """Gather original alphabetical and historical markers and apply live authority.

    Args:
        spotify: Caller-owned client.
        options: Destinations and execution mode.
        callbacks: Operator decisions, notifications and retry ownership.
        resources: Persistent files and checkpoint authority.

    Returns:
        The original typed summary and accepted effects.

    Raises:
        RuntimeError: Observations, selections or persistence cannot complete.
    """
    resources = resources or PalaceResources()
    configured = palace(spotify, options, callbacks, resources)
    return configured.run(
        options.playlist_id, options.dry_run, options.alphabetical_start
    )
