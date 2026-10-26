"""Prove cache compatibility, per-credential refresh and bounded cancellation."""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import Mock

import pytest
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.client import SpotifyAppAuthenticationError
from spotify_manager.infrastructure.spotify_async.blocking import BlockingOAuth
from spotify_manager.infrastructure.spotify_async.credentials import Credential
from spotify_manager.infrastructure.spotify_async.credentials import Credentials
from spotify_manager.infrastructure.spotify_async.oauth import SCOPES
from spotify_manager.infrastructure.spotify_async.oauth import OAuthSource
from tests.spotify_async.memory import ResponseSpec
from tests.spotify_async.memory import TokenMemory
from tests.spotify_async.memory import transport_memory


@dataclass
class RefreshMemory:
    """Refresh an actual SDK cache through a scripted external authentication edge.

    Args:
        cache: Real SDK cache in isolated fixture storage.
    """

    cache: CacheFileHandler
    refreshes: list[str] = field(default_factory=list)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Publish the original OAuth mapping format after one refresh.

        Args:
            refresh_token: Original refresh credential.

        Returns:
            Valid SDK token metadata.
        """
        self.refreshes.append(refresh_token)
        token = _token(10**12)
        self.cache.save_token_to_cache(token)
        return token


def _oauth(
    path: Path, token: dict[str, Any] | None
) -> tuple[SpotifyOAuth, RefreshMemory]:
    cache = CacheFileHandler(cache_path=str(path / "token.json"))
    if token is not None:
        cache.save_token_to_cache(token)
    manager = SpotifyOAuth(
        client_id="id", client_secret="secret", scope=list(SCOPES), cache_handler=cache
    )
    refresh = RefreshMemory(cache)
    manager.refresh_access_token = Mock(side_effect=refresh.refresh)
    return manager, refresh


def _token(expires: int) -> dict[str, Any]:
    return {
        "access_token": "access",
        "refresh_token": "refresh",
        "scope": " ".join(SCOPES),
        "expires_at": expires,
    }


def test_expired_token_refresh_is_coordinated_for_concurrent_reads(
    tmp_path: Path,
) -> None:
    """Require the real SDK validation to refresh once for simultaneous reads.

    Args:
        tmp_path: Isolated SDK cache location.
    """
    manager, refresh = _oauth(tmp_path, _token(0))
    asyncio.run(_refresh_once(manager, refresh))


async def _refresh_once(manager: SpotifyOAuth, refresh: RefreshMemory) -> None:
    credential = Credential(
        OAuthSource("primary", manager), BlockingOAuth(asyncio.Semaphore(2))
    )
    try:
        result = await asyncio.gather(
            credential.token(), credential.token(), credential.token()
        )
        assert list(result) == ["access", "access", "access"]
        assert refresh.refreshes == ["refresh"]
    finally:
        await credential.close()


@pytest.mark.parametrize("token", [None, {"access_token": "access"}])
def test_headless_rotation_keeps_original_missing_cache_errors(
    token: dict[str, Any] | None,
    tmp_path: Path,
) -> None:
    """Retain distinct absent-cache and absent-refresh-token failures.

    Args:
        token: Original unusable cache response.
        tmp_path: Isolated SDK cache location.
    """
    manager, _refresh = _oauth(tmp_path, token)
    source = OAuthSource("app5", manager)
    try:
        with pytest.raises(SpotifyAppAuthenticationError) as caught:
            source.refresh()
        assert (
            "no headless token cache" in str(caught.value)
            if token is None
            else "no refresh token" in str(caught.value)
        )
    finally:
        source.close()


@dataclass
class BlockingToken(TokenMemory):
    """Hold a real blocking worker until the test releases its cache operation."""

    started: Event = field(default_factory=Event, init=False)
    release: Event = field(default_factory=Event, init=False)

    def token(self) -> str:
        """Complete a token read after releasing its blocking operation.

        Returns:
            Original selected access token.
        """
        self._wait_for_release()
        return super().token()

    def refresh(self) -> None:
        """Complete a force refresh after releasing its blocking operation."""
        self._wait_for_release()
        super().refresh()

    def _wait_for_release(self) -> None:
        self.started.set()
        assert self.release.wait(timeout=5)


def test_cancelled_worker_retains_capacity_until_underlying_cache_write_finishes() -> (
    None
):
    """Cancellation cannot release capacity while its blocking work is running."""
    asyncio.run(_bounded_cancellation())


async def _bounded_cancellation() -> None:
    blocking = BlockingOAuth(asyncio.Semaphore(1))
    first = BlockingToken()
    second = TokenMemory("app5")
    task = asyncio.create_task(blocking.token(first))
    await asyncio.to_thread(first.started.wait)
    task.cancel()
    following = asyncio.create_task(blocking.token(second))
    try:
        await asyncio.sleep(0)
        assert second.calls == []
        assert not task.done()
    finally:
        first.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await following == "app5-token"
    assert second.calls == [False]


def test_refresh_of_one_credential_does_not_lock_another() -> None:
    """Keep credential locks independent while a refresh is blocked."""
    asyncio.run(_independent_credentials())


async def _independent_credentials() -> None:
    blocking = BlockingOAuth(asyncio.Semaphore(2))
    source = BlockingToken()
    first = Credential(source, blocking)
    second = Credential(TokenMemory("app5"), blocking)
    task = asyncio.create_task(first.refresh())
    await asyncio.to_thread(source.started.wait)
    try:
        assert await asyncio.wait_for(second.token(), 2) == "app5-token"
        assert not task.done()
    finally:
        source.release.set()
        await task
        await first.close()
        await second.close()


@dataclass
class PausedProvisioner:
    """Hold SDK/cache construction until cancellation has been requested.

    Args:
        source: Newly constructed credential resource.
    """

    source: TokenMemory
    started: Event = field(default_factory=Event, init=False)
    release: Event = field(default_factory=Event, init=False)

    def open_sources(self) -> tuple[TokenMemory, ...]:
        """Return a constructed credential after the observation barrier.

        Returns:
            Credential whose ownership must survive cancelled construction.
        """
        self.started.set()
        assert self.release.wait(timeout=5)
        return (self.source,)


def test_cancelled_provisioning_closes_unclaimed_sources() -> None:
    """Do not leak credentials returned after their caller was cancelled."""
    asyncio.run(_cancel_prepare())


async def _cancel_prepare() -> None:
    blocking = BlockingOAuth(asyncio.Semaphore(1))
    provisioner = PausedProvisioner(TokenMemory())
    task = asyncio.create_task(blocking.open_sources(provisioner))
    await asyncio.to_thread(provisioner.started.wait)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    provisioner.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provisioner.source.closed


def test_cancelled_child_task_is_drained_without_reading_its_result() -> None:
    """Handle a cancelled worker future without hiding cancellation."""
    asyncio.run(_cancel_child())


async def _cancel_child() -> None:
    from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking

    task = asyncio.create_task(asyncio.sleep(0))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finish_blocking(task)


def test_force_refresh_retains_the_original_cache_format(tmp_path: Path) -> None:
    """Refresh an already valid token using the existing on-disk SDK format.

    Args:
        tmp_path: Isolated SDK cache location.
    """
    manager, refresh = _oauth(tmp_path, _token(10**12))
    source = OAuthSource("app5", manager)
    try:
        source.refresh()
        assert source.token() == "access"
        assert refresh.refreshes == ["refresh"]
        assert manager.cache_handler.get_cached_token() == _token(10**12)
    finally:
        source.close()


def test_interactive_rotation_without_cache_keeps_sdk_authentication_calls(
    tmp_path: Path,
) -> None:
    """Allow the same local interactive fallback only when explicitly selected.

    Args:
        tmp_path: Isolated missing-cache location.
    """
    from unittest.mock import call

    manager, _refresh = _oauth(tmp_path, None)
    access = Mock(side_effect=[_token(10**12), "access"])
    manager.get_access_token = access
    source = OAuthSource("app5", manager, interactive=True)
    try:
        source.refresh()
        assert source.token() == "access"
        assert access.call_args_list == [
            call(as_dict=True, check_cache=True),
            call(as_dict=False),
        ]
    finally:
        source.close()


def test_partial_provisioning_failure_closes_earlier_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release earlier OAuth owners when a later cache cannot be created.

    Args:
        monkeypatch: External cache-construction failure substitution.
    """
    from spotify_manager.infrastructure.spotify_async.oauth import OAuthProvisioner
    from spotify_manager.settings import Settings

    source = TokenMemory()
    monkeypatch.setattr(
        OAuthProvisioner,
        "_source",
        Mock(side_effect=[source, OSError("cache directory unavailable")]),
    )
    configuration = Settings(app5_client_id="app5", app5_client_secret="secret")
    with pytest.raises(OSError, match="cache directory"):
        OAuthProvisioner(configuration).open_sources()
    assert source.closed


