"""Spotipy client."""

import spotipy
from spotipy.oauth2 import SpotifyOAuth

# UFI
from spotify_manager.settings import Settings


settings = Settings()


def get_spotipy_client() -> spotipy.Spotify:
    """Get spotipy client."""
    spotipy_client_id = settings.spotipy_client_id
    spotipy_client_secret = settings.spotipy_client_secret
    spotipy_redirect_uri = settings.spotipy_redirect_uri

    scope = ["playlist-modify-public", "playlist-modify-private", "user-library-read"]

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scope,
            client_id=spotipy_client_id,
            client_secret=spotipy_client_secret,
            redirect_uri=spotipy_redirect_uri,
        ),
    )
