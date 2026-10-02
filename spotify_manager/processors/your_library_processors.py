"""Data processors for your library file."""

from spotipy import Spotify

# UFI
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


def is_in_library_artist(sp: Spotify, artist: YourLibraryArtist) -> bool:
    """Read original singleton follow membership.

    Args:
        sp: Original caller-owned synchronous client.
        artist: Original export identity.

    Returns:
        The original first membership value without added validation.
    """
    return sp.current_user_following_artists([artist.spotify_id])[0]


def is_in_library_track(sp: Spotify, track: YourLibraryTrack) -> bool:
    """Read original singleton liked-track membership.

    Args:
        sp: Original caller-owned synchronous client.
        track: Original export identity.

    Returns:
        The original first membership value without added validation.
    """
    return sp.current_user_saved_tracks_contains([track.spotify_id])[0]


def save_to_library_artist(sp: Spotify, artist: YourLibraryArtist) -> None:
    """Accept the original singleton artist-follow request.

    Args:
        sp: Original caller-owned synchronous client.
        artist: Original export identity.
    """
    sp.user_follow_artists([artist.spotify_id])


def save_to_library_track(sp: Spotify, track: YourLibraryTrack) -> None:
    """Accept the original singleton liked-track request.

    Args:
        sp: Original caller-owned synchronous client.
        track: Original export identity.
    """
    sp.current_user_saved_tracks_add([track.spotify_id])
