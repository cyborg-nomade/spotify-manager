"""Discovery execution bindings for existing playlist, follow and state helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.routines import new_kids


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
        new_kids._append_review_track(
            self.client, playlist_id, track, description, self.retry
        )

    def remove(self, playlist_id: str, source: PlaylistTrack, label: str) -> None:
        """Remove the original source at its accepted retry boundary.

        Args:
            playlist_id: Review playlist identifier.
            source: Original snapshotted marker.
            label: Original review playlist display label.
        """
        new_kids._remove_review_track(
            self.client, playlist_id, source, label, self.retry
        )

    def membership(self, playlist_id: str) -> tuple[set[str], set[str]]:
        """Read destination memberships through the original live playlist loader.

        Args:
            playlist_id: Destination identifier.

        Returns:
            Original primary artist and playable track identifier sets.
        """
        return new_kids._playlist_artist_ids(self.client, playlist_id, self.retry)

    def great_playlist(self, state: dict[str, object], dry_run: bool) -> str | None:
        """Use the existing destination creation and checkpoint integration.

        Args:
            state: Mutable complete namespace.
            dry_run: Whether to preview creation.

        Returns:
            Original destination identifier, or None for previewed creation.
        """
        return new_kids._great_discoveries_playlist(
            self.client,
            state,
            self.year,
            self.great_seed,
            dry_run=dry_run,
            retry_call=self.retry,
            state_access=self.state_access,
            echo=self.echo,
        )

    def followed(self, artist_id: str, artist_name: str) -> bool:
        """Observe the original tolerant follow status.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.

        Returns:
            First truthy status, otherwise false.
        """
        return new_kids._artist_followed(
            self.client, artist_id, artist_name, self.retry
        )

    def unfollow(self, artist_id: str, artist_name: str) -> None:
        """Unfollow an artist remotely before mirror removal.

        Args:
            artist_id: Logical artist identifier.
            artist_name: Original retry display name.
        """
        new_kids._unfollow_artist(self.client, artist_id, artist_name, self.retry)

    def remove_local_artist(self, artist_id: str) -> None:
        """Remove the unfollowed artist from the existing canonical mirror.

        Args:
            artist_id: Logical artist identifier.
        """
        new_kids.remove_local_artist(artist_id, self.artists_path)
