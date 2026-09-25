"""Synchronous bridges retaining legacy Spotify parsing and retry policies.

These adapters intentionally reuse existing routines until their vertical slices
move. SDK payloads and routine-specific retry descriptions stay at this boundary.
"""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.music import Album
from spotify_manager.application.music import NamedTrack
from spotify_manager.application.music import Track
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.requeue_result import RequeueForADreamError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.processors import library_lookups
from spotify_manager.routines import new_wine
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import slow_listening


@dataclass
class SpotifyAlbumCatalog:
    """Use the original synchronous client and tolerant album codecs.

    Args:
        client: Existing client with its caller-owned credentials and callbacks.
    """

    client: Spotify

    def resolve_album(
        self, *, name: str | None, album_id: str | None, artist: str | None
    ) -> Album:
        """Resolve the exact legacy album identity without local-file fallback.

        Args:
            name: Exact display name when the identifier is absent.
            album_id: Preferred direct identifier.
            artist: Optional primary-artist name.

        Returns:
            The original parsed identity as a typed value.

        Raises:
            LookupError: No unique album matches.
            ValueError: Both name and identifier are absent.
            RuntimeError: Spotify returns malformed data.
        """
        identity = library_lookups.resolve_live_album(
            self.client, name=name, album_id=album_id, artist=artist
        )
        return Album(*identity)

    def album_tracks(self, album_id: str) -> tuple[Track, ...]:
        """Load all album pages through the existing validation rules.

        Args:
            album_id: Resolved identifier.

        Returns:
            Ordered tracks with duplicate and missing identifiers preserved.

        Raises:
            RuntimeError: Spotify returns incomplete tracks or malformed pages.
        """
        tracks = []
        for raw in library_lookups._fetch_album_tracks(self.client, album_id):
            identifier = str(raw["id"]) if raw.get("id") else None
            tracks.append(
                Track(identifier, str(raw["name"]), str(raw["uri"]), str(raw.get("id")))
            )
        return tuple(tracks)


@dataclass
class SpotifyTrackMembership:
    """Preserve the live album instrument's batch size and response validation.

    Args:
        client: The same synchronous client used for catalog reads.
    """

    client: Spotify

    def liked_tracks(self, track_ids: tuple[str, ...]) -> dict[str, bool]:
        """Read fresh membership without deduplicating or caching observations.

        Args:
            track_ids: Ordered identifiers, including duplicates.

        Returns:
            Last observed status for each identifier.

        Raises:
            RuntimeError: Spotify returns malformed or mismatched statuses.
        """
        return library_lookups.load_live_liked_statuses(self.client, list(track_ids))


@dataclass
class RequeuePlaylistAccess:
    """Wrap the existing Requeue read and write boundaries synchronously.

    Args:
        client: Existing Spotify client, whose ownership remains with the caller.
        retry: Existing routine retry policy, invoked at the same boundaries.
    """

    client: Spotify
    retry: RetryCall

    def sources(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read complete markers with the public routine's error translation.

        Args:
            playlist_id: Source playlist, including the final live recheck.

        Returns:
            Ordered parsed markers, preserving their original values.

        Raises:
            RequeueForADreamError: The existing playlist parser rejects a response.
        """
        try:
            return new_wine.load_playlist_tracks(self.client, playlist_id, self.retry)
        except new_wine.NewWineError as exc:
            raise RequeueForADreamError(str(exc)) from exc

    def tracks(self, playlist_id: str) -> tuple[Track, ...]:
        """Read playable markers through the original pagination and codec.

        Args:
            playlist_id: Source playlist identifier.

        Returns:
            Ordered markers, retaining duplicate entries.

        Raises:
            new_wine.NewWineError: A playlist response is malformed.
        """
        original = new_wine.load_playlist_tracks(self.client, playlist_id, self.retry)
        return tuple(
            Track(track.spotify_id, track.name, track.uri) for track in original
        )

    def append(self, playlist_id: str, track: NamedTrack) -> None:
        """Append exactly one marker through the original write and retry path.

        Args:
            playlist_id: Destination identifier.
            track: Replacement marker.
        """
        requeue_for_a_dream._add_track(self.client, playlist_id, track, self.retry)

    def remove(self, playlist_id: str, track: NamedTrack) -> None:
        """Remove exactly one marker through the original write and retry path.

        Args:
            playlist_id: Source identifier.
            track: Marker to remove.
        """
        requeue_for_a_dream._remove_track(self.client, playlist_id, track, self.retry)


@dataclass
class SpotifyRequeueCatalog:
    """Reuse catalog I/O while the shared legacy loaders migrate by routine family.

    Args:
        client: Caller-owned synchronous client.
        retry: Existing retry policy with its original descriptions and boundaries.
    """

    client: Spotify
    retry: RetryCall

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Load the selected studio discography with unchanged error translation.

        Args:
            artist_id: Primary artist of the source marker.

        Returns:
            Ordered, deduplicated studio editions selected by the domain policy.

        Raises:
            RequeueForADreamError: The shared catalog parser rejects a response.
        """
        try:
            return slow_listening.load_discography(self.client, artist_id, self.retry)
        except slow_listening.SlowListeningError as exc:
            raise RequeueForADreamError(str(exc)) from exc

    def release_tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Load playable successor tracks with unchanged error translation.

        Args:
            release: Selected successor edition.

        Returns:
            Original parsed tracks in disc and track order.

        Raises:
            RequeueForADreamError: The shared track parser rejects a response.
        """
        try:
            return slow_listening.load_release_tracks(self.client, release, self.retry)
        except slow_listening.SlowListeningError as exc:
            raise RequeueForADreamError(str(exc)) from exc
