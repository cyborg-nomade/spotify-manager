"""Spotipy client."""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from typing import Protocol
from urllib.parse import urlparse

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

# UFI
from spotify_manager.settings import Settings


settings = Settings()
logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
ROTATING_STATUS_FORCELIST = (500, 502, 503, 504)
OPTIONAL_APP_LABELS = ("app5", "app6", "app7", "app8")
SpotifyEventCallback = Callable[[str], None]
LOCALHOST_REDIRECT_MESSAGE = (
    "Spotify no longer accepts localhost redirect URIs. Set "
    "SPOTIPY_REDIRECT_URI to an explicit loopback IP URI such as "
    "http://127.0.0.1:8080/callback, then add that exact URI to your "
    "Spotify app dashboard."
)


class SpotifyRedirectURIError(ValueError):
    """Raised when the configured Spotify redirect URI cannot be used."""


class SpotifyClientConfigurationError(ValueError):
    """Raised when an optional Spotify application is only partly configured."""


class SpotifyAppAuthenticationError(RuntimeError):
    """Raised when one configured application cannot provide an access token."""


@dataclass(frozen=True)
class SpotifyAppCredentials:
    """One Spotify application and its isolated OAuth cache."""

    label: str
    client_id: str
    client_secret: str
    cache_path: Path


class SpotifySettings(Protocol):
    """Settings required for the primary Spotify application."""

    spotipy_client_id: str
    spotipy_client_secret: str


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


def _cache_path_for_app(label: str) -> Path:
    """Return the configured or conventional cache path for one app."""
    primary_path = Path(
        os.getenv(
            "SPOTIPY_CACHE_PATH",
            "spotify_manager/auth/spotipy_token_cache.json",
        )
    )
    if label == "primary":
        return primary_path

    configured_path = os.getenv(f"{label.upper()}_SPOTIPY_CACHE_PATH")
    if configured_path:
        return Path(configured_path)
    suffix = primary_path.suffix
    stem = primary_path.stem if suffix else primary_path.name
    filename = f"{stem}_{label}{suffix}"
    return primary_path.with_name(filename)


def configured_spotify_apps(
    configuration: SpotifySettings | None = None,
) -> tuple[SpotifyAppCredentials, ...]:
    """Return complete Spotify app credential sets in rotation order."""
    current = settings if configuration is None else configuration
    apps = [
        SpotifyAppCredentials(
            label="primary",
            client_id=str(current.spotipy_client_id),
            client_secret=str(current.spotipy_client_secret),
            cache_path=_cache_path_for_app("primary"),
        )
    ]
    for label in OPTIONAL_APP_LABELS:
        client_id = getattr(current, f"{label}_client_id", None)
        client_secret = getattr(current, f"{label}_client_secret", None)
        if bool(client_id) != bool(client_secret):
            raise SpotifyClientConfigurationError(
                f"{label.upper()}_CLIENT_ID and {label.upper()}_CLIENT_SECRET "
                "must be configured together."
            )
        if client_id and client_secret:
            apps.append(
                SpotifyAppCredentials(
                    label=label,
                    client_id=str(client_id),
                    client_secret=str(client_secret),
                    cache_path=_cache_path_for_app(label),
                )
            )
    return tuple(apps)


