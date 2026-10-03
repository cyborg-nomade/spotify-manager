"""Shared CLI and HTTP Sauvignon operation and compatibility values."""

from datetime import datetime
from pathlib import Path

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
from spotify_manager.bootstrap.sauvignon import sauvignon_workflow
from spotify_manager.domain.album_recommendations import (
    AlbumRecommendation as AlbumRecommendation,
)
from spotify_manager.domain.album_recommendations import FirstTrack as FirstTrack
from spotify_manager.domain.album_recommendations import (
    SpotifyAlbumOption as SpotifyAlbumOption,
)
from spotify_manager.domain.album_selection import SauvignonResult as SauvignonResult
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
    playlist_id: str,
    choice_reader: AlbumChoiceReader | None,
    *,
    count: int | None = None,
    max_playlist_length: int | None = DEFAULT_MAX_PLAYLIST_LENGTH,
    seed_count: int = DEFAULT_SEED_COUNT,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> SauvignonSummary:
    """Compose and invoke album discovery for a CLI command or HTTP job.

    Args:
        spotify: Caller-owned Spotify client.
        lastfm: History and neighborhood reader.
        playlist_id: Destination identity.
        choice_reader: Invocation-owned edition interaction.
        count: Explicit number of additions.
        max_playlist_length: Optional destination capacity.
        seed_count: Requested number of seeds.
        dry_run: Suppress Spotify writes while preserving preview records.
        echo: Accepted-effect presenter.
        progress_callback: Stage observer and cancellation boundary.
        retry_call: Caller-owned retry policy.
        export_path: Canonical history location.
        recent_path: Recent history location.
        cache_path: Neighborhood cache location.
        log_path: Audit location.
        now: Optional effective UTC time.

    Returns:
        The typed result after accepted effects and audit.

    Raises:
        SauvignonError: Request validation, Spotify observations or audit fail.
    """
    workflow = sauvignon_workflow(
        spotify,
        lastfm,
        playlist_id,
        choice_reader,
        echo,
        progress_callback,
        retry_call,
        export_path,
        recent_path,
        cache_path,
        log_path,
        now,
    )
    return workflow.run(playlist_id, count, max_playlist_length, seed_count, dry_run)
