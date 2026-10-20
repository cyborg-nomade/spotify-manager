"""Bind original artist-review files, catalog seams and synchronous Spotify retries."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.artist_review_catalog import CatalogCache
from spotify_manager.application.artist_review_catalog import CatalogReads
from spotify_manager.application.artist_review_catalog import FirstTrack
from spotify_manager.application.artist_review_catalog import RawReleasePage
from spotify_manager.application.artist_review_catalog import ReleasePage
from spotify_manager.application.artist_review_membership import MembershipPage
from spotify_manager.application.artist_review_membership import MembershipPages
from spotify_manager.application.artist_review_values import ArtistReviewPaths
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.infrastructure.legacy.artist_review_catalog import (
    LegacyCatalogCache,
)
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


type RetryCall = Callable[[Callable[[], object], str], object]


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
            Original mutable state with the original checkpoint publication order.
        """
        from spotify_manager.routines.review_artists import _deserialize_state
        from spotify_manager.routines.review_artists import _state_access

        access = _state_access(self.paths, self.state_service)
        state = _deserialize_state(access.load())
        state.checkpoint = ReviewCheckpoint(access)
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

    def cache_for(self, artist: YourLibraryArtist) -> CatalogCache:
        """Resolve an artist-specific view of the invocation metadata.

        Args:
            artist: Reviewed artist.

        Returns:
            Durable artist cache view.
        """
        return LegacyCatalogCache(
            artist.spotify_id,
            artist.name,
            self.cache,
            ReviewMetadata(self.paths.cache, self.cache),
        )

    def reads_for(self, artist: YourLibraryArtist) -> CatalogReads:
        """Resolve artist-specific transport observations.

        Args:
            artist: Reviewed artist.

        Returns:
            Named catalog reads using the invocation retry policy.
        """
        return SpotifyArtistReads(self.spotify, artist, self.retry)


@dataclass(frozen=True)
class ReviewCheckpoint:
    """Persist typed review progress through its original namespace.

    Args:
        access: Caller-selected durable state authority.
    """

    access: RoutineState

    def save(self, state: ArtistReviewState) -> None:
        """Serialize and accept complete progress.

        Args:
            state: Current review model.
        """
        from spotify_manager.routines.review_artists import _serialize_state

        self.access.save(_serialize_state(state))


@dataclass(frozen=True)
class ReviewMetadata:
    """Own complete cache publication without a bound persistence callback.

    Args:
        path: Metadata destination.
        data: Shared mutable invocation cache.
    """

    path: Path
    data: dict[str, dict[str, object]]

    def save(self) -> None:
        """Accept the current complete cache."""
        from spotify_manager.routines.review_artists import save_cache

        save_cache(self.path, self.data)


@dataclass(frozen=True)
class SpotifyArtistReads:
    """Read one artist's catalog with a caller-owned transport retry policy.

    Args:
        spotify: Caller-owned synchronous client.
        artist: Reviewed artist.
        retry: Transport retry policy.
    """

    spotify: Spotify
    artist: YourLibraryArtist
    retry: RetryCall

    def read_tracks(self) -> list[TrackCandidate]:
        """Read complete ranked track facts.

        Returns:
            Parsed associated candidates.
        """
        from spotify_manager.routines.review_artists import _read_tracks

        return _read_tracks(self.spotify, self.artist, self.retry)

    def read_search(self, offset: int) -> ReleasePage:
        """Read a ranked release page.

        Args:
            offset: Raw row offset.

        Returns:
            Parsed candidates and pagination authority.
        """
        from spotify_manager.routines.review_artists import _read_ranked_page

        return _read_ranked_page(self.spotify, self.artist, self.retry, offset)

    def read_discography(self, offset: int) -> RawReleasePage:
        """Read an unbounded catalog scan page.

        Args:
            offset: Raw row offset.

        Returns:
            Complete raw rows and pagination authority.
        """
        from spotify_manager.routines.review_artists import _read_discography_page

        return _read_discography_page(self.spotify, self.artist, self.retry, offset)

    def read_first(self, release: ReleaseCandidate) -> FirstTrack | None:
        """Read the first playable track with original 404 handling.

        Args:
            release: Selected release.

        Returns:
            First-track metadata, or none.
        """
        from spotify_manager.routines.review_artists import _read_first

        return _read_first(self.spotify, self.retry, release)


@dataclass(frozen=True)
class SpotifyMembershipPages:
    """Read complete raw queue pages without concealing a membership use case.

    Args:
        spotify: Caller-owned synchronous client.
        playlist: Queue identity.
        retry: Transport retry policy.
    """

    spotify: Spotify
    playlist: str
    retry: RetryCall

    def read_membership(self, offset: int) -> MembershipPage:
        """Read one queue page.

        Args:
            offset: Raw row offset.

        Returns:
            Parsed markers and raw pagination authority.
        """
        from spotify_manager.routines.review_artists import _read_membership_page

        return _read_membership_page(self.spotify, self.playlist, self.retry, offset)


