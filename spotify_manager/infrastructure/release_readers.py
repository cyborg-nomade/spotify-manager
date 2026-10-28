"""Named synchronous release and playlist transport readers."""

from dataclasses import dataclass

from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate


type RetryCall = Retry


@dataclass(frozen=True)
class SpotifyReleasePages:
    """Read release candidates for a mapped history artist.

    Args:
        spotify: Caller-owned client.
        artist: History artist used for request descriptions.
        mapped: Accepted Spotify identity.
        retry: Original transport retry policy.
    """

    spotify: Spotify
    artist: RankedArtist
    mapped: SpotifyArtistCandidate
    retry: RetryCall

    async def read(self, offset: int) -> object:
        """Read one original catalog page.

        Args:
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.routines.release_check import _read_catalog_page

        return await _read_catalog_page(
            self.spotify, self.artist, self.mapped, self.retry, offset
        )


@dataclass(frozen=True)
class SpotifyReleaseTracks:
    """Read complete or first-only tracks for a selected release.

    Args:
        spotify: Caller-owned client.
        release: Selected release.
        retry: Original transport retry policy.
    """

    spotify: Spotify
    release: ReleaseCandidate
    retry: RetryCall

    async def read(self, offset: int, limit: int) -> object:
        """Read one original track page.

        Args:
            offset: Raw row offset.
            limit: Original first-only or complete page size.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.routines.release_check import _read_track_page

        return await _read_track_page(
            self.spotify, self.release, self.retry, offset, limit
        )


@dataclass(frozen=True)
class SpotifyReleasePlaylist:
    """Read complete URI-preserving destination playlist pages.

    Args:
        spotify: Caller-owned client.
        playlist: Destination identity.
        retry: Original transport retry policy.
    """

    spotify: Spotify
    playlist: str
    retry: RetryCall

    async def read(self, offset: int) -> object:
        """Read one original destination page.

        Args:
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.routines.release_check import _read_playlist_page

        return await _read_playlist_page(
            self.spotify, self.playlist, self.retry, offset
        )
