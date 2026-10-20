"""Construct concrete resources for legacy maintenance use cases."""

from spotipy import Spotify

from spotify_manager.application.legacy_library_effects import MonthlyActions
from spotify_manager.application.legacy_library_effects import MonthlyPlaylist
from spotify_manager.infrastructure.legacy_library_resources import LegacyLibraryFiles
from spotify_manager.infrastructure.legacy_library_resources import LegacyMonthlyLimits
from spotify_manager.infrastructure.legacy_library_resources import SpotifyAlbumRefresh
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyControlMembership,
)
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyConversionCatalog,
)
from spotify_manager.infrastructure.legacy_library_resources import SpotifyPlaylistClock
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyPlaylistWrites,
)
from spotify_manager.infrastructure.legacy_library_resources import SpotifyTrackRead
from spotify_manager.settings import Settings


def legacy_settings() -> Settings:
    """Observe process-local legacy settings.

    Returns:
        Original environment-backed settings.
    """
    return Settings()


def conversion_files() -> LegacyLibraryFiles:
    """Construct conversion storage.

    Returns:
        Named storage resource.
    """
    return LegacyLibraryFiles()


def monthly_files() -> LegacyLibraryFiles:
    """Construct monthly storage.

    Returns:
        Named storage resource.
    """
    return LegacyLibraryFiles()


def conversion_catalog(spotify: Spotify) -> SpotifyConversionCatalog:
    """Construct conversion reads and writes.

    Args:
        spotify: Caller-owned synchronous client.

    Returns:
        Named conversion resource.
    """
    return SpotifyConversionCatalog(spotify)


def monthly_actions(spotify: Spotify) -> MonthlyActions:
    """Construct resources for the fixed monthly sequence.

    Args:
        spotify: Caller-owned synchronous client.

    Returns:
        Membership and playlist resources.
    """
    return MonthlyActions(SpotifyControlMembership(spotify), monthly_playlist(spotify))


def monthly_playlist(spotify: Spotify) -> MonthlyPlaylist:
    """Construct resources for direct playlist execution.

    Args:
        spotify: Caller-owned synchronous client.

    Returns:
        Cohesive clock, catalog, writes, storage and settings.
    """
    return MonthlyPlaylist(
        SpotifyPlaylistClock(spotify),
        SpotifyTrackRead(spotify),
        SpotifyPlaylistWrites(spotify),
        LegacyLibraryFiles(),
        LegacyMonthlyLimits(),
    )


def album_refresh(spotify: Spotify) -> SpotifyAlbumRefresh:
    """Construct saved-album refresh I/O.

    Args:
        spotify: Caller-owned synchronous client.

    Returns:
        Named paging and storage resource.
    """
    return SpotifyAlbumRefresh(spotify)


def track_read(spotify: Spotify) -> SpotifyTrackRead:
    """Construct track paging and decoding.

    Args:
        spotify: Caller-owned synchronous client.

    Returns:
        Named track resource.
    """
    return SpotifyTrackRead(spotify)
