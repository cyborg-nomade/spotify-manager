"""Spotipy client."""

import os
from pathlib import Path

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

# UFI
from spotify_manager.settings import Settings


settings = Settings()


def get_spotipy_client() -> spotipy.Spotify:
    """Get spotipy client."""
    spotipy_client_id = settings.spotipy_client_id
    spotipy_client_secret = settings.spotipy_client_secret
    spotipy_redirect_uri = settings.spotipy_redirect_uri

    print(spotipy_client_id)
    print(spotipy_client_secret)
    print(spotipy_redirect_uri)

    spotify_cache_path = Path(
        os.getenv(
            "SPOTIPY_CACHE_PATH",
            "spotify_manager/auth/spotipy_token_cache.json",
        )
    )

    spotify_cache_path.parent.mkdir(parents=True, exist_ok=True)

    cache_handler = CacheFileHandler(cache_path=str(spotify_cache_path))

    scope = [
        "playlist-modify-public",
        "playlist-modify-private",
        "user-library-read",
        "user-follow-read",
        "user-follow-modify",
    ]

    auth_manager = SpotifyOAuth(
        client_id=spotipy_client_id,
        client_secret=spotipy_client_secret,
        redirect_uri=spotipy_redirect_uri,
        scope=scope,
        cache_handler=cache_handler,
        open_browser=False,
    )

    return spotipy.Spotify(
        auth_manager=auth_manager,
        requests_timeout=10,
        retries=5,
    )
