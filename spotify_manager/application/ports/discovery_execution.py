"""Playlist and follow effects used by discovery review execution."""

from typing import Protocol

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack


class DiscoveryEffects(Protocol):
    """Perform one accepted effect using the caller's existing retry boundary."""

    def append(self, playlist_id: str, track: CatalogTrack, description: str) -> None:
        """Append a chosen marker.

        Args:
            playlist_id: Destination identifier.
            track: Accepted destination marker.
            description: Original retry description.
        """

    def remove(self, playlist_id: str, source: PlaylistTrack, label: str) -> None:
        """Remove the original marker after securing destinations.

        Args:
            playlist_id: Review playlist identifier.
            source: Original review marker.
            label: Original review playlist display label.
        """

    def membership(self, playlist_id: str) -> tuple[set[str], set[str]]:
        """Observe destination artist and track memberships.

        Args:
            playlist_id: Destination identifier.

        Returns:
            Mutable artist and track identifier sets from live markers.
        """

    def great_playlist(self, state: dict[str, object], dry_run: bool) -> str | None:
        """Resolve the current-year destination using existing creation/checkpoints.

        Args:
            state: Mutable complete review namespace.
            dry_run: Whether creation is previewed.

        Returns:
            Accepted playlist identifier or None for a preview of creation.
        """

    def followed(self, artist_id: str, artist_name: str) -> bool:
        """Read the original tolerant artist-follow response.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.

        Returns:
            First truthy status, otherwise false.
        """

    def unfollow(self, artist_id: str, artist_name: str) -> None:
        """Unfollow an artist remotely.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.
        """

    def remove_local_artist(self, artist_id: str) -> None:
        """Remove a successfully unfollowed artist from the canonical mirror.

        Args:
            artist_id: Logical artist identifier.
        """


class DiscoveryExecutionPresentation(Protocol):
    """Render accepted playlist and follow effects at their original boundaries."""

    def marker_added(self, name: str, dry_run: bool) -> None:
        """Show a secured replacement marker.

        Args:
            name: Replacement track name.
            dry_run: Whether to use preview wording.
        """

    def marker_removed(self, name: str, dry_run: bool) -> None:
        """Show removal of an existing source marker.

        Args:
            name: Original track name.
            dry_run: Whether to use preview wording.
        """

    def artist_added(self, name: str, label: str, dry_run: bool) -> None:
        """Show an artist added to an existing destination.

        Args:
            name: Logical artist display name.
            label: Destination display label.
            dry_run: Whether to use preview wording.
        """

    def future_artist_added(self, name: str, label: str, track: str) -> None:
        """Preview promotion to a destination that would first need creation.

        Args:
            name: Logical artist display name.
            label: Future destination display label.
            track: Chosen promotion marker name.
        """

    def artist_unfollowed(self, name: str, dry_run: bool) -> None:
        """Show unfollowing only when the artist was previously followed.

        Args:
            name: Logical artist display name.
            dry_run: Whether to use preview wording.
        """
