"""Invoke discography use cases for CLI and HTTP features."""

from datetime import date as date
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.discography_values import (
    DiscographyCancelledError as DiscographyCancelledError,
)
from spotify_manager.application.discography_values import (
    DiscographyConfigError as DiscographyConfigError,
)
from spotify_manager.application.discography_values import (
    DiscographyError as DiscographyError,
)
from spotify_manager.application.discography_values import (
    DiscographyRunSummary as DiscographyRunSummary,
)
from spotify_manager.bootstrap import discography as composition
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.discography_values import ArtistSelection as ArtistSelection
from spotify_manager.domain.discography_values import CatalogRelease as CatalogRelease
from spotify_manager.domain.discography_values import DiscographyPlan as DiscographyPlan
from spotify_manager.domain.discography_values import QueueArtist as QueueArtist
from spotify_manager.domain.discography_values import QueueName as QueueName
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines.blast_from_past import (
    fetch_random_indexes as fetch_random_indexes,
)
from spotify_manager.routines.discography import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.discography import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.discography import (
    DEFAULT_STATE_PATH as DEFAULT_STATE_PATH,
)
from spotify_manager.routines.discography import QUEUE_LABELS as QUEUE_LABELS
from spotify_manager.routines.discography import (
    HistoricalArtistChoiceReader as HistoricalArtistChoiceReader,
)
from spotify_manager.routines.discography import ProgressCallback as ProgressCallback
from spotify_manager.routines.discography import RandomIndexReader as RandomIndexReader
from spotify_manager.routines.discography import ReleaseSelector as ReleaseSelector
from spotify_manager.routines.discography import RetryCall as RetryCall
from spotify_manager.routines.discography import _default_state as _default_state
from spotify_manager.routines.discography import (
    format_release_indexes as format_release_indexes,
)
from spotify_manager.routines.discography import parse_playlist_id as parse_playlist_id
from spotify_manager.routines.discography import (
    parse_playlist_ids as parse_playlist_ids,
)
from spotify_manager.routines.discography import (
    parse_release_indexes as parse_release_indexes,
)
from spotify_manager.routines.discography import validate_state as validate_state


def build_discography_plan(
    spotify: Spotify,
    playlist_ids: dict[QueueName, str],
    release_selector: ReleaseSelector,
    *,
    queue_3_playlist_id: str | None = None,
    historical_artist_choice_reader: HistoricalArtistChoiceReader | None = None,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
) -> DiscographyPlan:
    """Build the next round-week batch without changing Spotify or state.

    Args:
        spotify: Original spotify boundary.
        playlist_ids: Original playlist ids boundary.
        release_selector: Original release selector boundary.
        queue_3_playlist_id: Original queue 3 playlist id boundary.
        historical_artist_choice_reader: Original historical mapping interaction.
        scrobbles_path: Original scrobbles path boundary.
        today: Original today boundary.
        random_index_reader: Original random index reader boundary.
        retry_call: Original retry call boundary.
        progress_callback: Original progress callback boundary.
        state_path: Original state path boundary.
        state_service: Original state service boundary.

    Returns:
        Original complete compatible result.
    """
    return composition.planning(
        spotify,
        playlist_ids,
        release_selector,
        queue_3_playlist_id,
        historical_artist_choice_reader,
        scrobbles_path,
        today,
        random_index_reader,
        retry_call,
        progress_callback,
        state_path,
        state_service,
    ).run()


def apply_discography_plan(
    spotify: Spotify,
    plan: DiscographyPlan,
    *,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> DiscographyRunSummary:
    """Remove confirmed markers, audit each artist, then advance final priority.

    Args:
        spotify: Original spotify boundary.
        plan: Original plan boundary.
        retry_call: Original retry call boundary.
        progress_callback: Original progress callback boundary.
        state_path: Original state path boundary.
        state_service: Original state service boundary.
        log_path: Original log path boundary.

    Returns:
        Original complete compatible result.
    """
    return composition.execution(
        spotify, retry_call, progress_callback, state_path, state_service, log_path
    ).run(plan)
