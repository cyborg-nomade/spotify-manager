"""Shared CLI and HTTP Sauvignon operation and compatibility values."""

from datetime import date
from datetime import datetime as datetime

from spotipy import Spotify

from spotify_manager.application.sauvignon_values import (
    SauvignonConfigError as SauvignonConfigError,
)
from spotify_manager.application.sauvignon_values import (
    SauvignonError as SauvignonError,
)
from spotify_manager.application.sauvignon_values import (
    SauvignonSummary as SauvignonSummary,
)
from spotify_manager.bootstrap.album_recommendations import album_gathering
from spotify_manager.bootstrap.sauvignon import sauvignon_workflow
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import FirstTrack as FirstTrack
from spotify_manager.domain.album_recommendations import (
    SpotifyAlbumOption as SpotifyAlbumOption,
)
from spotify_manager.domain.album_selection import SauvignonResult as SauvignonResult
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.interfaces.requests.sauvignon import SauvignonCallbacks
from spotify_manager.interfaces.requests.sauvignon import SauvignonOptions
from spotify_manager.interfaces.requests.sauvignon import SauvignonResources
from spotify_manager.routines import sauvignon as legacy
from spotify_manager.routines.sauvignon import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.sauvignon import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.sauvignon import DEFAULT_CACHE_PATH as DEFAULT_CACHE_PATH
from spotify_manager.routines.sauvignon import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.sauvignon import (
    DEFAULT_MAX_PLAYLIST_LENGTH as DEFAULT_MAX_PLAYLIST_LENGTH,
)
from spotify_manager.routines.sauvignon import (
    DEFAULT_RECENT_PATH as DEFAULT_RECENT_PATH,
)
from spotify_manager.routines.sauvignon import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.sauvignon import DEFAULT_SEED_COUNT as DEFAULT_SEED_COUNT
from spotify_manager.routines.sauvignon import AlbumChoiceReader as AlbumChoiceReader
from spotify_manager.routines.sauvignon import Echo as Echo
from spotify_manager.routines.sauvignon import LastFmReader as LastFmReader
from spotify_manager.routines.sauvignon import ProgressCallback as ProgressCallback
from spotify_manager.routines.sauvignon import RetryCall as RetryCall
from spotify_manager.routines.sauvignon import parse_playlist_id as parse_playlist_id


def fill_sauvignon_from_lastfm(
    spotify: Spotify,
    lastfm: LastFmReader,
    options: SauvignonOptions,
    callbacks: SauvignonCallbacks,
    resources: SauvignonResources | None = None,
) -> SauvignonSummary:
    """Compose and invoke album discovery for a CLI command or HTTP job.

    Args:
        spotify: Caller-owned client.
        lastfm: Caller-owned client.
        options: Destinations and execution mode.
        callbacks: Operator decisions, notifications and retry ownership.
        resources: Persistent files and checkpoint authority.

    Returns:
        The original typed summary and accepted effects.

    Raises:
        RuntimeError: Observations, selections or persistence cannot complete.
    """
    resources = resources or SauvignonResources()
    workflow = sauvignon_workflow(
        spotify,
        lastfm,
        options.playlist_id,
        callbacks.choice_reader,
        callbacks.echo,
        callbacks.progress_callback,
        callbacks.retry_call,
        resources.export_path,
        resources.recent_path,
        resources.cache_path,
        resources.log_path,
        options.now,
    )
    return workflow.run(
        options.playlist_id,
        options.count,
        options.max_playlist_length,
        options.seed_count,
        options.dry_run,
    )


def gather_albums(
    spotify: Spotify,
    candidates: tuple[FoundArtCandidate, ...],
    excluded: set[AlbumKey],
    existing: set[str],
    maximum: int,
    week: date,
    retry: legacy.RetryCall,
    progress: legacy.ProgressCallback | None,
) -> tuple[AlbumRecommendation, ...]:
    """Bind independent album gathering to original catalog and retry boundaries.

    Args:
        spotify: Caller-owned Spotify client.
        candidates: Original ordered ranked track pool.
        excluded: Original heard and previously added album keys.
        existing: Original represented destination album identities.
        maximum: Original Python-slice limit on considered tracks.
        week: Original effective listening week.
        retry: Existing caller-owned retry behavior.
        progress: Optional original candidate presenter.

    Returns:
        Original ranked album recommendations after all observations succeed.

    Raises:
        SauvignonSpotifyError: Existing catalog observations are unusable.
    """
    workflow = album_gathering(spotify, retry, progress)
    return workflow.run(candidates, excluded, existing, maximum, week)
