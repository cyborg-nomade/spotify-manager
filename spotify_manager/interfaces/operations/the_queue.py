"""Invoke the queue use cases for CLI and HTTP features."""

from datetime import date as date
from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.queue_fill_values import FillResult as FillResult
from spotify_manager.application.queue_fill_values import FillSummary as FillSummary
from spotify_manager.application.queue_flush_values import FlushResult as FlushResult
from spotify_manager.application.queue_flush_values import FlushSummary as FlushSummary
from spotify_manager.application.queue_values import (
    QueueConfigError as QueueConfigError,
)
from spotify_manager.application.queue_values import QueueError as QueueError
from spotify_manager.bootstrap.queue_fill import queue_fill
from spotify_manager.bootstrap.queue_flush import queue_flush
from spotify_manager.bootstrap.queue_recommendations import queue_recommendations
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.queue_values import (
    ArtistRecommendation as ArtistRecommendation,
)
from spotify_manager.domain.queue_values import ArtistSeed as ArtistSeed
from spotify_manager.routines.the_queue import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.the_queue import (
    CHOICE_SEARCH_PREFIX as CHOICE_SEARCH_PREFIX,
)
from spotify_manager.routines.the_queue import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.the_queue import (
    DEFAULT_ARTISTS_PATH as DEFAULT_ARTISTS_PATH,
)
from spotify_manager.routines.the_queue import DEFAULT_CACHE_PATH as DEFAULT_CACHE_PATH
from spotify_manager.routines.the_queue import DEFAULT_COUNT as DEFAULT_COUNT
from spotify_manager.routines.the_queue import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.the_queue import (
    DEFAULT_RECENT_PATH as DEFAULT_RECENT_PATH,
)
from spotify_manager.routines.the_queue import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.the_queue import DEFAULT_SEED_COUNT as DEFAULT_SEED_COUNT
from spotify_manager.routines.the_queue import DEFAULT_STATE_PATH as DEFAULT_STATE_PATH
from spotify_manager.routines.the_queue import MIN_CANDIDATE_POOL as MIN_CANDIDATE_POOL
from spotify_manager.routines.the_queue import ArtistChoiceReader as ArtistChoiceReader
from spotify_manager.routines.the_queue import Echo as Echo
from spotify_manager.routines.the_queue import LastFmReader as LastFmReader
from spotify_manager.routines.the_queue import ProgressCallback as ProgressCallback
from spotify_manager.routines.the_queue import QueuePlaylists as QueuePlaylists
from spotify_manager.routines.the_queue import RetryCall as RetryCall
from spotify_manager.routines.the_queue import _default_state as _default_state
from spotify_manager.routines.the_queue import validate_state as validate_state


def gather_artist_recommendations(
    lastfm: LastFmReader,
    seeds: tuple[ArtistSeed, ...],
    heard_keys: set[str],
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    week_start: date | None = None,
    candidate_pool_size: int = MIN_CANDIDATE_POOL,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[ArtistRecommendation, ...]:
    """Aggregate Last.fm artist neighborhoods into a weekly ordering.

    Args:
        lastfm: Caller-owned original Last.fm client.
        seeds: Original ordered weighted seed artists.
        heard_keys: Original heard artist identities.
        cache_path: Original neighborhood cache location.
        log_path: Original prior-addition audit location.
        week_start: Optional original effective listening week.
        candidate_pool_size: Original pool slice limit.
        now: Optional original timestamp.
        progress_callback: Optional original progress presenter.

    Returns:
        Original weekly ordering after accepted neighborhood checkpoints.

    Raises:
        QueueStateError: Original cache or audit data is unusable.
    """
    configured = queue_recommendations(
        lastfm, cache_path, log_path, now, progress_callback
    )
    return configured.run(seeds, heard_keys, week_start, candidate_pool_size)


def fill_queue_from_lastfm(
    sp: Spotify,
    lastfm: LastFmReader,
    playlists: QueuePlaylists,
    choice_reader: ArtistChoiceReader | None,
    *,
    count: int | None = DEFAULT_COUNT,
    max_playlist_length: int | None = None,
    seed_count: int = DEFAULT_SEED_COUNT,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> FillSummary:
    """Add unheard Last.fm artist recommendations to The Queue.

    Args:
        sp: Caller-owned original Spotify client.
        lastfm: Caller-owned original Last.fm reader.
        playlists: Original parsed destination identities.
        choice_reader: Original optional mapping interaction.
        count: Original optional requested additions.
        max_playlist_length: Original optional maximum Queue length.
        seed_count: Original requested weekly seeds.
        dry_run: Original preview behavior.
        echo: Original text presenter.
        progress_callback: Original optional progress presenter.
        retry_call: Original optional retry boundary.
        export_path: Original history export location.
        recent_path: Original recent-history location.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        cache_path: Original neighborhood cache location.
        log_path: Original audit location.
        now: Original optional timestamp.

    Returns:
        Original complete ordered fill outcome.

    Raises:
        QueueConfigError: Original limits conflict or are invalid.
        QueueStateError: Original history, cache or state is unusable.
        QueueSpotifyError: Original follow or liked response is invalid.
    """
    from spotify_manager.application.queue_fill_values import QueueFillRequest

    configured = queue_fill(
        sp,
        lastfm,
        playlists,
        choice_reader,
        echo,
        progress_callback,
        retry_call,
        export_path,
        recent_path,
        state_path,
        state_service,
        cache_path,
        log_path,
        now,
    )
    return configured.run(
        QueueFillRequest(count, max_playlist_length, seed_count, dry_run)
    )


def flush_queue(
    sp: Spotify,
    playlists: QueuePlaylists,
    *,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
) -> FlushSummary:
    """Advance the first ten Queue artists through their unliked top tracks.

    Args:
        sp: Original caller-owned Spotify client.
        playlists: Original configured destination identities.
        dry_run: Original preview behavior.
        echo: Original text presenter.
        progress_callback: Original optional stage presenter.
        retry_call: Original optional retry boundary.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        log_path: Original audit location.
        artists_path: Original artist mirror location.

    Returns:
        Original ordered outcomes after accepted effects and checkpoints.

    Raises:
        QueueStateError: Original stored sources, plans or counts are invalid.
        QueueSpotifyError: Original follow-status response is invalid.
    """
    configured = queue_flush(
        sp,
        playlists,
        echo,
        progress_callback,
        retry_call,
        state_path,
        state_service,
        log_path,
        artists_path,
    )
    return configured.run(dry_run)
