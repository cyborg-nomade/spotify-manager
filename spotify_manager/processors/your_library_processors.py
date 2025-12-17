"""Data processors for your library file."""

from spotipy import Spotify

# UFI
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


def is_in_library_artist(sp: Spotify, artist: YourLibraryArtist) -> bool:
    """Check whether an artist is in library."""
    return sp.current_user_following_artists([artist.spotify_id])[0]


def is_in_library_track(sp: Spotify, track: YourLibraryTrack) -> bool:
    """Check whether a track is in library."""
    return sp.current_user_following_artists([track.spotify_id])[0]


def save_to_library_artist(sp: Spotify, artist: YourLibraryArtist) -> None:
    """Save artist to libary."""
    sp.user_follow_artists([artist.spotify_id])


def save_to_library_track(sp: Spotify, track: YourLibraryTrack) -> None:
    """Save track to libary."""
    sp.user_follow_artists([track.spotify_id])
