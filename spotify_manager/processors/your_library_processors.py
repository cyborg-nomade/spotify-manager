"""Data processors for your library file."""

from typing import cast

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify

# UFI
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


async def async_is_in_library_artist(sp: Spotify, artist: YourLibraryArtist) -> bool:
    """Read original singleton follow membership.

    Args:
        sp: Original caller-owned synchronous client.
        artist: Original export identity.

    Returns:
        The original first membership value without added validation.
    """
    response = await sp.current_user_following_artists([artist.spotify_id])
    return cast(list[bool], response)[0]


async def async_is_in_library_track(sp: Spotify, track: YourLibraryTrack) -> bool:
    """Read original singleton liked-track membership.

    Args:
        sp: Original caller-owned synchronous client.
        track: Original export identity.

    Returns:
        The original first membership value without added validation.
    """
    response = await sp.current_user_saved_tracks_contains([track.spotify_id])
    return cast(list[bool], response)[0]


async def async_save_to_library_artist(sp: Spotify, artist: YourLibraryArtist) -> None:
    """Accept the original singleton artist-follow request.

    Args:
        sp: Original caller-owned synchronous client.
        artist: Original export identity.
    """
    await sp.user_follow_artists([artist.spotify_id])


async def async_save_to_library_track(sp: Spotify, track: YourLibraryTrack) -> None:
    """Accept the original singleton liked-track request.

    Args:
        sp: Original caller-owned synchronous client.
        track: Original export identity.
    """
    await sp.current_user_saved_tracks_add([track.spotify_id])


def is_in_library_artist(sp: LegacySpotify, artist: YourLibraryArtist) -> bool:
    """Read original singleton follow membership.

    Args:
        sp: Original caller-owned synchronous client.
        artist: Original export identity.

    Returns:
        The original first membership value without added validation.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_is_in_library_artist(legacy_spotify(sp), artist))


def is_in_library_track(sp: LegacySpotify, track: YourLibraryTrack) -> bool:
    """Read original singleton liked-track membership.

    Args:
        sp: Original caller-owned synchronous client.
        track: Original export identity.

    Returns:
        The original first membership value without added validation.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_is_in_library_track(legacy_spotify(sp), track))


def save_to_library_artist(sp: LegacySpotify, artist: YourLibraryArtist) -> None:
    """Accept the original singleton artist-follow request.

    Args:
        sp: Original caller-owned synchronous client.
        artist: Original export identity.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_save_to_library_artist(legacy_spotify(sp), artist))


def save_to_library_track(sp: LegacySpotify, track: YourLibraryTrack) -> None:
    """Accept the original singleton liked-track request.

    Args:
        sp: Original caller-owned synchronous client.
        track: Original export identity.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_save_to_library_track(legacy_spotify(sp), track))
