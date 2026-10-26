"""Reuse the original OAuth scopes, cache formats and headless rotation behavior."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import cast

from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth
from spotipy.oauth2 import SpotifyOauthError

from spotify_manager.client import SPOTIFY_OAUTH_TIMEOUT_SECONDS
from spotify_manager.client import SpotifyAppAuthenticationError
from spotify_manager.client import SpotifyAppCredentials
from spotify_manager.client import configured_spotify_apps
from spotify_manager.client import should_open_browser_for_redirect
from spotify_manager.client import validate_spotify_redirect_uri
from spotify_manager.infrastructure.spotify_async.blocking import TokenSource
from spotify_manager.settings import Settings


SCOPES = (
    "playlist-modify-public",
    "playlist-modify-private",
    "playlist-read-private",
    "user-library-read",
    "user-library-modify",
    "user-follow-read",
    "user-follow-modify",
)


@dataclass
class OAuthSource:
    """Own the existing isolated SpotifyOAuth manager at a blocking SDK edge.

    Args:
        label: Original primary/app label.
        manager: Original SDK manager, excluded from representation.
        interactive: Original caller's permission to authenticate interactively.
    """

    label: str
    manager: SpotifyOAuth = field(repr=False)
    interactive: bool = False

    def token(self) -> str:
        """Read the token at the SDK's original request-authentication boundary.

        Returns:
            Original access token.

        Raises:
            OSError: Original OAuth cache or network transport is unavailable.
            SpotifyOauthError: Original SDK authentication fails.
        """
        return cast(str, self.manager.get_access_token(as_dict=False))

    def refresh(self) -> None:
        """Force-refresh exactly as the original credential-rotation boundary.

        Raises:
            SpotifyAppAuthenticationError: Headless cache or refresh is unavailable.
            SpotifyOauthError: Original SDK authentication fails.
        """
        token = self.manager.cache_handler.get_cached_token()
        if token is None:
            if not self.interactive:
                raise SpotifyAppAuthenticationError(
                    f"Spotify credentials {self.label} have no headless token cache."
                )
            self.manager.get_access_token(as_dict=True, check_cache=True)
            return
        refresh = token.get("refresh_token")
        if not refresh:
            raise SpotifyAppAuthenticationError(
                f"Spotify credentials {self.label} have no refresh token."
            )
        self.manager.refresh_access_token(str(refresh))

    def close(self) -> None:
        """Close the SDK-owned OAuth session after cache work has completed."""
        self.manager._session.close()


@dataclass(frozen=True)
class OAuthProvisioner:
    """Construct original OAuth managers through the bounded off-loop boundary.

    Args:
        configuration: Original Spotify app and redirect settings.
        interactive: Explicit permission for local authentication.
    """

    configuration: Settings = field(repr=False)
    interactive: bool = False

    def open_sources(self) -> tuple[TokenSource, ...]:
        """Create isolated cache/session owners in the original app order.

        Returns:
            Primary and configured optional credentials.

        Raises:
            ValueError: Original redirect or credential configuration is invalid.
            OSError: A cache directory cannot be created.
        """
        redirect = self.configuration.spotipy_redirect_uri
        validate_spotify_redirect_uri(redirect)
        sources = []
        try:
            for app in configured_spotify_apps(self.configuration):
                sources.append(self._source(app, redirect))
        except OSError, ValueError, SpotifyOauthError:
            for source in sources:
                source.close()
            raise
        return tuple(sources)

    def _source(self, app: SpotifyAppCredentials, redirect: str) -> OAuthSource:
        Path(app.cache_path).parent.mkdir(parents=True, exist_ok=True)
        manager = SpotifyOAuth(
            client_id=app.client_id,
            client_secret=app.client_secret,
            redirect_uri=redirect,
            scope=list(SCOPES),
            cache_handler=CacheFileHandler(cache_path=str(app.cache_path)),
            open_browser=should_open_browser_for_redirect(redirect),
            requests_timeout=SPOTIFY_OAUTH_TIMEOUT_SECONDS,
        )
        return OAuthSource(app.label, manager, self.interactive)
