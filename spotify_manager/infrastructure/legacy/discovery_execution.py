"""Discovery execution bindings for existing playlist, follow and state helpers."""

from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack


@dataclass(frozen=True)
class LegacyDiscoveryEffects:
    """Bind review execution to caller-owned integrations.

    Args:
        client: Existing synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        artists_path: Canonical artist mirror.
    """

    client: Spotify
    retry: RetryCall
    artists_path: Path

    async def append(
        self, playlist_id: str, track: CatalogTrack, description: str
    ) -> None:
        """Append a marker using its original retry description.

        Args:
            playlist_id: Destination identifier.
            track: Accepted marker.
            description: Original retry message.
        """
        from spotify_manager.routines.new_kids import _append_review_track

        await _append_review_track(
            self.client, playlist_id, track, description, self.retry
        )

    async def remove(self, playlist_id: str, source: PlaylistTrack, label: str) -> None:
        """Remove the original source at its accepted retry boundary.

        Args:
            playlist_id: Review playlist identifier.
            source: Original snapshotted marker.
            label: Original review playlist display label.
        """
        from spotify_manager.routines.new_kids import _remove_review_track

        await _remove_review_track(self.client, playlist_id, source, label, self.retry)

    async def membership(self, playlist_id: str) -> tuple[set[str], set[str]]:
        """Read destination memberships through the original live playlist loader.

        Args:
            playlist_id: Destination identifier.

        Returns:
            Original primary artist and playable track identifier sets.
        """
        from spotify_manager.routines.new_kids import _playlist_artist_ids

        return await _playlist_artist_ids(self.client, playlist_id, self.retry)

    async def followed(self, artist_id: str, artist_name: str) -> bool:
        """Observe the original tolerant follow status.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.

        Returns:
            First truthy status, otherwise false.
        """
        from spotify_manager.routines.new_kids import _artist_followed

        return await _artist_followed(self.client, artist_id, artist_name, self.retry)

    async def unfollow(self, artist_id: str, artist_name: str) -> None:
        """Unfollow an artist remotely before mirror removal.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.
        """
        from spotify_manager.routines.new_kids import _unfollow_artist

        await _unfollow_artist(self.client, artist_id, artist_name, self.retry)

    async def remove_local_artist(self, artist_id: str) -> None:
        """Remove the unfollowed artist from the existing canonical mirror.

        Args:
            artist_id: Logical artist identifier.
        """
        from spotify_manager.routines.new_kids import (
            async_remove_local_artist as remove_local_artist,
        )

        await remove_local_artist(artist_id, self.artists_path)


@dataclass(frozen=True)
class LegacyDiscoveryCreation:
    """Bind original Spotify identity and playlist creation observations.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
    """

    client: Spotify
    retry: RetryCall

    async def current_user(self) -> str:
        """Read the original profile ID using tolerant response parsing.

        Returns:
            Observed profile identifier, or an empty string.
        """
        from spotify_manager.routines.new_kids import _current_user_id

        return await _current_user_id(self.client, self.retry)

    async def create(self, user_id: str, year: int) -> str:
        """Create the original private yearly playlist.

        Args:
            user_id: Accepted profile identifier.
            year: Original review year for name and description.

        Returns:
            Created identifier, or an empty string for an invalid response.
        """
        from spotify_manager.routines.new_kids import _create_great_playlist

        return await _create_great_playlist(self.client, user_id, year, self.retry)


@dataclass(frozen=True)
class LegacyDiscoveryQueue:
    """Bind queue transfers to original playlist observation and mutation helpers.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
    """

    client: Spotify
    retry: RetryCall

    async def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe playable queue markers in their original order.

        Args:
            playlist_id: Queue source identifier.

        Returns:
            Original markers, retaining duplicates.
        """
        from spotify_manager.routines.new_wine import (
            async_load_playlist_tracks as load_playlist_tracks,
        )

        return await load_playlist_tracks(self.client, playlist_id, self.retry)

    async def append(
        self, playlist_id: str, source: PlaylistTrack, description: str
    ) -> None:
        """Secure a queue marker through the original append helper.

        Args:
            playlist_id: Destination identifier.
            source: Original queue marker.
            description: Original retry message.
        """
        from spotify_manager.routines.new_kids import _append_queue_track

        await _append_queue_track(
            self.client, playlist_id, source, description, self.retry
        )

    async def remove(
        self, playlist_id: str, source: PlaylistTrack, description: str
    ) -> None:
        """Remove a moved or reconciled marker through the original helper.

        Args:
            playlist_id: Queue source identifier.
            source: Original queue marker.
            description: Original retry message.
        """
        from spotify_manager.routines.new_kids import _remove_queue_track

        await _remove_queue_track(
            self.client, playlist_id, source, description, self.retry
        )
