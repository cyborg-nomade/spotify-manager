"""Spotipy client."""

import os
from pathlib import Path
from urllib.parse import urlparse

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

# UFI
from spotify_manager.settings import Settings


settings = Settings()

LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
LOCALHOST_REDIRECT_MESSAGE = (
    "Spotify no longer accepts localhost redirect URIs. Set "
    "SPOTIPY_REDIRECT_URI to an explicit loopback IP URI such as "
    "http://127.0.0.1:8080/callback, then add that exact URI to your "
    "Spotify app dashboard."
)


class SpotifyRedirectURIError(ValueError):
    """Raised when the configured Spotify redirect URI cannot be used."""


def validate_spotify_redirect_uri(redirect_uri: str) -> None:
    """Validate the Spotify redirect URI before starting OAuth."""
    parsed_redirect_uri = urlparse(redirect_uri)
    redirect_host = parsed_redirect_uri.hostname

    if not parsed_redirect_uri.scheme or not parsed_redirect_uri.netloc:
        raise SpotifyRedirectURIError(
            "SPOTIPY_REDIRECT_URI must be an absolute URI such as "
            "http://127.0.0.1:8080/callback."
        )

    if redirect_host == "localhost":
        raise SpotifyRedirectURIError(LOCALHOST_REDIRECT_MESSAGE)

    if parsed_redirect_uri.scheme == "http" and redirect_host not in LOOPBACK_HOSTS:
        raise SpotifyRedirectURIError(
            "Spotify HTTP redirect URIs must use an explicit loopback IP "
            "literal, such as http://127.0.0.1:8080/callback."
        )


def should_open_browser_for_redirect(redirect_uri: str) -> bool:
    """Return whether Spotipy can capture auth through a local callback server."""
    parsed_redirect_uri = urlparse(redirect_uri)

    return (
        parsed_redirect_uri.scheme == "http"
        and parsed_redirect_uri.hostname in LOOPBACK_HOSTS
        and parsed_redirect_uri.port is not None
    )


def get_spotipy_client(
    retries: int = 5,
    status_retries: int | None = None,
    status_forcelist: tuple[int, ...] | None = None,
) -> spotipy.Spotify:
    """Get spotipy client."""
    spotipy_client_id = settings.spotipy_client_id
    spotipy_client_secret = settings.spotipy_client_secret
    spotipy_redirect_uri = settings.spotipy_redirect_uri

    validate_spotify_redirect_uri(spotipy_redirect_uri)

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
        "user-library-modify",
        "user-follow-read",
        "user-follow-modify",
    ]

    auth_manager = SpotifyOAuth(
        client_id=spotipy_client_id,
        client_secret=spotipy_client_secret,
        redirect_uri=spotipy_redirect_uri,
        scope=scope,
        cache_handler=cache_handler,
        open_browser=should_open_browser_for_redirect(spotipy_redirect_uri),
    )

    client_args = {}
    if status_forcelist is not None:
        client_args["status_forcelist"] = status_forcelist

    return spotipy.Spotify(
        auth_manager=auth_manager,
        requests_timeout=10,
        retries=retries,
        status_retries=retries if status_retries is None else status_retries,
        **client_args,
    )
