"""Test Spotipy client."""

from types import SimpleNamespace

import pytest
import spotipy

# UFI
from spotify_manager import client as client_module
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
    assert client.retries == 5
    assert client.status_retries == 5


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

    client = client_module.get_spotipy_client(retries=0, status_retries=0)

    assert client.retries == 0
    assert client.status_retries == 0


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
