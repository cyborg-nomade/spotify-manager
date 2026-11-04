"""Resolve historical releases through explicit album choices."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.manual_matching import ManualAlbumCandidate


class ManualAlbumCatalog(Protocol):
    """Read unfiltered album candidates for an unresolved historical reference."""

    async def search(self, scrobble: Scrobble) -> tuple[ManualAlbumCandidate, ...]:
        """Search release text, or albums associated with a historical track.

        Args:
            scrobble: Available artist, track and album text.

        Returns:
            Up to ten albums in original search order.
        """
        ...


class AlbumMatchInteraction(Protocol):
    """Present album candidates and accept an explicit match or rejection."""

    async def choose_album_match(
        self, scrobble: Scrobble, candidates: tuple[ManualAlbumCandidate, ...]
    ) -> str:
        """Choose an offered album or reject all results, raising on cancellation.

        Args:
            scrobble: Original historical reference.
            candidates: Search-ordered album observations, possibly empty.

        Returns:
            Selected album ID, or an empty string for no match.
        """
        ...


@dataclass(frozen=True)
class ManualAlbumMatching:
    """Validate operator choices without applying automatic similarity gates.

    Args:
        catalog: Broad album search resource.
        interaction: Operator choice owner.
        cancellation: Invocation cancellation boundary.
    """

    catalog: ManualAlbumCatalog
    interaction: AlbumMatchInteraction
    cancellation: Cancellation

    async def run(self, scrobble: Scrobble) -> ManualAlbumCandidate | None:
        """Resolve one album reference or explicitly leave it unmatched.

        Args:
            scrobble: Historical reference whose automatic lookup failed.

        Returns:
            Selected album or none when rejected.

        Raises:
            SpotifyTrackResolutionError: A choice is outside the offered results.
            RuntimeError: Invocation cancellation is requested.
        """
        self.cancellation.check()
        candidates = await self.catalog.search(scrobble)
        self.cancellation.check()
        selected = await self.interaction.choose_album_match(scrobble, candidates)
        self.cancellation.check()
        if not selected:
            return None
        for candidate in candidates:
            if candidate.spotify_id == selected:
                return candidate
        raise SpotifyTrackResolutionError("The selected Spotify album is not offered.")