@dataclass(frozen=True)
class ReviewSpotifyAccess:
    """Read queue pages and accept artist-review Spotify effects.

    Args:
        spotify: Caller-owned synchronous client.
        retry: Original transport retry policy.
    """

    spotify: Spotify
    retry: RetryCall

    def pages(self, identity: str) -> MembershipPages:
        """Select a queue page reader.

        Args:
            identity: Queue identity.

        Returns:
            Named transport page reader.
        """
        return SpotifyMembershipPages(self.spotify, identity, self.retry)

    def append(self, identity: str, uri: str, description: str) -> object:
        """Accept one marker addition through the original retry boundary.

        Args:
            identity: Destination queue.
            uri: Selected marker.
            description: Visible retry label.

        Returns:
            Original accepted response.
        """
        from spotify_manager.routines.review_artists import add_playlist_item

        return self.retry(
            partial(add_playlist_item, self.spotify, identity, uri), description
        )

    def remove(self, identity: str, uris: list[str], description: str) -> object:
        """Accept one ordered removal batch through the original retry boundary.

        Args:
            identity: Source queue.
            uris: Complete ordered removal batch.
            description: Visible retry label.

        Returns:
            Original accepted response.
        """
        from spotify_manager.routines.review_artists import remove_playlist_items

        return self.retry(
            partial(remove_playlist_items, self.spotify, identity, uris), description
        )

    def unfollow(self, uris: list[str], description: str) -> object:
        """Accept an artist unfollow batch through the original retry boundary.

        Args:
            uris: Complete ordered artist batch.
            description: Visible retry label.

        Returns:
            Original accepted response.
        """
        from spotify_manager.routines.review_artists import remove_library_artists

        return self.retry(
            partial(remove_library_artists, self.spotify, uris), description
        )


@dataclass(frozen=True)
class ReviewFiles:
    """Own ordered review file operations and the invocation metadata cache.

    Args:
        resources: Caller-owned paths, state authority and metadata lifetime.
    """

    resources: ReviewResources

    def artists(self) -> list[YourLibraryArtist]:
        """Complete current followed-artist mirror.

        Returns:
            Original boundary result.
        """
        from spotify_manager.routines.review_artists import load_models

        return load_models(self.resources.paths.artists, YourLibraryArtist)

    def tracks(self) -> list[YourLibraryTrack]:
        """Complete current liked-track mirror.

        Returns:
            Original boundary result.
        """
        from spotify_manager.routines.review_artists import load_models

        return load_models(self.resources.paths.liked_tracks, YourLibraryTrack)

    def state(self) -> ArtistReviewState:
        """Load original progress and attach its named checkpoint store.

        Returns:
            Original boundary result.
        """
        return self.resources.state()

    def cache(self, refresh: bool) -> None:
        """Initialize original metadata cache for subsequent catalog reads.

        Args:
            refresh: Original refresh.
        """
        return self.resources.initialize_cache(refresh)

    def run_id(self) -> str:
        """Create the original sortable invocation identity.

        Returns:
            Original boundary result.
        """
        from spotify_manager.routines.review_artists import new_run_id

        return new_run_id()

    def event(self, run_id: str, name: str, **details: object) -> dict[str, object]:
        """Observe the event clock and encode complete audit facts.

        Args:
            run_id: Invocation identity.
            name: Event classification.
            details: Complete decision facts.

        Returns:
            Timestamped audit record.
        """
        from spotify_manager.routines.review_artists import event

        return event(run_id, name, **details)

    def append(self, events: list[dict[str, object]]) -> None:
        """Append original ordered audit records.

        Args:
            events: Original events.
        """
        from spotify_manager.routines.review_artists import append_events

        return append_events(self.resources.paths.log, events)

    def save_artists(self, artists: list[YourLibraryArtist]) -> None:
        """Publish original remaining followed artists.

        Args:
            artists: Original artists.
        """
        from spotify_manager.routines.review_artists import save_artists

        return save_artists(self.resources.paths.artists, artists)

    def stats(self, total: int, removed: int) -> None:
        """Publish original post-unfollow statistics.

        Args:
            total: Original total.
            removed: Original removed.
        """
        from spotify_manager.routines.review_artists import update_stats_after_unfollow

        return update_stats_after_unfollow(
            self.resources.paths.stats_history, total, removed
        )


@dataclass(frozen=True)
class ReviewAuditFile:
    """Append audit decisions for retained public completion helpers.

    Args:
        path: Original explicit audit destination.
    """

    path: Path

    def append(self, events: list[dict[str, object]]) -> None:
        """Accept ordered complete records.

        Args:
            events: Original complete audit records.
        """
        from spotify_manager.routines.review_artists import append_events

        append_events(self.path, events)
