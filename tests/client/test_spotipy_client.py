"""Test Spotipy client."""

from types import SimpleNamespace

import pytest
import spotipy
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager import client as client_module
from spotify_manager.client import SpotifyClientConfigurationError
from spotify_manager.client import SpotifyRedirectURIError
from spotify_manager.client import should_open_browser_for_redirect
from spotify_manager.client import validate_spotify_redirect_uri


def test_get_spotipy_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get spotipy client."""
    monkeypatch.setattr(
        client_module,
        "settings",
        SimpleNamespace(
            spotipy_client_id="client-id",
            spotipy_client_secret="client-secret",
            spotipy_redirect_uri="http://127.0.0.1:8080/callback",
        ),
    )

    client = client_module.get_spotipy_client()
    assert isinstance(client, spotipy.Spotify)
    assert isinstance(client, client_module.RotatingSpotify)
    assert client.app_labels == ("primary",)
    assert client.retries == 5
    assert client.status_retries == 5
    assert 429 not in client.status_forcelist
    retry = client._session.get_adapter("https://").max_retries
    assert retry.respect_retry_after_header is False


def test_get_spotipy_client_accepts_retry_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get spotipy client with custom retry settings."""
    monkeypatch.setattr(
        client_module,
        "settings",
        SimpleNamespace(
            spotipy_client_id="client-id",
            spotipy_client_secret="client-secret",
            spotipy_redirect_uri="http://127.0.0.1:8080/callback",
        ),
    )

    client = client_module.get_spotipy_client(
        retries=0,
        status_retries=0,
        status_forcelist=(999,),
    )

    assert client.retries == 0
    assert client.status_retries == 0
    assert client.status_forcelist == (999,)


class FakeCacheHandler:
    """In-memory cache handler used by rotation tests."""

    def __init__(self, cache_path: str, has_token: bool = True) -> None:
        self.cache_path = cache_path
        self.has_token = has_token

    def get_cached_token(self) -> dict[str, str] | None:
        if not self.has_token:
            return None
        return {"refresh_token": f"refresh:{self.cache_path}"}


class FakeOAuth:
    """Small OAuth stand-in recording forced refreshes."""

    def __init__(self, **kwargs) -> None:
        self.client_id = kwargs["client_id"]
        self.cache_handler = kwargs["cache_handler"]
        self.refreshed: list[str] = []
        self.interactive_calls = 0

    def refresh_access_token(self, refresh_token: str) -> dict[str, str]:
        self.refreshed.append(refresh_token)
        return {"access_token": "fresh", "refresh_token": refresh_token}

    def get_access_token(self, **_kwargs) -> dict[str, str]:
        self.interactive_calls += 1
        return {"access_token": "interactive"}


def rotating_settings(**overrides):
    """Return complete primary settings plus optional test overrides."""
    values = {
        "spotipy_client_id": "primary-id",
        "spotipy_client_secret": "primary-secret",
        "spotipy_redirect_uri": "http://127.0.0.1:8080/callback",
        "app5_client_id": None,
        "app5_client_secret": None,
        "app6_client_id": None,
        "app6_client_secret": None,
        "app7_client_id": None,
        "app7_client_secret": None,
        "app8_client_id": None,
        "app8_client_secret": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_rate_limit_rotates_app_refreshes_token_and_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(
            app5_client_id="app5-id",
            app5_client_secret="app5-secret",
        ),
    )
    monkeypatch.setenv(
        "SPOTIPY_CACHE_PATH",
        str(tmp_path / "spotipy_token_cache.json"),
    )
    oauth_managers: list[FakeOAuth] = []

    def oauth_factory(**kwargs):
        manager = FakeOAuth(**kwargs)
        oauth_managers.append(manager)
        return manager

    monkeypatch.setattr(client_module, "SpotifyOAuth", oauth_factory)
    monkeypatch.setattr(client_module, "CacheFileHandler", FakeCacheHandler)
    calls: list[str] = []

    def api_call(spotify, *_args, **_kwargs):
        calls.append(spotify.active_app_label)
        if spotify.active_app_label == "primary":
            raise SpotifyException(429, -1, "rate limited")
        return {"ok": True}

    monkeypatch.setattr(spotipy.Spotify, "_internal_call", api_call)
    events: list[str] = []
    spotify = client_module.get_spotipy_client(event_callback=events.append)

    result = spotify._internal_call("GET", "endpoint", None, {})

    assert result == {"ok": True}
    assert calls == ["primary", "app5"]
    assert spotify.active_app_label == "app5"
    assert oauth_managers[1].refreshed == [
        f"refresh:{tmp_path / 'spotipy_token_cache_app5.json'}"
    ]
    assert any("Switching Spotify credentials to app5" in event for event in events)


