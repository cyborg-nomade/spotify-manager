"""Bind original artist-review files, catalog seams and synchronous Spotify retries."""

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from time import sleep as default_sleep

from spotipy import Spotify

from spotify_manager.application.artist_review_catalog import ArtistCatalog
from spotify_manager.application.artist_review_effects import ReviewCatalog
from spotify_manager.application.artist_review_effects import ReviewInteraction
from spotify_manager.application.artist_review_run import ArtistReview
from spotify_manager.application.artist_review_session import ReviewSession
from spotify_manager.application.artist_review_values import ArtistReviewPaths
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.application.artist_review_values import ReviewCounts
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.artist_review_values import QueuePlaylists
from spotify_manager.infrastructure.artist_review_resources import ReviewFiles
from spotify_manager.infrastructure.artist_review_resources import ReviewMetadata
from spotify_manager.infrastructure.artist_review_resources import ReviewResources
from spotify_manager.infrastructure.artist_review_resources import ReviewSpotifyAccess
from spotify_manager.infrastructure.artist_review_resources import SpotifyArtistReads
from spotify_manager.infrastructure.legacy.artist_review_catalog import (
    LegacyCatalogCache,
)
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.routines import review_artists as legacy


def compose(
    sp: Spotify,
    playlists: QueuePlaylists,
    paths: ArtistReviewPaths,
    echo: Callable[[str], None],
    progress: legacy.ProgressCallback | None,
    track_choice: legacy.TrackChoiceReader | None,
    release_choice: legacy.ReleaseChoiceReader | None,
    sleep: Callable[[float], None],
    retry_delay: int,
    retry_attempts: int,
    state_service: StateService | None,
) -> ArtistReview:
    """Bind the original compatibility facade to independently injected stages.

    Args:
        sp: Original caller-owned Spotify client.
        playlists: Original parsed queue identities.
        paths: Original file locations.
        echo: Original presenter.
        progress: Original optional progress callback.
        track_choice: Original optional tied-track prompt.
        release_choice: Original optional release prompt.
        sleep: Original blocking retry wait.
        retry_delay: Original transient retry delay.
        retry_attempts: Original transient attempt count.
        state_service: Original optional shared state authority.

    Returns:
        Complete original synchronous artist review.
    """
    resources = ReviewResources(
        sp, paths, echo, sleep, retry_delay, retry_attempts, state_service
    )
    catalog = ReviewCatalog(resources)
    interaction = ReviewInteraction(echo, progress, track_choice, release_choice)
    return ArtistReview(
        playlists,
        ReviewFiles(resources),
        catalog,
        ReviewSpotifyAccess(resources.spotify, resources.retry),
        interaction,
    )


def recovery_session(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry: legacy.RetryCall,
    echo: Callable[[str], None],
) -> ReviewSession:
    """Bind original public recovery helpers without loading new invocation facts.

    Args:
        sp: Original caller-owned Spotify client.
        artists: Original caller-owned current followed artists.
        state: Original caller-owned mutable progress.
        counts: Original caller-owned mutable action counts.
        paths: Original local files.
        run_id: Original invocation identity.
        retry: Original caller-owned retry wrapper.
        echo: Original recovery presenter.

    Returns:
        Recovery context sharing the exact original mutable authorities.
    """
    resources = ReviewResources(sp, paths, echo, default_sleep, 0, 0, None)
    spotify = ReviewSpotifyAccess(sp, retry)
    catalog = ReviewCatalog(resources)
    return ReviewSession(
        artists,
        Counter(),
        set(),
        state,
        run_id,
        QueuePlaylists("", "", ""),
        ReviewFiles(resources),
        catalog,
        spotify,
        ReviewInteraction(echo, None, None, None),
        counts,
    )


def catalog(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    path: Path,
    retry: legacy.RetryCall,
) -> ArtistCatalog:
    """Bind original shared cache and parsed SDK read seams for one reviewed artist.

    Args:
        sp: Original caller-owned SDK client.
        artist: Original reviewed followed artist.
        cache: Original same complete mutable metadata cache.
        path: Original complete metadata checkpoint destination.
        retry: Original caller-owned retry wrapper.

    Returns:
        Complete original synchronous catalog gatherer.
    """
    repository = LegacyCatalogCache(
        artist.spotify_id, artist.name, cache, ReviewMetadata(path, cache)
    )
    return ArtistCatalog(repository, SpotifyArtistReads(sp, artist, retry))
