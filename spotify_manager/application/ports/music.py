"""Narrow synchronous catalog, library membership, and playlist contracts."""

from typing import Protocol

from spotify_manager.application.music import Album
from spotify_manager.application.music import NamedTrack
from spotify_manager.application.music import Track


class AlbumCatalog(Protocol):
    """Resolve albums and retrieve their ordered, freshly parsed tracks."""

    def resolve_album(
        self, *, name: str | None, album_id: str | None, artist: str | None
    ) -> Album:
        """Resolve a reference using the established matching rules.

        Args:
            name: Exact display name, when no identifier is provided.
            album_id: Direct identifier, taking priority over the name.
            artist: Optional primary-artist disambiguation.

        Returns:
            The uniquely resolved album.

        Raises:
            LookupError: No unique album matches.
            ValueError: Both name and identifier are missing.
        """

    def album_tracks(self, album_id: str) -> tuple[Track, ...]:
        """Read all pages in order, preserving duplicates and missing identifiers.

        Args:
            album_id: Resolved catalog identifier.

        Returns:
            The current track listing.
        """


class TrackMembership(Protocol):
    """Read current Liked Songs membership without cross-call caching."""

    def liked_tracks(self, track_ids: tuple[str, ...]) -> dict[str, bool]:
        """Read statuses with the caller's order and duplicate requests intact.

        Args:
            track_ids: Identifiers observed in the current track list.

        Returns:
            Status by identifier, with the last duplicate observation prevailing.
        """


class PlaylistAccess(Protocol):
    """Read markers and perform one explicitly ordered Requeue effect at a time."""

    def tracks(self, playlist_id: str) -> tuple[Track, ...]:
        """Read playable markers through the existing pagination and parser.

        Args:
            playlist_id: Playlist identifier.

        Returns:
            Parsed tracks in playlist order, including duplicates.
        """

    def append(self, playlist_id: str, track: NamedTrack) -> None:
        """Append one replacement using the established Requeue retry profile.

        Args:
            playlist_id: Destination playlist.
            track: Replacement marker and its retry-message title.
        """

    def remove(self, playlist_id: str, track: NamedTrack) -> None:
        """Remove a source marker using the established Requeue retry profile.

        Args:
            playlist_id: Source playlist.
            track: Marker to remove and its retry-message title.
        """
