"""Test Spotipy client."""

from types import SimpleNamespace

import pytest
import spotipy
from requests.exceptions import ConnectionError as RequestsConnectionError
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
    assert retry.read is False


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
    retry = client._session.get_adapter("https://").max_retries
    assert retry.read is False


def test_get_request_retries_connection_reset_including_token_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(),
    )
    calls = 0
    sleeps: list[float] = []
    events: list[str] = []

    def api_call(_spotify, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RequestsConnectionError(
                "Connection aborted.",
                ConnectionResetError(104, "Connection reset by peer"),
            )
        return {"ok": True}

    monkeypatch.setattr(spotipy.Spotify, "_internal_call", api_call)
    monkeypatch.setattr(client_module, "sleep", sleeps.append)
    spotify = client_module.get_spotipy_client(event_callback=events.append)

    assert spotify._internal_call("GET", "endpoint", None, {}) == {"ok": True}
    assert calls == 2
    assert sleeps == [10]
    assert events == [
        "Spotify connection interrupted; retrying in 10 seconds (attempt 2 of 4)."
    ]


def test_mutating_request_does_not_retry_ambiguous_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(),
    )
    calls = 0
    sleeps: list[float] = []

    def api_call(_spotify, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RequestsConnectionError("Connection reset by peer")

    monkeypatch.setattr(spotipy.Spotify, "_internal_call", api_call)
    monkeypatch.setattr(client_module, "sleep", sleeps.append)
    spotify = client_module.get_spotipy_client()

    with pytest.raises(RequestsConnectionError):
        spotify._internal_call("POST", "endpoint", None, {})

    assert calls == 1
    assert sleeps == []


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


def test_validate_spotify_redirect_uri_requires_an_absolute_uri() -> None:
    with pytest.raises(SpotifyRedirectURIError, match="absolute URI"):
        validate_spotify_redirect_uri("127.0.0.1/callback")


def test_configured_app_uses_explicit_optional_cache_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    optional_cache = tmp_path / "app5.json"
    monkeypatch.setenv("APP5_SPOTIPY_CACHE_PATH", str(optional_cache))

    apps = client_module.configured_spotify_apps(
        rotating_settings(
            app5_client_id="app5-id",
            app5_client_secret="app5-secret",
        )
    )

    assert apps[1].cache_path == optional_cache


def test_rotating_client_requires_matching_labels_and_managers() -> None:
    with pytest.raises(SpotifyClientConfigurationError, match="At least one"):
        client_module.RotatingSpotify((), ())
    with pytest.raises(SpotifyClientConfigurationError, match="At least one"):
        client_module.RotatingSpotify(("primary",), ())


def test_event_callback_can_be_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", rotating_settings())
    previous_events: list[str] = []
    new_events: list[str] = []
    spotify = client_module.get_spotipy_client(event_callback=previous_events.append)

    previous = spotify.set_event_callback(new_events.append)
    spotify._emit("event")

    assert previous == previous_events.append
    assert new_events == ["event"]


def test_rotation_can_authenticate_interactively_without_cache(
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
    managers: list[FakeOAuth] = []

    def oauth_factory(**kwargs):
        manager = FakeOAuth(**kwargs)
        managers.append(manager)
        return manager

    monkeypatch.setattr(client_module, "SpotifyOAuth", oauth_factory)
    monkeypatch.setattr(
        client_module,
        "CacheFileHandler",
        lambda cache_path: FakeCacheHandler(cache_path, has_token=False),
    )
    spotify = client_module.get_spotipy_client(allow_interactive_auth=True)

    assert spotify.rotate_credentials() == "app5"
    assert managers[1].interactive_calls == 1


def test_rotation_skips_missing_refresh_token_and_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CacheWithoutRefresh(FakeCacheHandler):
        def get_cached_token(self) -> dict[str, str]:
            return {"access_token": "stale"}

    class SometimesFailingOAuth(FakeOAuth):
        def refresh_access_token(self, refresh_token: str) -> dict[str, str]:
            if self.client_id == "app6-id":
                raise RuntimeError("refresh failed")
            return super().refresh_access_token(refresh_token)

    monkeypatch.setattr(
        client_module,
        "settings",
        rotating_settings(
            app5_client_id="app5-id",
            app5_client_secret="app5-secret",
            app6_client_id="app6-id",
            app6_client_secret="app6-secret",
            app7_client_id="app7-id",
            app7_client_secret="app7-secret",
        ),
    )
    monkeypatch.setattr(client_module, "SpotifyOAuth", SometimesFailingOAuth)

    def cache_factory(cache_path: str):
        if "app5" in cache_path:
            return CacheWithoutRefresh(cache_path)
        return FakeCacheHandler(cache_path)

    monkeypatch.setattr(client_module, "CacheFileHandler", cache_factory)
    events: list[str] = []
    spotify = client_module.get_spotipy_client(event_callback=events.append)

    assert spotify.rotate_credentials() == "app7"
    assert any("no refresh token" in event for event in events)
    assert any("could not refresh" in event for event in events)


def test_refresh_all_tokens_restores_original_active_app(
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
    monkeypatch.setattr(client_module, "CacheFileHandler", FakeCacheHandler)
    spotify = client_module.get_spotipy_client()
    spotify.rotate_credentials()

    assert spotify.refresh_all_app_tokens() == ("primary", "app5")
    assert spotify.active_app_label == "app5"


def test_manual_rotation_fails_without_an_alternate_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "settings", rotating_settings())
    spotify = client_module.get_spotipy_client()

    with pytest.raises(
        client_module.SpotifyAppAuthenticationError,
        match="No alternate",
    ):
        spotify.rotate_credentials()


def test_non_rate_limit_spotify_error_is_not_rotated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "settings", rotating_settings())

    def fail(*_args, **_kwargs):
        raise SpotifyException(500, -1, "server error")

    monkeypatch.setattr(spotipy.Spotify, "_internal_call", fail)
    spotify = client_module.get_spotipy_client()

    with pytest.raises(SpotifyException) as exc:
        spotify._internal_call("GET", "endpoint", None, {})
    assert exc.value.http_status == 500
