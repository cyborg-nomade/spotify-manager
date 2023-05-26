"""Spotipy client."""

import spotipy
from spotipy.oauth2 import SpotifyOAuth


def get_spotipy_client() -> spotipy.Spotify:
    """."""
    SPOTIPY_CLIENT_ID = "fc70707ebf5d4ca3af5bdcd88bdd9b17"
    SPOTIPY_CLIENT_SECRET = "bc624df47d1c48b5a3f5dcef186c2b6c"
    SPOTIPY_REDIRECT_URI = "http://localhost"

    scope = ["playlist-modify-public", "playlist-modify-private", "user-library-read"]

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scope,
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
            redirect_uri=SPOTIPY_REDIRECT_URI,
        )
    )