def test_credentials_can_be_rotated_manually(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(
            app5_client_id="app5-id",
            app5_client_secret="app5-secret",
        ),
    )
    monkeypatch.setenv(
        "SPOTIPY_CACHE_PATH",
        str(tmp_path / "spotipy_token_cache.json"),
    )
    oauth_managers: list[FakeOAuth] = []

    def oauth_factory(**kwargs):
        manager = FakeOAuth(**kwargs)
        oauth_managers.append(manager)
        return manager

    monkeypatch.setattr(client_module, "SpotifyOAuth", oauth_factory)
    monkeypatch.setattr(client_module, "CacheFileHandler", FakeCacheHandler)
    spotify = client_module.get_spotipy_client()

    assert spotify.rotate_credentials() == "app5"
    assert spotify.active_app_label == "app5"
    assert len(oauth_managers[1].refreshed) == 1


def test_repeated_rate_limits_rotate_through_every_configured_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(
            **{
                f"app{number}_{field}": f"app{number}-{field}"
                for number in range(5, 9)
                for field in ("client_id", "client_secret")
            }
        ),
    )
    monkeypatch.setenv(
        "SPOTIPY_CACHE_PATH",
        str(tmp_path / "spotipy_token_cache.json"),
    )
    oauth_managers: list[FakeOAuth] = []

    def oauth_factory(**kwargs):
        manager = FakeOAuth(**kwargs)
        oauth_managers.append(manager)
        return manager

    monkeypatch.setattr(client_module, "SpotifyOAuth", oauth_factory)
    monkeypatch.setattr(client_module, "CacheFileHandler", FakeCacheHandler)
    calls: list[str] = []

    def api_call(spotify, *_args, **_kwargs):
        calls.append(spotify.active_app_label)
        if spotify.active_app_label != "app8":
            raise SpotifyException(429, -1, "rate limited")
        return {"ok": True}

    monkeypatch.setattr(spotipy.Spotify, "_internal_call", api_call)
    spotify = client_module.get_spotipy_client()

    assert spotify._internal_call("GET", "endpoint", None, {}) == {"ok": True}
    assert calls == ["primary", "app5", "app6", "app7", "app8"]
    assert spotify.active_app_label == "app8"
    assert [len(manager.refreshed) for manager in oauth_managers] == [0, 1, 1, 1, 1]


def test_rate_limit_skips_app_without_headless_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(
            app5_client_id="app5-id",
            app5_client_secret="app5-secret",
        ),
    )
    monkeypatch.setattr(client_module, "SpotifyOAuth", FakeOAuth)
    monkeypatch.setattr(
        client_module,
        "CacheFileHandler",
        lambda cache_path: FakeCacheHandler(cache_path, has_token=False),
    )
    monkeypatch.setattr(
        spotipy.Spotify,
        "_internal_call",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SpotifyException(429, -1, "rate limited")
        ),
    )
    events: list[str] = []
    spotify = client_module.get_spotipy_client(
        event_callback=events.append,
        allow_interactive_auth=False,
    )

    with pytest.raises(SpotifyException) as exc_info:
        spotify._internal_call("GET", "endpoint", None, {})

    assert exc_info.value.http_status == 429
    assert spotify.active_app_label == "primary"
    assert any("app5 have no headless token cache" in event for event in events)
    assert any("All configured Spotify credential sets" in event for event in events)


def test_partial_optional_app_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(app5_client_id="app5-id"),
    )

    with pytest.raises(SpotifyClientConfigurationError, match="APP5_CLIENT_SECRET"):
        client_module.get_spotipy_client()


def test_validate_spotify_redirect_uri_rejects_localhost() -> None:
    with pytest.raises(SpotifyRedirectURIError, match="localhost"):
        validate_spotify_redirect_uri("http://localhost")


def test_validate_spotify_redirect_uri_rejects_non_loopback_http() -> None:
    with pytest.raises(SpotifyRedirectURIError, match="loopback IP"):
        validate_spotify_redirect_uri("http://example.com/callback")


def test_validate_spotify_redirect_uri_accepts_loopback_ip() -> None:
    validate_spotify_redirect_uri("http://127.0.0.1:8080/callback")


def test_should_open_browser_for_redirect_requires_loopback_port() -> None:
    assert should_open_browser_for_redirect("http://127.0.0.1:8080/callback")
    assert not should_open_browser_for_redirect("http://127.0.0.1")
    assert not should_open_browser_for_redirect("https://example.com/callback")
