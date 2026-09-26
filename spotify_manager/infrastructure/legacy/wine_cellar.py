"""Existing Spotify, mirror and persistence boundaries for Wine Cellar refill."""

from dataclasses import dataclass
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.new_wine_values import CellarRefillResult
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.wine_cellar import Inventory
from spotify_manager.application.wine_cellar import LibraryCounts
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.routines import new_wine as legacy


@dataclass(frozen=True)
class WineCellarAccess:
    """Retain the original client, mirrors, namespace and audit destination.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation policy.
        state_access: Already-resolved namespace adapter.
        log_path: Original audit destination.
        liked_path: Canonical liked-track mirror.
        albums_path: Canonical saved-album mirror.
    """

    client: Spotify
    retry: RetryCall
    state_access: RoutineState
    log_path: Path
    liked_path: Path
    albums_path: Path

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read the original ordered playlist observations.

        Args:
            playlist_id: Source or destination identifier.

        Returns:
            Parsed playable markers.
        """
        return legacy.load_playlist_tracks(self.client, playlist_id, self.retry)

    def inventory(self) -> Inventory:
        """Read candidate IDs from the existing canonical mirrors.

        Returns:
            Liked-track and saved-album maps keyed by normalized artist name.
        """
        return legacy._load_no_discovery_inventory(self.liked_path, self.albums_path)

    def counts(self, artist: str, inventory: Inventory) -> LibraryCounts:
        """Read live membership under the original early-stop policy.

        Args:
            artist: Source primary artist name.
            inventory: Mirror candidate IDs.

        Returns:
            Liked count, saved-album count and eligibility.
        """
        tracks, albums = inventory
        return legacy._live_no_discovery_counts(
            self.client, artist, tracks, albums, self.retry
        )

    def append(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Append the cellar marker to New Wine.

        Args:
            playlist_id: Destination playlist.
            source: Original cellar marker.
        """
        track = ReleaseTrack(source.spotify_id, source.uri, source.name, 1, 1)
        legacy._add_playlist_track(self.client, playlist_id, track, self.retry)

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove the cellar marker after its replacement is secure.

        Args:
            playlist_id: Cellar playlist.
            source: Original marker.
        """
        legacy._remove_playlist_track(self.client, playlist_id, source, self.retry)

    def save(self, state: dict[str, object]) -> None:
        """Persist one pending-transfer checkpoint.

        Args:
            state: Complete New Wine namespace.
        """
        self.state_access.save(state)

    def audit(self, run_id: str, result: CellarRefillResult) -> None:
        """Append the original refill audit record.

        Args:
            run_id: Original execution identifier.
            result: Accepted or previewed refill outcome.
        """
        legacy.append_cellar_log(run_id, result, self.log_path)

    def source(self, raw: object) -> PlaylistTrack:
        """Reconstruct a pending marker with unchanged validation.

        Args:
            raw: Serialized source record.

        Returns:
            Original source value.
        """
        return legacy._playlist_track_from_record(raw)


@dataclass(frozen=True)
class ArtistLibraryMembership:
    """Bind one artist's membership reads to the original SDK helper expressions.

    Args:
        client: Caller-owned Spotify client.
        artist: Original display name used in retry descriptions.
        retry: Existing retry/cancellation callback.
    """

    client: Spotify
    artist: str
    retry: RetryCall

    def albums(self, ids: list[str]) -> tuple[bool, ...]:
        """Read validated saved-album statuses.

        Args:
            ids: Candidate album IDs in mirror order.

        Returns:
            Boolean statuses in the same order.
        """
        return legacy._affinity_album_statuses(
            self.client, self.artist, ids, self.retry
        )

    def tracks(self, ids: list[str]) -> tuple[bool, ...]:
        """Read validated liked-track statuses.

        Args:
            ids: Candidate track IDs in mirror order.

        Returns:
            Boolean statuses in the same order.
        """
        return legacy._affinity_track_statuses(
            self.client, self.artist, ids, self.retry
        )
