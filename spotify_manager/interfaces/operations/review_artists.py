"""Invoke review artists use cases for CLI and HTTP features."""

from collections.abc import Callable as Callable
from time import sleep as default_sleep

from spotipy import Spotify as Spotify

from spotify_manager.application.artist_review_recovery import (
    flush_moves as flush_moves,
)
from spotify_manager.application.artist_review_recovery import (
    flush_unfollows as flush_unfollows,
)
from spotify_manager.application.artist_review_values import (
    ArtistReviewPaths as ArtistReviewPaths,
)
from spotify_manager.application.artist_review_values import (
    ArtistReviewState as ArtistReviewState,
)
from spotify_manager.application.artist_review_values import (
    ArtistReviewSummary as ArtistReviewSummary,
)
from spotify_manager.application.artist_review_values import (
    ReviewCounts as ReviewCounts,
)
from spotify_manager.bootstrap import artist_review as composition
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.artist_review_values import (
    ArtistReviewConfigError as ArtistReviewConfigError,
)
from spotify_manager.domain.artist_review_values import (
    ArtistReviewError as ArtistReviewError,
)
from spotify_manager.domain.artist_review_values import (
    PlaylistMembership as PlaylistMembership,
)
from spotify_manager.domain.artist_review_values import QueuePlaylists as QueuePlaylists
from spotify_manager.domain.artist_review_values import (
    ReleaseCandidate as ReleaseCandidate,
)
from spotify_manager.domain.artist_review_values import TrackCandidate as TrackCandidate
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_MAX_ATTEMPTS as TRANSIENT_MAX_ATTEMPTS,
)
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_RETRY_DELAY_SECONDS as TRANSIENT_RETRY_DELAY_SECONDS,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyRateLimitError as SpotifyRateLimitError,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyTransientServerError as SpotifyTransientServerError,
)
from spotify_manager.models.your_library import YourLibraryArtist as YourLibraryArtist
from spotify_manager.routines.review_artists import CHOICE_DECLINE as CHOICE_DECLINE
from spotify_manager.routines.review_artists import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.review_artists import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.review_artists import DEFAULT_PATHS as DEFAULT_PATHS
from spotify_manager.routines.review_artists import Echo as Echo
from spotify_manager.routines.review_artists import ProgressCallback as ProgressCallback
from spotify_manager.routines.review_artists import (
    ReleaseChoiceReader as ReleaseChoiceReader,
)
from spotify_manager.routines.review_artists import RetryCall as RetryCall
from spotify_manager.routines.review_artists import Sleep as Sleep
from spotify_manager.routines.review_artists import (
    TrackChoiceReader as TrackChoiceReader,
)
from spotify_manager.routines.review_artists import _default_state as _default_state
from spotify_manager.routines.review_artists import validate_state as validate_state


def flush_pending_unfollows(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry_call: RetryCall,
    echo: Echo,
) -> list[YourLibraryArtist]:
    """Execute journaled automatic unfollows in API-sized batches.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artists: Original caller-owned current followed-artist list.
        state: Original mutable completed and pending progress.
        counts: Original mutable invocation counters.
        paths: Original complete file locations.
        run_id: Original sortable invocation identity.
        retry_call: Original caller-owned synchronous retry wrapper.
        echo: Original visible progress and action presenter.

    Returns:
        Original current followed artists after recovery.
    """
    session = composition.recovery_session(
        sp, artists, state, counts, paths, run_id, retry_call, echo
    )
    flush_unfollows(session)
    return session.artists


def flush_pending_queue_moves(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry_call: RetryCall,
    get_membership: Callable[[str], PlaylistMembership],
    echo: Echo,
) -> None:
    """Finish journaled queue-one to queue-two moves idempotently.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artists: Original caller-owned current followed-artist list.
        state: Original mutable completed and pending progress.
        counts: Original mutable invocation counters.
        paths: Original complete file locations.
        run_id: Original sortable invocation identity.
        retry_call: Original caller-owned synchronous retry wrapper.
        get_membership: Original caller-owned queue membership authority.
        echo: Original visible progress and action presenter.
    """
    session = composition.recovery_session(
        sp, artists, state, counts, paths, run_id, retry_call, echo
    )
    flush_moves(session, get_membership)


def review_artists(
    sp: Spotify,
    playlists: QueuePlaylists,
    track_choice_reader: TrackChoiceReader | None = None,
    release_choice_reader: ReleaseChoiceReader | None = None,
    paths: ArtistReviewPaths = DEFAULT_PATHS,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    refresh_cache: bool = False,
    limit: int | None = None,
    sleep: Sleep = default_sleep,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
    state_service: StateService | None = None,
) -> ArtistReviewSummary:
    """Review followed artists using local counts and targeted Spotify calls.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        playlists: Original parsed three queue identities.
        track_choice_reader: Original optional tied-track decision reader.
        release_choice_reader: Original optional release decision reader.
        paths: Original complete file locations.
        echo: Original visible progress and action presenter.
        progress_callback: Original optional position/total presenter.
        refresh_cache: Original option to rebuild metadata from live reads.
        limit: Original pending-list slice, including zero and negatives.
        sleep: Original blocking retry wait.
        transient_retry_delay_seconds: Original transient retry delay.
        transient_max_attempts: Original maximum transient attempts.
        state_service: Original optional shared state authority.

    Returns:
        Original complete paused or completed ten-field summary.

    Raises:
        ArtistReviewError: An original required boundary is invalid.
    """
    return composition.compose(
        sp,
        playlists,
        paths,
        echo,
        progress_callback,
        track_choice_reader,
        release_choice_reader,
        sleep,
        transient_retry_delay_seconds,
        transient_max_attempts,
        state_service,
    ).run(refresh_cache, limit)
