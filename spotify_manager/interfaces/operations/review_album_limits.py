"""Invoke review album limits use cases for CLI and HTTP features."""

from pathlib import Path as Path
from time import sleep as default_sleep

from spotipy import Spotify as Spotify

from spotify_manager.application.album_limits import review_albums as review_albums
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.infrastructure.legacy.album_limits import (
    LegacyAlbumReview as LegacyAlbumReview,
)
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
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
from spotify_manager.infrastructure.spotify.retry import (
    format_retry_after as format_retry_after,
)
from spotify_manager.infrastructure.spotify.retry import (
    format_retry_delay as format_retry_delay,
)
from spotify_manager.infrastructure.spotify.retry import (
    format_transient_spotify_failure as format_transient_spotify_failure,
)
from spotify_manager.infrastructure.spotify.retry import (
    get_retry_after_seconds as get_retry_after_seconds,
)
from spotify_manager.infrastructure.spotify.retry import (
    retry_spotify_server_errors as retry_spotify_server_errors,
)
from spotify_manager.interfaces.presenters.album_limits import (
    ActionReader as ActionReader,
)
from spotify_manager.interfaces.presenters.album_limits import (
    AlbumReviewPresenter as AlbumReviewPresenter,
)
from spotify_manager.interfaces.presenters.album_limits import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.review_album_limits import (
    REVIEW_DECISIONS_PATH as REVIEW_DECISIONS_PATH,
)
from spotify_manager.routines.review_album_limits import Echo as Echo
from spotify_manager.routines.review_album_limits import Sleep as Sleep
from spotify_manager.routines.review_album_limits import (
    validate_review_decisions as validate_review_decisions,
)


def review_album_limits(
    sp: Spotify,
    action_reader: ActionReader,
    threshold: float = 0.5,
    use_cache: bool = True,
    refresh_cache: bool = False,
    echo: Echo = print,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    decisions_path: Path | None = None,
    state_service: StateService | None = None,
    progress_callback: ProgressCallback | None = None,
    sleep: Sleep = default_sleep,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
) -> None:
    """Review saved albums through an injected application use case.

    Args:
        sp: Caller-owned Spotify client.
        action_reader: Interface choice callback.
        threshold: Existing retention threshold.
        use_cache: Read cached track lists when available.
        refresh_cache: Refresh track lists before evaluation.
        echo: Existing message sink.
        log_path: Removal audit destination.
        decisions_path: Optional explicit legacy decisions path.
        state_service: Optional shared-state service.
        progress_callback: Optional completion and cancellation callback.
        sleep: Existing retry wait callback.
        transient_retry_delay_seconds: Existing retry delay.
        transient_max_attempts: Existing retry limit.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyTransientServerError: The configured retry policy is exhausted.
    """
    library = LegacyAlbumReview(
        sp,
        threshold,
        use_cache,
        refresh_cache,
        echo,
        log_path,
        decisions_path or REVIEW_DECISIONS_PATH,
        state_service,
        sleep,
        transient_retry_delay_seconds,
        transient_max_attempts,
    )
    review_albums(library, AlbumReviewPresenter(action_reader, echo, progress_callback))
