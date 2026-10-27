"""Verify explicit construction, resource cleanup and ordinary SDK cache settings."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from spotify_manager.bootstrap.spotify_async import AsyncSpotifyRuntime
from spotify_manager.bootstrap.spotify_async import SpotifyRuntimeOptions
from spotify_manager.infrastructure.spotify_async.oauth import SCOPES
from spotify_manager.infrastructure.spotify_async.oauth import OAuthProvisioner
from spotify_manager.infrastructure.spotify_async.oauth import OAuthSource
from spotify_manager.infrastructure.spotify_async.transport import AsyncSleep
from spotify_manager.infrastructure.spotify_async.transport import (
    NativeSpotifyTransport,
)
from spotify_manager.settings import Settings
from tests.spotify_async.memory import TokenMemory
from tests.spotify_async.memory import transport_memory


@pytest.mark.parametrize("connections, workers", [(0, 2), (2, 0), (-1, 2)])
def test_runtime_rejects_invalid_capacities(connections: int, workers: int) -> None:
    """Reject invalid capacities without constructing any clients.

    Args:
        connections: Selected HTTP capacity.
        workers: Selected blocking SDK capacity.
    """
    with pytest.raises(ValueError, match="positive"):
        SpotifyRuntimeOptions(connections=connections, oauth_workers=workers)


def test_runtime_owns_pool_and_oauth_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Build one client and close all owned resources before leaving its loop.

    Args:
        monkeypatch: External SDK provisioning substitution.
    """
    source = TokenMemory()
    monkeypatch.setattr(OAuthProvisioner, "open_sources", Mock(return_value=(source,)))
    asyncio.run(_runtime(source))


async def _runtime(source: TokenMemory) -> None:
    runtime = AsyncSpotifyRuntime(Settings())
    async with runtime as client:
        assert isinstance(client.transport, NativeSpotifyTransport)
        assert not client.transport.http.is_closed
        with pytest.raises(RuntimeError, match="twice"):
            await runtime.__aenter__()
    assert client.transport.http.is_closed
    assert source.closed


def test_runtime_propagates_context_errors_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the original caller failure while closing the native pool.

    Args:
        monkeypatch: External provisioning substitution.
    """
    source = TokenMemory()
    monkeypatch.setattr(OAuthProvisioner, "open_sources", Mock(return_value=(source,)))
    asyncio.run(_context_error(source))


async def _context_error(source: TokenMemory) -> None:
    with pytest.raises(ValueError, match="original failure"):
        async with AsyncSpotifyRuntime(Settings()):
            raise ValueError("original failure")
    assert source.closed


def test_oauth_construction_preserves_scopes_paths_and_headless_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create the real SDK/cache resources without authenticating.

    Args:
        tmp_path: Isolated original cache location.
        monkeypatch: Cache-path environment override.
    """
    monkeypatch.setenv("SPOTIPY_CACHE_PATH", str(tmp_path / "primary.json"))
    configuration = Settings(app5_client_id="app5", app5_client_secret="app5-secret")
    sources = OAuthProvisioner(configuration).open_sources()
    try:
        assert [source.label for source in sources] == ["primary", "app5"]
        first, second = sources
        assert isinstance(first, OAuthSource) and isinstance(second, OAuthSource)
        assert first.manager.cache_handler.cache_path == str(tmp_path / "primary.json")
        assert second.manager.cache_handler.cache_path == str(
            tmp_path / "primary_app5.json"
        )
        assert set(first.manager.scope.split()) == set(SCOPES)
        assert first.manager.requests_timeout == 10
        assert not first.interactive
    finally:
        for source in sources:
            source.close()


def test_http_cleanup_failure_still_closes_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close credential sessions even if native HTTP cleanup fails.

    Args:
        monkeypatch: Native HTTP cleanup failure substitution.
    """
    asyncio.run(_http_close_failure(monkeypatch))


async def _http_close_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = transport_memory()
    monkeypatch.setattr(
        memory.transport.http, "aclose", AsyncMock(side_effect=OSError("close failed"))
    )
    with pytest.raises(OSError, match="close failed"):
        await memory.transport.aclose()
    assert memory.tokens[0].closed


def test_default_wait_uses_awaited_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Await positive delays without introducing a blocking wait.

    Args:
        monkeypatch: Standard-library sleep observation.
    """
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    asyncio.run(_sleep())
    sleep.assert_awaited_once_with(0.25)


async def _sleep() -> None:
    await AsyncSleep().sleep(0)
    await AsyncSleep().sleep(0.25)


def test_exit_without_enter_has_no_cleanup_side_effects() -> None:
    """Allow an unentered runtime to leave without creating resources."""
    asyncio.run(AsyncSpotifyRuntime(Settings()).__aexit__(None, None, None))


def test_failed_pool_construction_closes_provisioned_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not leak constructed SDK sessions when the HTTP pool cannot start.

    Args:
        monkeypatch: HTTPX constructor and SDK provisioning substitutions.
    """
    source = TokenMemory()
    monkeypatch.setattr(OAuthProvisioner, "open_sources", Mock(return_value=(source,)))
    monkeypatch.setattr(
        "spotify_manager.bootstrap.spotify_async.httpx.AsyncClient",
        Mock(side_effect=ValueError("bad TLS configuration")),
    )
    with pytest.raises(ValueError, match="bad TLS"):
        asyncio.run(AsyncSpotifyRuntime(Settings()).__aenter__())
    assert source.closed
