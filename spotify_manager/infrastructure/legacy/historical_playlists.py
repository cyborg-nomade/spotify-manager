"""Retain the existing synchronous historical playlist observation boundaries."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.historical_values import PlaylistState
from spotify_manager.application.historical_values import SpotifySelectionResolution
from spotify_manager.application.historical_values import SpotifyTrackMatch
from spotify_manager.domain.history import ScrobbleSelection
from spotify_manager.routines import blast_from_past as legacy


@dataclass(frozen=True)
class LegacyHistoricalPlaylist:
    """Bind caller-owned Spotify and the original retry and cancellation policy.

    Args:
        client: Existing caller-owned Spotify client.
        playlist_id: Target playlist.
        progress: Optional original progress callback.
        retry: Original caller retry policy.
        cancel: Optional original cancellation predicate.
    """

    client: Spotify
    playlist_id: str
    progress: legacy.ProgressCallback | None
    retry: legacy.RetryCall
    cancel: legacy.CancelCheck | None

    def read(self) -> PlaylistState:
        """Observe destination facts using the original pagination boundary.

        Returns:
            Playlist size and membership identities.

        Raises:
            SpotifyTrackResolutionError: Spotify returns unusable playlist data.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        from spotify_manager.routines.blast_from_past import load_playlist_state

        return load_playlist_state(
            self.client, self.playlist_id, self.retry, self.cancel
        )

    def resolve(
        self, selections: tuple[ScrobbleSelection, ...], playlist: PlaylistState
    ) -> SpotifySelectionResolution:
        """Resolve matches and liked observations in their original order.

        Args:
            selections: Selected plays in requested order.
            playlist: Observed playlist membership.

        Returns:
            Original match decisions and pending additions.

        Raises:
            SpotifyTrackResolutionError: Spotify returns unusable search or liked data.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        from spotify_manager.bootstrap.historical_playlists import historical_resolution

        workflow = historical_resolution(
            self.client, self.progress, self.retry, self.cancel
        )
        return workflow.run(selections, playlist)

    def append(self, matches: list[SpotifyTrackMatch]) -> None:
        """Append pending matches using the original API-sized batches.

        Args:
            matches: Selected matches in their original order.

        Raises:
            BlastFromPastCancelledError: Cancellation is requested.
        """
        from spotify_manager.routines.blast_from_past import add_spotify_matches

        add_spotify_matches(
            self.client, self.playlist_id, matches, self.retry, self.cancel
        )


@dataclass(frozen=True)
class LegacyHistoricalMatches:
    """Bind historical track observations to their original synchronous API helpers.

    Args:
        client: Caller-owned Spotify client.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.
    """

    client: Spotify
    retry: legacy.RetryCall
    cancel: legacy.CancelCheck | None

    def search(self, scrobble: legacy.Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Search one selected scrobble with the existing qualifier parsing.

        Args:
            scrobble: Original selected play.

        Returns:
            Artist/track-qualified matches in search rank order.

        Raises:
            SpotifyTrackResolutionError: Search data is unusable.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        from spotify_manager.routines.blast_from_past import search_spotify_matches

        return search_spotify_matches(self.client, scrobble, self.retry, self.cancel)

    def liked(self, groups: list[tuple[SpotifyTrackMatch, ...]]) -> set[str]:
        """Read liked status using original identity batching.

        Args:
            groups: Ordered search matches, including empty groups.

        Returns:
            Live liked identities.

        Raises:
            SpotifyTrackResolutionError: Liked statuses are unusable.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        from spotify_manager.routines.blast_from_past import liked_spotify_track_ids

        return liked_spotify_track_ids(self.client, groups, self.retry, self.cancel)
