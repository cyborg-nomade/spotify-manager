"""Bind original artist-review files, catalog seams and synchronous Spotify retries."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path
from time import sleep as default_sleep

from spotipy import Spotify

from spotify_manager.application.artist_review_catalog import ArtistCatalog
from spotify_manager.application.artist_review_effects import ReviewCatalog
from spotify_manager.application.artist_review_effects import ReviewInteraction
from spotify_manager.application.artist_review_effects import ReviewSpotify
from spotify_manager.application.artist_review_effects import ReviewStorage
from spotify_manager.application.artist_review_run import ArtistReview
from spotify_manager.application.artist_review_session import ReviewSession
from spotify_manager.application.artist_review_values import ArtistReviewPaths
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.application.artist_review_values import ReviewCounts
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.artist_review_values import QueuePlaylists
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.infrastructure.legacy.artist_review_catalog import (
    LegacyCatalogCache,
)
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import review_artists as legacy


@dataclass
class ReviewResources:
    """Own original run-scoped metadata and supplied synchronous retry boundaries.

    Args:
        spotify: Original caller-owned Spotify client.
        paths: Original complete file locations.
        echo: Original presenter.
        sleep: Original blocking retry wait.
        retry_delay: Original transient delay.
        retry_attempts: Original transient attempt count.
        state_service: Original optional shared state authority.
        cache: Original mutable invocation metadata cache.
    """

    spotify: Spotify
    paths: ArtistReviewPaths
    echo: Callable[[str], None]
    sleep: Callable[[float], None]
    retry_delay: int
    retry_attempts: int
    state_service: StateService | None
    cache: dict[str, dict[str, object]] = field(default_factory=dict)

    def state(self) -> ArtistReviewState:
        """Resolve, load and attach original progress persistence.

        Returns:
            Original mutable state with the original save callback semantics.
        """
        from spotify_manager.routines.review_artists import _deserialize_state
        from spotify_manager.routines.review_artists import _state_access

        access = _state_access(self.paths, self.state_service)
        state = _deserialize_state(access.load())
        state.persist = partial(_persist, access, state)
        return state

    def initialize_cache(self, refresh: bool) -> None:
        """Initialize metadata after original state resolution.

        Args:
            refresh: Original refresh-cache option.
        """
        from spotify_manager.routines.review_artists import load_cache

        self.cache = load_cache(self.paths.cache, refresh=refresh)

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Retain original narrowed synchronous transient retry behavior.

        Args:
            operation: Original complete effect.
            description: Original visible operation description.

        Returns:
            Original accepted response.
        """
        from spotify_manager.infrastructure.spotify.retry import (
            retry_spotify_server_errors,
        )

        return retry_spotify_server_errors(
            operation,
            description,
            self.echo,
            self.sleep,
            self.retry_delay,
            self.retry_attempts,
        )

    def tracks(self, artist: YourLibraryArtist) -> list[TrackCandidate]:
        """Read original cached Spotify-ranked associated tracks.

        Args:
            artist: Original current reviewed artist.

        Returns:
            Original complete ordered candidates.
        """
        return catalog(
            self.spotify, artist, self.cache, self.paths.cache, self.retry
        ).ranked_tracks()

    def ranked(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Read original cached ranked album/EP releases.

        Args:
            artist: Original current reviewed artist.

        Returns:
            Original complete enriched releases.
        """
        return catalog(
            self.spotify, artist, self.cache, self.paths.cache, self.retry
        ).ranked_releases()

    def earliest(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Read original cached chronological releases.

        Args:
            artist: Original current reviewed artist.

        Returns:
            Original complete enriched releases.
        """
        return catalog(
            self.spotify, artist, self.cache, self.paths.cache, self.retry
        ).earliest_releases()

    def append(self, playlist: str, uri: str, description: str) -> object:
        """Retry original single-marker addition at the mutation boundary.

        Args:
            playlist: Original destination identity.
            uri: Original marker URI.
            description: Original visible retry description.

        Returns:
            Original mutation response.
        """
        from spotify_manager.routines.review_artists import add_playlist_item

        return self.retry(
            partial(add_playlist_item, self.spotify, playlist, uri), description
        )

    def remove(self, playlist: str, uris: list[str], description: str) -> object:
        """Retry original ordered marker removals at the mutation boundary.

        Args:
            playlist: Original source identity.
            uris: Original complete batch.
            description: Original visible retry description.

        Returns:
            Original mutation response.
        """
        from spotify_manager.routines.review_artists import remove_playlist_items

        return self.retry(
            partial(remove_playlist_items, self.spotify, playlist, uris),
            description,
        )

    def unfollow(self, uris: list[str], description: str) -> object:
        """Retry the original complete unfollow batch.

        Args:
            uris: Original complete ordered artist URIs.
            description: Original visible retry description.

        Returns:
            Original mutation response.
        """
        from spotify_manager.routines.review_artists import remove_library_artists

        return self.retry(
            partial(remove_library_artists, self.spotify, uris), description
        )


def _persist(access: RoutineState, state: ArtistReviewState) -> None:
    from spotify_manager.routines.review_artists import _serialize_state

    access.save(_serialize_state(state))


def _event(run_id: str, name: str, **details: object) -> dict[str, object]:
    from spotify_manager.routines.review_artists import event

    return event(run_id, name, **details)


def _storage(resources: ReviewResources) -> ReviewStorage:
    from spotify_manager.routines.review_artists import append_events
    from spotify_manager.routines.review_artists import load_models
    from spotify_manager.routines.review_artists import new_run_id
    from spotify_manager.routines.review_artists import save_artists
    from spotify_manager.routines.review_artists import update_stats_after_unfollow

    paths = resources.paths
    return ReviewStorage(
        partial(load_models, paths.artists, YourLibraryArtist),
        partial(load_models, paths.liked_tracks, YourLibraryTrack),
        resources.state,
        resources.initialize_cache,
        new_run_id,
        _event,
        partial(append_events, paths.log),
        partial(save_artists, paths.artists),
        partial(update_stats_after_unfollow, paths.stats_history),
    )


def _spotify(resources: ReviewResources) -> ReviewSpotify:
    from spotify_manager.routines.review_artists import playlist_membership

    return ReviewSpotify(
        partial(playlist_membership, resources.spotify, retry_call=resources.retry),
        resources.append,
        resources.remove,
        resources.unfollow,
    )


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
    catalog = ReviewCatalog(resources.tracks, resources.ranked, resources.earliest)
    interaction = ReviewInteraction(echo, progress, track_choice, release_choice)
    return ArtistReview(
        playlists, _storage(resources), catalog, _spotify(resources), interaction
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
    from spotify_manager.routines.review_artists import playlist_membership

    resources = ReviewResources(sp, paths, echo, default_sleep, 0, 0, None)
    spotify = ReviewSpotify(
        partial(playlist_membership, sp, retry_call=retry),
        partial(_append, sp, retry),
        partial(_remove, sp, retry),
        partial(_unfollow, sp, retry),
    )
    catalog = ReviewCatalog(resources.tracks, resources.ranked, resources.earliest)
    return ReviewSession(
        artists,
        Counter(),
        set(),
        state,
        run_id,
        QueuePlaylists("", "", ""),
        _storage(resources),
        catalog,
        spotify,
        ReviewInteraction(echo, None, None, None),
        counts,
    )


def _append(
    sp: Spotify, retry: legacy.RetryCall, identity: str, uri: str, description: str
) -> object:
    from spotify_manager.routines.review_artists import add_playlist_item

    return retry(partial(add_playlist_item, sp, identity, uri), description)


def _remove(
    sp: Spotify,
    retry: legacy.RetryCall,
    identity: str,
    uris: list[str],
    description: str,
) -> object:
    from spotify_manager.routines.review_artists import remove_playlist_items

    return retry(partial(remove_playlist_items, sp, identity, uris), description)


def _unfollow(
    sp: Spotify, retry: legacy.RetryCall, uris: list[str], description: str
) -> object:
    from spotify_manager.routines.review_artists import remove_library_artists

    return retry(partial(remove_library_artists, sp, uris), description)


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
    from spotify_manager.routines.review_artists import _read_discography_page
    from spotify_manager.routines.review_artists import _read_first
    from spotify_manager.routines.review_artists import _read_ranked_page
    from spotify_manager.routines.review_artists import _read_tracks
    from spotify_manager.routines.review_artists import save_cache

    repository = LegacyCatalogCache(
        artist.spotify_id, artist.name, cache, partial(save_cache, path, cache)
    )
    return ArtistCatalog(
        repository,
        partial(_read_tracks, sp, artist, retry),
        partial(_read_ranked_page, sp, artist, retry),
        partial(_read_discography_page, sp, artist, retry),
        partial(_read_first, sp, retry),
    )
