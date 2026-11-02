"""Explicit synchronous boundaries used by followed-artist review."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.artist_review_catalog import ArtistCatalog
from spotify_manager.application.artist_review_catalog import CatalogCache
from spotify_manager.application.artist_review_catalog import CatalogReads
from spotify_manager.application.artist_review_membership import MembershipPages
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import ReviewProgress
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


class ReviewStorage(Protocol):
    """Bind ordered local reads, accepted progress and durable publications."""

    async def artists(self) -> list[YourLibraryArtist]:
        """Complete current followed-artist mirror.

        Returns:
            Original boundary result.
        """
        ...

    async def tracks(self) -> list[YourLibraryTrack]:
        """Complete current liked-track mirror.

        Returns:
            Original boundary result.
        """
        ...

    async def state(self) -> ArtistReviewState:
        """Load original progress and attach its named checkpoint store.

        Returns:
            Original boundary result.
        """
        ...

    async def cache(self, refresh: bool) -> None:
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

    async def append(self, events: list[dict[str, object]]) -> None:
        """Append original ordered audit records.

        Args:
            events: Original events.
        """
        ...

    async def save_artists(self, artists: list[YourLibraryArtist]) -> None:
        """Publish original remaining followed artists.

        Args:
            artists: Original artists.
        """
        ...

    async def stats(self, total: int, removed: int) -> None:
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

    async def tracks(self, artist: YourLibraryArtist) -> list[TrackCandidate]:
        """Gather ranked associated tracks through the named catalog stage.

        Args:
            artist: Reviewed artist.

        Returns:
            Complete candidates.
        """
        return await self._artist(artist).ranked_tracks()

    async def ranked(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Gather ranked releases through the named catalog stage.

        Args:
            artist: Reviewed artist.

        Returns:
            Complete enriched releases.
        """
        return await self._artist(artist).ranked_releases()

    async def earliest(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Gather chronological releases through the named catalog stage.

        Args:
            artist: Reviewed artist.

        Returns:
            Complete enriched releases.
        """
        return await self._artist(artist).earliest_releases()

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

    async def append(self, identity: str, uri: str, description: str) -> object:
        """Original single-marker addition.

        Args:
            identity: Original identity.
            uri: Original uri.
            description: Original description.

        Returns:
            Original boundary result.
        """
        ...

    async def remove(self, identity: str, uris: list[str], description: str) -> object:
        """Original requested marker removal, retaining batch order.

        Args:
            identity: Original identity.
            uris: Original uris.
            description: Original description.

        Returns:
            Original boundary result.
        """
        ...

    async def unfollow(self, uris: list[str], description: str) -> object:
        """Original forty-artist mutation boundary.

        Args:
            uris: Original uris.
            description: Original description.

        Returns:
            Original boundary result.
        """
        ...


class TrackChoices(Protocol):
    """Read an operator's tied-track selection."""

    async def choose_track(
        self, artist: YourLibraryArtist, candidates: tuple[TrackCandidate, ...], /
    ) -> str:
        """Choose a track or return the original control response.

        Args:
            artist: Artist being reviewed.
            candidates: Ordered tied candidates.

        Returns:
            Original selected identity or control response.
        """
        ...


class ReleaseChoices(Protocol):
    """Read an operator's release selection."""

    async def choose_release(
        self,
        artist: YourLibraryArtist,
        candidates: tuple[ReleaseCandidate, ...],
        allow_decline: bool,
        /,
    ) -> str:
        """Choose a release or return the original control response.

        Args:
            artist: Artist being reviewed.
            candidates: Ordered release candidates.
            allow_decline: Whether declining is allowed at this stage.

        Returns:
            Original selected identity or control response.
        """
        ...


@dataclass(frozen=True)
class ReviewInteraction:
    """Bind original visible output and optional interactive decisions.

    Args:
        output: Original visible progress and action messages.
        progress: Original optional position/total progress resource.
        track: Original optional tied-track prompt.
        release: Original optional release prompt with decline availability.
    """

    output: Messages
    progress: ReviewProgress | None
    track: TrackChoices | None
    release: ReleaseChoices | None
