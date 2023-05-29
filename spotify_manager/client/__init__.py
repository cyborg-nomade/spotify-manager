"""Spotipy client."""

import spotipy
from spotipy.oauth2 import SpotifyOAuth


def get_spotipy_client() -> spotipy.Spotify:
    """."""
    spotipy_client_id = "fc70707ebf5d4ca3af5bdcd88bdd9b17"
    spotipy_client_secret = "bc624df47d1c48b5a3f5dcef186c2b6c"
    spotipy_redirect_uri = "http://localhost"

    scope = ["playlist-modify-public", "playlist-modify-private", "user-library-read"]

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scope,
            client_id=spotipy_client_id,
            client_secret=spotipy_client_secret,
            redirect_uri=spotipy_redirect_uri,
        )
    )
