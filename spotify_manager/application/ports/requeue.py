"""Integration contracts for the complete Requeue transition."""

from typing import Protocol

from spotify_manager.application.music import NamedTrack
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


class RequeuePlaylists(Protocol):
    """Read complete source markers and execute individual playlist effects."""

    def sources(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read current playable markers with their artist and release facts.

        Args:
            playlist_id: Playlist to read, including the final freshness check.

        Returns:
            Ordered source markers, preserving duplicates.

        Raises:
            RequeueForADreamError: Parsing the source playlist fails.
        """

    def append(self, playlist_id: str, track: NamedTrack) -> None:
        """Append a replacement through the supplied retry policy.

        Args:
            playlist_id: Destination playlist.
            track: Replacement URI and display title.
        """

    def remove(self, playlist_id: str, track: NamedTrack) -> None:
        """Remove the old marker after its replacement is secure.

        Args:
            playlist_id: Source playlist.
            track: Original marker URI and display title.
        """


class RequeueCatalog(Protocol):
    """Read the selected studio discography and ordered release tracks."""

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read eligible editions with current saved-status observations.

        Args:
            artist_id: Source marker's primary artist.

        Returns:
            Selected studio albums and EPs in legacy chronological order.

        Raises:
            RequeueForADreamError: Catalog parsing fails.
        """

    def release_tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read playable tracks in the original disc and track order.

        Args:
            release: Selected successor edition.

        Returns:
            Ordered tracks, possibly empty.

        Raises:
            RequeueForADreamError: Track parsing fails.
        """
