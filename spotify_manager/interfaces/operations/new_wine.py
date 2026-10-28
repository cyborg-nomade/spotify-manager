"""Invoke new wine use cases for CLI and HTTP features."""

from pathlib import Path as Path

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
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.bootstrap.new_wine import new_wine_dependencies
from spotify_manager.domain.catalog import PlaylistTrack as PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate as ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack as ReleaseTrack
from spotify_manager.interfaces.requests.new_wine import NewWineCallbacks
from spotify_manager.interfaces.requests.new_wine import NewWineStorage
from spotify_manager.routines.new_wine import _CLOCK_RESOURCE
from spotify_manager.routines.new_wine import _LOCAL_YEAR_RESOURCE
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


async def flush_new_wine(
    sp: Spotify,
    options: NewWineOptions,
    callbacks: NewWineCallbacks,
    storage: NewWineStorage | None = None,
    year: int | None = None,
) -> FlushSummary:
    """Advance New Wine with explicit decisions and persistence resources.

    Args:
        sp: Caller-owned synchronous Spotify client.
        options: Destinations and preview, refill and endpoint modes.
        callbacks: Run-owned operator decisions and notifications.
        storage: Namespace, mirrors and audit destinations.
        year: Review year, retaining the original local-year fallback.

    Returns:
        The original flush, resume and cellar-refill results.

    Raises:
        NewWineError: Observations, choices or durable records are invalid.
    """
    dependencies = new_wine_dependencies(
        sp,
        options,
        callbacks,
        storage or NewWineStorage(),
        year,
        _CLOCK_RESOURCE,
        _LOCAL_YEAR_RESOURCE,
    )
    return await execute_flush_new_wine(options, dependencies)
