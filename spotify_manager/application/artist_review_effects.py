"""Explicit synchronous boundaries used by followed-artist review."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.artist_review_catalog import ArtistCatalog
from spotify_manager.application.artist_review_catalog import CatalogCache
from spotify_manager.application.artist_review_catalog import CatalogReads
from spotify_manager.application.artist_review_membership import MembershipPages
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


class ReviewStorage(Protocol):
    """Bind ordered local reads, accepted progress and durable publications."""

    def artists(self) -> list[YourLibraryArtist]:
        """Complete current followed-artist mirror.

        Returns:
            Original boundary result.
        """
        ...

    def tracks(self) -> list[YourLibraryTrack]:
        """Complete current liked-track mirror.

        Returns:
            Original boundary result.
        """
        ...

    def state(self) -> ArtistReviewState:
        """Load original progress and attach its named checkpoint store.

        Returns:
            Original boundary result.
        """
        ...

    def cache(self, refresh: bool) -> None:
        """Initialize original metadata cache for subsequent catalog reads.

        Args:
            refresh: Original refresh.
        """
        ...

    def run_id(self) -> str:
        """Create the original sortable invocation identity.

        Returns:
            Original boundary result.
        """
        ...

    def event(self, run_id: str, name: str, **details: object) -> dict[str, object]:
        """Observe the event clock and encode complete audit facts.

        Args:
            run_id: Invocation identity.
            name: Event classification.
            details: Complete decision facts.

        Returns:
            Timestamped audit record.
        """
        ...

    def append(self, events: list[dict[str, object]]) -> None:
        """Append original ordered audit records.

        Args:
            events: Original events.
        """
        ...

    def save_artists(self, artists: list[YourLibraryArtist]) -> None:
        """Publish original remaining followed artists.

        Args:
            artists: Original artists.
        """
        ...

    def stats(self, total: int, removed: int) -> None:
        """Publish original post-unfollow statistics.

        Args:
            total: Original total.
            removed: Original removed.
        """
        ...


class CatalogSources(Protocol):
    """Supply artist-specific external cache and transport resources."""

    def cache_for(self, artist: YourLibraryArtist) -> CatalogCache:
        """Resolve the artist's cache view.

        Args:
            artist: Reviewed artist.

        Returns:
            Artist-specific durable metadata.
        """
        ...

    def reads_for(self, artist: YourLibraryArtist) -> CatalogReads:
        """Resolve artist-specific transport observations.

        Args:
            artist: Reviewed artist.

        Returns:
            Named read methods.
        """
        ...


@dataclass(frozen=True)
class ReviewCatalog:
    """Call named catalog stages directly from review execution.

    Args:
        sources: Shared cache and caller-owned catalog resources.
    """

    sources: CatalogSources

    def tracks(self, artist: YourLibraryArtist) -> list[TrackCandidate]:
        """Gather ranked associated tracks through the named catalog stage.

        Args:
            artist: Reviewed artist.

        Returns:
            Complete candidates.
        """
        return self._artist(artist).ranked_tracks()

    def ranked(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Gather ranked releases through the named catalog stage.

        Args:
            artist: Reviewed artist.

        Returns:
            Complete enriched releases.
        """
        return self._artist(artist).ranked_releases()

    def earliest(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Gather chronological releases through the named catalog stage.

        Args:
            artist: Reviewed artist.

        Returns:
            Complete enriched releases.
        """
        return self._artist(artist).earliest_releases()

    def _artist(self, artist: YourLibraryArtist) -> ArtistCatalog:
        return ArtistCatalog(
            self.sources.cache_for(artist), self.sources.reads_for(artist)
        )


class ReviewSpotify(Protocol):
    """Bind original retried Spotify reads and ordered writes."""

    def pages(self, identity: str) -> MembershipPages:
        """Complete fresh primary-credit membership for one queue.

        Args:
            identity: Original identity.

        Returns:
            Original boundary result.
        """
        ...

    def append(self, identity: str, uri: str, description: str) -> object:
        """Original single-marker addition.

        Args:
            identity: Original identity.
            uri: Original uri.
            description: Original description.

        Returns:
            Original boundary result.
        """
        ...

    def remove(self, identity: str, uris: list[str], description: str) -> object:
        """Original requested marker removal, retaining batch order.

        Args:
            identity: Original identity.
            uris: Original uris.
            description: Original description.

        Returns:
            Original boundary result.
        """
        ...

    def unfollow(self, uris: list[str], description: str) -> object:
        """Original forty-artist mutation boundary.

        Args:
            uris: Original uris.
            description: Original description.

        Returns:
            Original boundary result.
        """
        ...


@dataclass(frozen=True)
class ReviewInteraction:
    """Bind original visible output and optional interactive decisions.

    Args:
        echo: Original visible progress and action messages.
        progress: Original optional position/total callback.
        track: Original optional tied-track prompt.
        release: Original optional release prompt with decline availability.
    """

    echo: Callable[[str], None]
    progress: Callable[[int, int, str], None] | None
    track: Callable[[YourLibraryArtist, tuple[TrackCandidate, ...]], str] | None
    release: (
        Callable[[YourLibraryArtist, tuple[ReleaseCandidate, ...], bool], str] | None
    )