def test_cancelled_failed_provisioning_preserves_cancellation() -> None:
    """Do not replace cancellation with a background provisioning error."""
    asyncio.run(_cancel_failed_prepare())


@dataclass
class FailedProvisioner(PausedProvisioner):
    """Fail after a paused blocking construction instead of returning resources."""

    def open_sources(self) -> tuple[TokenMemory, ...]:
        """Expose a failing external construction boundary.

        Raises:
            ValueError: Original invalid configuration.
        """
        super().open_sources()
        raise ValueError("invalid configuration")


async def _cancel_failed_prepare() -> None:
    blocking = BlockingOAuth(asyncio.Semaphore(1))
    provisioner = FailedProvisioner(TokenMemory())
    task = asyncio.create_task(blocking.open_sources(provisioner))
    await asyncio.to_thread(provisioner.started.wait)
    task.cancel()
    provisioner.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@dataclass
class ActiveTokenRead:
    """Observe the selected app at the SDK's original token-read boundary.

    Args:
        credentials: Native credential pool under test.
    """

    credentials: Credentials
    selected: list[int] = field(default_factory=list)

    def read(self, **kwargs: object) -> str:
        """Read once after the alternate app has become active.

        Args:
            **kwargs: Original SDK access-token options.

        Returns:
            Synthetic alternate app token.
        """
        assert kwargs == {"as_dict": False}
        self.selected.append(self.credentials.active)
        return "app5-token"


def test_rotation_reads_token_once_after_publishing_the_active_app(
    tmp_path: Path,
) -> None:
    """Retain original refresh, app activation and token-read order.

    Args:
        tmp_path: Isolated original SDK cache.
    """
    manager, refresh = _oauth(tmp_path, _token(10**12))
    asyncio.run(_rotation_read_order(manager, refresh))


async def _rotation_read_order(manager: SpotifyOAuth, refresh: RefreshMemory) -> None:
    memory = transport_memory(
        [ResponseSpec(429), ResponseSpec(payload={"ok": True})],
        (TokenMemory(), TokenMemory("app5")),
    )
    memory.transport.credentials.entries[1].source = OAuthSource("app5", manager)
    observed = ActiveTokenRead(memory.transport.credentials)
    manager.get_access_token = Mock(side_effect=observed.read)
    try:
        assert await memory.transport.request(SpotifyRequest("GET", "me/")) == {
            "ok": True
        }
        assert refresh.refreshes == ["refresh"]
        assert observed.selected == [1]
    finally:
        await memory.transport.aclose()
