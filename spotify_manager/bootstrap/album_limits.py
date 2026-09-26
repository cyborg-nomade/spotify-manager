"""Compose saved-album review from caller-owned resources."""

from collections.abc import Callable
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.album_limits import review_albums
from spotify_manager.application.artist_follows import ArtistFollowOutcome
from spotify_manager.application.artist_follows import follow_album_artist
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.album_limits import AlbumArtistAdapter
from spotify_manager.infrastructure.legacy.album_limits import LegacyAlbumReview
from spotify_manager.interfaces.presenters.album_limits import ActionReader
from spotify_manager.interfaces.presenters.album_limits import AlbumReviewPresenter
from spotify_manager.interfaces.presenters.album_limits import ProgressCallback
from spotify_manager.models.your_library import YourLibraryAlbum


def follow_review_artist(
    spotify: Spotify,
    album: YourLibraryAlbum,
    known_artists: dict[str, str],
    checked_artists: set[str],
) -> ArtistFollowOutcome:
    """Bind existing artist effects to the shared application decision.

    Args:
        spotify: Caller-owned client.
        album: Current review item.
        known_artists: Run-scoped resolution cache.
        checked_artists: Run-scoped completed artist checks.

    Returns:
        Original follow outcome and persistence details.
    """
    return follow_album_artist(
        AlbumArtistAdapter(spotify, known_artists), album, checked_artists
    )


def run_album_review(
    spotify: Spotify,
    action_reader: ActionReader,
    threshold: float,
    use_cache: bool,
    refresh_cache: bool,
    echo: Callable[[str], None],
    log_path: Path,
    decisions_path: Path,
    state_service: StateService | None,
    progress_callback: ProgressCallback | None,
    sleep: Callable[[float], None],
    retry_delay: int,
    max_attempts: int,
) -> None:
    """Bind the synchronous adapter and existing interface callbacks.

    Args:
        spotify: Caller-owned client.
        action_reader: Existing user-choice callback.
        threshold: Retention threshold.
        use_cache: Original cache-read option.
        refresh_cache: Original cache-refresh option.
        echo: Output sink.
        log_path: Removal audit destination.
        decisions_path: Resolved decisions path.
        state_service: Optional shared-state service.
        progress_callback: Optional completion callback.
        sleep: Retry wait callback.
        retry_delay: Retry delay.
        max_attempts: Retry limit.
    """
    library = LegacyAlbumReview(
        spotify,
        threshold,
        use_cache,
        refresh_cache,
        echo,
        log_path,
        decisions_path,
        state_service,
        sleep,
        retry_delay,
        max_attempts,
    )
    review_albums(library, AlbumReviewPresenter(action_reader, echo, progress_callback))
