"""Invoke new wine use cases for CLI and HTTP features."""

from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.new_wine import NewWineOptions as NewWineOptions
from spotify_manager.application.new_wine import (
    flush_new_wine as execute_flush_new_wine,
)
from spotify_manager.application.new_wine_values import (
    CellarRefillResult as CellarRefillResult,
)
from spotify_manager.application.new_wine_values import (
    CellarRefillSummary as CellarRefillSummary,
)
from spotify_manager.application.new_wine_values import FlushResult as FlushResult
from spotify_manager.application.new_wine_values import FlushSummary as FlushSummary
from spotify_manager.application.new_wine_values import (
    NewWineConfigError as NewWineConfigError,
)
from spotify_manager.application.new_wine_values import NewWineError as NewWineError
from spotify_manager.bootstrap.new_wine import new_wine_dependencies
from spotify_manager.core.state import StateService as StateService
from spotify_manager.domain.catalog import PlaylistTrack as PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate as ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack as ReleaseTrack
from spotify_manager.routines.new_wine import CHOICE_CONTINUE as CHOICE_CONTINUE
from spotify_manager.routines.new_wine import CHOICE_CUTOFF as CHOICE_CUTOFF
from spotify_manager.routines.new_wine import CHOICE_DROP as CHOICE_DROP
from spotify_manager.routines.new_wine import CHOICE_FINISH as CHOICE_FINISH
from spotify_manager.routines.new_wine import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.new_wine import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.new_wine import DEFAULT_ALBUMS_PATH as DEFAULT_ALBUMS_PATH
from spotify_manager.routines.new_wine import (
    DEFAULT_LIKED_TRACKS_PATH as DEFAULT_LIKED_TRACKS_PATH,
)
from spotify_manager.routines.new_wine import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.new_wine import (
    DEFAULT_REMOVED_ALBUMS_LOG_PATH as DEFAULT_REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.routines.new_wine import DEFAULT_STATE_PATH as DEFAULT_STATE_PATH
from spotify_manager.routines.new_wine import Echo as Echo
from spotify_manager.routines.new_wine import (
    EndpointChoiceReader as EndpointChoiceReader,
)
from spotify_manager.routines.new_wine import ProgressCallback as ProgressCallback
from spotify_manager.routines.new_wine import ReleaseChoiceReader as ReleaseChoiceReader
from spotify_manager.routines.new_wine import RetryCall as RetryCall
from spotify_manager.routines.new_wine import _clock as _clock
from spotify_manager.routines.new_wine import _default_state as _default_state
from spotify_manager.routines.new_wine import _local_year as _local_year
from spotify_manager.routines.new_wine import parse_playlist_id as parse_playlist_id
from spotify_manager.routines.new_wine import validate_state as validate_state


def flush_new_wine(
    sp: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    endpoint_choice_reader: EndpointChoiceReader | None = None,
    choose_album_endpoints: bool = False,
    wine_cellar_playlist_id: str | None = None,
    no_discovery: bool = False,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    liked_tracks_path: Path = DEFAULT_LIKED_TRACKS_PATH,
    removed_albums_log_path: Path = DEFAULT_REMOVED_ALBUMS_LOG_PATH,
) -> FlushSummary:
    """Advance each snapshotted marker through the injected New Wine workflow.

    Args:
        sp: Caller-owned synchronous Spotify client.
        new_wine_playlist_id: Source and progression destination.
        sauvignon_playlist_id: Completed-album destination.
        choice_reader: Existing release selection callback.
        endpoint_choice_reader: Optional album/EP endpoint callback.
        choose_album_endpoints: Whether endpoint selection is requested.
        wine_cellar_playlist_id: Optional post-flush refill source.
        no_discovery: Whether refill requires existing library affinity.
        dry_run: Preview effects while retaining legacy audit writes.
        year: Existing current-year override.
        echo: Original message sink.
        progress_callback: Optional progress/cancellation callback.
        retry_call: Existing retry callback, or direct invocation.
        state_path: Original namespace path.
        state_service: Optional shared state service.
        log_path: Original audit destination.
        albums_path: Canonical saved-album mirror.
        liked_tracks_path: Canonical liked-track mirror.
        removed_albums_log_path: Removed-album recovery log.

    Returns:
        Original result including pause, resume and refill outcomes.

    Raises:
        NewWineError: Observations, choices or durable records are invalid.
    """
    options = NewWineOptions(
        new_wine_playlist_id,
        sauvignon_playlist_id,
        wine_cellar_playlist_id,
        no_discovery,
        choose_album_endpoints,
        dry_run,
    )
    configured = new_wine_dependencies(
        sp,
        options,
        choice_reader,
        endpoint_choice_reader,
        year,
        echo,
        progress_callback,
        retry_call,
        state_path,
        state_service,
        log_path,
        albums_path,
        liked_tracks_path,
        removed_albums_log_path,
        _clock,
        _local_year,
    )
    return execute_flush_new_wine(options, configured)
