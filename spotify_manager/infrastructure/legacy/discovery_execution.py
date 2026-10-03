"""Discovery execution bindings for existing playlist, follow and state helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack


@dataclass(frozen=True)
class LegacyDiscoveryEffects:
    """Bind review execution to caller-owned integrations.

    Args:
        client: Existing synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        state_access: Existing namespace checkpoint boundary.
        artists_path: Canonical artist mirror.
        year: Original invocation year.
        great_seed: Configured 2026 Great Discoveries playlist.
        echo: Existing output sink for destination creation.
    """

    client: Spotify
    retry: RetryCall
    state_access: RoutineState
    artists_path: Path
    year: int
    great_seed: str
    echo: Callable[[str], None]

    def append(self, playlist_id: str, track: CatalogTrack, description: str) -> None:
        """Append a marker using its original retry description.

        Args:
            playlist_id: Destination identifier.
            track: Accepted marker.
            description: Original retry message.
        """
        from spotify_manager.routines.new_kids import _append_review_track

        _append_review_track(self.client, playlist_id, track, description, self.retry)

    def remove(self, playlist_id: str, source: PlaylistTrack, label: str) -> None:
        """Remove the original source at its accepted retry boundary.

        Args:
            playlist_id: Review playlist identifier.
            source: Original snapshotted marker.
            label: Original review playlist display label.
        """
        from spotify_manager.routines.new_kids import _remove_review_track

        _remove_review_track(self.client, playlist_id, source, label, self.retry)

    def membership(self, playlist_id: str) -> tuple[set[str], set[str]]:
        """Read destination memberships through the original live playlist loader.

        Args:
            playlist_id: Destination identifier.

        Returns:
            Original primary artist and playable track identifier sets.
        """
        from spotify_manager.routines.new_kids import _playlist_artist_ids

        return _playlist_artist_ids(self.client, playlist_id, self.retry)

    def great_playlist(self, state: dict[str, object], dry_run: bool) -> str | None:
        """Use the existing destination creation and checkpoint integration.

        Args:
            state: Mutable complete namespace.
            dry_run: Whether to preview creation.

        Returns:
            Original destination identifier, or None for previewed creation.
        """
        from spotify_manager.bootstrap.new_kids import great_discoveries

        service = great_discoveries(
            self.client, self.retry, self.state_access, self.echo
        )
        return service.resolve(state, self.year, self.great_seed, dry_run)

    def followed(self, artist_id: str, artist_name: str) -> bool:
        """Observe the original tolerant follow status.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.

        Returns:
            First truthy status, otherwise false.
        """
        from spotify_manager.routines.new_kids import _artist_followed

        return _artist_followed(self.client, artist_id, artist_name, self.retry)

    def unfollow(self, artist_id: str, artist_name: str) -> None:
        """Unfollow an artist remotely before mirror removal.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.
        """
        from spotify_manager.routines.new_kids import _unfollow_artist

        _unfollow_artist(self.client, artist_id, artist_name, self.retry)

    def remove_local_artist(self, artist_id: str) -> None:
        """Remove the unfollowed artist from the existing canonical mirror.

        Args:
            artist_id: Logical artist identifier.
        """
        from spotify_manager.routines.new_kids import remove_local_artist

        remove_local_artist(artist_id, self.artists_path)


@dataclass(frozen=True)
class LegacyDiscoveryCreation:
    """Bind original Spotify identity and playlist creation observations.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
    """

    client: Spotify
    retry: RetryCall

    def current_user(self) -> str:
        """Read the original profile ID using tolerant response parsing.

        Returns:
            Observed profile identifier, or an empty string.
        """
        from spotify_manager.routines.new_kids import _current_user_id

        return _current_user_id(self.client, self.retry)

    def create(self, user_id: str, year: int) -> str:
        """Create the original private yearly playlist.

        Args:
            user_id: Accepted profile identifier.
            year: Original review year for name and description.

        Returns:
            Created identifier, or an empty string for an invalid response.
        """
        from spotify_manager.routines.new_kids import _create_great_playlist

        return _create_great_playlist(self.client, user_id, year, self.retry)


@dataclass(frozen=True)
class LegacyDiscoveryQueue:
    """Bind queue transfers to original playlist observation and mutation helpers.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
    """

    client: Spotify
    retry: RetryCall

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe playable queue markers in their original order.

        Args:
            playlist_id: Queue source identifier.

        Returns:
            Original markers, retaining duplicates.
        """
        from spotify_manager.routines.new_wine import load_playlist_tracks

        return load_playlist_tracks(self.client, playlist_id, self.retry)

    def append(self, playlist_id: str, source: PlaylistTrack, description: str) -> None:
        """Secure a queue marker through the original append helper.

        Args:
            playlist_id: Destination identifier.
            source: Original queue marker.
            description: Original retry message.
        """
        from spotify_manager.routines.new_kids import _append_queue_track

        _append_queue_track(self.client, playlist_id, source, description, self.retry)

    def remove(self, playlist_id: str, source: PlaylistTrack, description: str) -> None:
        """Remove a moved or reconciled marker through the original helper.

        Args:
            playlist_id: Queue source identifier.
            source: Original queue marker.
            description: Original retry message.
        """
        from spotify_manager.routines.new_kids import _remove_queue_track

        _remove_queue_track(self.client, playlist_id, source, description, self.retry)