class RotatingSpotify(spotipy.Spotify):
    """Spotify client that rotates application credentials after HTTP 429."""

    def __init__(
        self,
        app_labels: tuple[str, ...],
        auth_managers: tuple[SpotifyOAuth, ...],
        event_callback: SpotifyEventCallback | None = None,
        allow_interactive_auth: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize one client with an ordered set of auth managers."""
        if not auth_managers or len(app_labels) != len(auth_managers):
            raise SpotifyClientConfigurationError(
                "At least one labeled Spotify auth manager is required."
            )
        self._app_labels = app_labels
        self._auth_managers = auth_managers
        self._active_app_index = 0
        self._event_callback = event_callback
        self._allow_interactive_auth = allow_interactive_auth
        self._rotation_lock = RLock()
        super().__init__(auth_manager=auth_managers[0], **kwargs)

    @property
    def active_app_label(self) -> str:
        """Return the non-secret label of the active Spotify application."""
        return self._app_labels[self._active_app_index]

    @property
    def app_labels(self) -> tuple[str, ...]:
        """Return the configured application labels in rotation order."""
        return self._app_labels

    def set_event_callback(
        self,
        callback: SpotifyEventCallback | None,
    ) -> SpotifyEventCallback | None:
        """Replace the event callback and return the previous callback."""
        previous = self._event_callback
        self._event_callback = callback
        return previous

    def _emit(self, message: str) -> None:
        """Log a safe rotation event and forward it to the active interface."""
        logger.warning(message)
        if self._event_callback is not None:
            try:
                self._event_callback(message)
            except Exception:  # pragma: no cover - display callbacks are best-effort
                logger.exception("Spotify event callback failed")

    def _refresh_auth_manager(self, index: int) -> None:
        """Force-refresh one app token, authenticating locally if necessary."""
        label = self._app_labels[index]
        auth_manager = self._auth_managers[index]
        token_info = auth_manager.cache_handler.get_cached_token()
        if token_info is None:
            if not self._allow_interactive_auth:
                raise SpotifyAppAuthenticationError(
                    f"Spotify credentials {label} have no headless token cache."
                )
            auth_manager.get_access_token(as_dict=True, check_cache=True)
            return

        refresh_token = token_info.get("refresh_token")
        if not refresh_token:
            raise SpotifyAppAuthenticationError(
                f"Spotify credentials {label} have no refresh token."
            )
        auth_manager.refresh_access_token(str(refresh_token))

    def _activate_next_app(self, attempted: set[int]) -> bool:
        """Activate and refresh the next usable, untried app."""
        app_count = len(self._auth_managers)
        for distance in range(1, app_count + 1):
            index = (self._active_app_index + distance) % app_count
            if index in attempted:
                continue
            attempted.add(index)
            label = self._app_labels[index]
            self._emit(
                f"Switching Spotify credentials to {label} and refreshing its token."
            )
            try:
                self._refresh_auth_manager(index)
            except SpotifyAppAuthenticationError as exc:
                self._emit(str(exc))
                continue
            except Exception:
                self._emit(
                    f"Spotify credentials {label} could not refresh; "
                    "trying the next configured app."
                )
                continue
            self._active_app_index = index
            self.auth_manager = self._auth_managers[index]
            self._emit(f"Spotify requests now use credentials {label}.")
            return True
        return False

    def refresh_all_app_tokens(self) -> tuple[str, ...]:
        """Authenticate or force-refresh every configured app in order."""
        refreshed = []
        with self._rotation_lock:
            original_index = self._active_app_index
            try:
                for index, label in enumerate(self._app_labels):
                    self._emit(f"Refreshing Spotify token for credentials {label}.")
                    self._refresh_auth_manager(index)
                    refreshed.append(label)
                    self._emit(f"Spotify token ready for credentials {label}.")
            finally:
                self._active_app_index = original_index
                self.auth_manager = self._auth_managers[original_index]
        return tuple(refreshed)

    def rotate_credentials(self) -> str:
        """Force-refresh and activate the next usable configured app."""
        with self._rotation_lock:
            if not self._activate_next_app({self._active_app_index}):
                raise SpotifyAppAuthenticationError(
                    "No alternate Spotify credential set could be activated."
                )
            return self.active_app_label

    def _internal_call(
        self,
        method: str,
        url: str,
        payload: object,
        params: dict[str, Any],
    ) -> Any:
        """Retry a rate-limited request through the next configured app."""
        with self._rotation_lock:
            attempted = {self._active_app_index}
            while True:
                try:
                    return super()._internal_call(method, url, payload, params)
                except SpotifyException as exc:
                    if exc.http_status != 429:
                        raise
                    self._emit(
                        f"Spotify rate limit reached for credentials "
                        f"{self.active_app_label}."
                    )
                    if not self._activate_next_app(attempted):
                        self._emit(
                            "All configured Spotify credential sets are "
                            "rate-limited or unavailable."
                        )
                        raise


def get_spotipy_client(
    retries: int = 5,
    status_retries: int | None = None,
    status_forcelist: tuple[int, ...] | None = None,
    event_callback: SpotifyEventCallback | None = None,
    allow_interactive_auth: bool = True,
) -> spotipy.Spotify:
    """Get a Spotify client that rotates configured apps after rate limits."""
    spotipy_redirect_uri = settings.spotipy_redirect_uri

    validate_spotify_redirect_uri(spotipy_redirect_uri)
    apps = configured_spotify_apps()
    scope = [
        "playlist-modify-public",
        "playlist-modify-private",
        "playlist-read-private",
        "user-library-read",
        "user-library-modify",
        "user-follow-read",
        "user-follow-modify",
    ]
    auth_managers = []
    for app in apps:
        app.cache_path.parent.mkdir(parents=True, exist_ok=True)
        auth_managers.append(
            SpotifyOAuth(
                client_id=app.client_id,
                client_secret=app.client_secret,
                redirect_uri=spotipy_redirect_uri,
                scope=scope,
                cache_handler=CacheFileHandler(cache_path=str(app.cache_path)),
                open_browser=should_open_browser_for_redirect(spotipy_redirect_uri),
            )
        )

    return RotatingSpotify(
        app_labels=tuple(app.label for app in apps),
        auth_managers=tuple(auth_managers),
        event_callback=event_callback,
        allow_interactive_auth=allow_interactive_auth,
        requests_timeout=10,
        retries=retries,
        status_retries=retries if status_retries is None else status_retries,
        status_forcelist=(
            ROTATING_STATUS_FORCELIST if status_forcelist is None else status_forcelist
        ),
    )
