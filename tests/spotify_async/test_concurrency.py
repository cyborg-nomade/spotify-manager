"""Prove overlap, loop ownership and cancellation using deterministic barriers."""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from threading import Event

import httpx
import pytest

from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.infrastructure.spotify_async.transport import (
    NativeSpotifyTransport,
)
from tests.spotify_async.memory import HttpMemory
from tests.spotify_async.memory import ResponseSpec
from tests.spotify_async.memory import TokenMemory
from tests.spotify_async.memory import WaitMemory
from tests.spotify_async.memory import transport_memory


@dataclass
class PausedHttp(HttpMemory):
    """Hold HTTP requests until all expected independent reads have arrived.

    Args:
        expected: Number of requests needed to open the observation barrier.
    """

    expected: int = 2
    arrivals: int = field(default=0, init=False)
    ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    release: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        """Wait at the HTTP boundary without blocking the event loop.

        Args:
            request: Native prepared request.

        Returns:
            Scripted response after release.
        """
        self.arrivals += 1
        if self.arrivals == self.expected:
            self.ready.set()
        await self.release.wait()
        return await super().handle(request)


@dataclass
class PausedWait(WaitMemory):
    """Pause an awaited retry without sleeping a real clock."""

    ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    release: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def sleep(self, seconds: float) -> None:
        """Hold the selected backoff until released or cancelled.

        Args:
            seconds: Original delay.
        """
        self.delays.append(seconds)
        self.ready.set()
        await self.release.wait()


def test_independent_http_requests_overlap() -> None:
    """Require both requests to enter HTTP before either response is released."""
    asyncio.run(_overlap())


async def _overlap() -> None:
    http = PausedHttp()
    memory = transport_memory(http=http)
    try:
        async with asyncio.TaskGroup() as group:
            first = group.create_task(
                memory.transport.request(SpotifyRequest("GET", "albums/abc"))
            )
            second = group.create_task(
                memory.transport.request(SpotifyRequest("GET", "artists/abc"))
            )
            await asyncio.wait_for(http.ready.wait(), 3)
            assert not first.done() and not second.done()
            http.release.set()
        assert first.result() is None and second.result() is None
        assert http.arrivals == 2
    finally:
        http.release.set()
        await memory.transport.aclose()


def test_cancellation_during_http_does_not_replay_request() -> None:
    """Keep cancelled response outcomes ambiguous and close every resource."""
    asyncio.run(_cancel_http())


async def _cancel_http() -> None:
    http = PausedHttp(expected=1)
    memory = transport_memory(http=http)
    task = asyncio.create_task(
        memory.transport.request(
            SpotifyRequest("POST", "playlists/abc/items", payload=["spotify:track:abc"])
        )
    )
    await asyncio.wait_for(http.ready.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await memory.transport.aclose()
    assert http.arrivals == 1
    assert memory.transport.http.is_closed
    assert memory.tokens[0].closed


def test_cancellation_during_retry_backoff_is_prompt() -> None:
    """Stop an awaited retry without starting another HTTP attempt."""
    asyncio.run(_cancel_retry())


async def _cancel_retry() -> None:
    memory = transport_memory([ResponseSpec(503)])
    wait = PausedWait()
    memory.transport.wait = wait
    task = asyncio.create_task(memory.transport.request(SpotifyRequest("GET", "me/")))
    await asyncio.wait_for(wait.ready.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(memory.http.requests) == 1
    await memory.transport.aclose()


def test_client_rejects_cross_loop_use() -> None:
    """Keep two live loops distinct and clean up on the original owner loop."""
    with asyncio.Runner() as owner, asyncio.Runner() as foreign:
        transport = owner.run(_create_transport())
        try:
            foreign.run(_reject_foreign(transport))
        finally:
            owner.run(transport.aclose())


async def _create_transport() -> NativeSpotifyTransport:
    return transport_memory().transport


async def _reject_foreign(transport: NativeSpotifyTransport) -> None:
    with pytest.raises(RuntimeError, match="another event loop"):
        await transport.request(SpotifyRequest("GET", "me/"))
    with pytest.raises(RuntimeError, match="another event loop"):
        await transport.aclose()


def test_closed_transport_is_not_reused_and_cleanup_is_idempotent() -> None:
    """Reject requests after cleanup while allowing repeated close calls."""
    asyncio.run(_closed())


async def _closed() -> None:
    memory = transport_memory()
    await asyncio.gather(memory.transport.aclose(), memory.transport.aclose())
    await memory.transport.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await memory.transport.request(SpotifyRequest("GET", "me/"))
    assert memory.transport.http.is_closed
    assert memory.tokens[0].closed


@dataclass
class BrokenClose(TokenMemory):
    """Fail cleanup after recording that the original source was closed."""

    def close(self) -> None:
        """Raise the original session cleanup failure.

        Raises:
            OSError: Simulated external cleanup failure.
        """
        super().close()
        raise OSError("cache close failed")


def test_cleanup_closes_remaining_sources_after_one_failure() -> None:
    """Do not leak later OAuth owners when an earlier session close fails."""
    asyncio.run(_broken_cleanup())


async def _broken_cleanup() -> None:
    tokens = (BrokenClose(), TokenMemory("app5"))
    memory = transport_memory(tokens=tokens)
    with pytest.raises(OSError, match="cache close failed"):
        await memory.transport.aclose()
    assert all(token.closed for token in tokens)
    assert memory.transport.http.is_closed


@dataclass
class PausedClose(TokenMemory):
    """Hold cleanup long enough to observe cancellation and closing state."""

    started: Event = field(default_factory=Event, init=False)
    release: Event = field(default_factory=Event, init=False)

    def close(self) -> None:
        """Complete session cleanup after the test releases the barrier."""
        self.started.set()
        assert self.release.wait(timeout=5)
        super().close()


def test_shutdown_finishes_even_when_its_caller_is_cancelled() -> None:
    """Reject new requests while closing and finish cleanup before cancellation."""
    asyncio.run(_cancel_close())


async def _cancel_close() -> None:
    from spotify_manager.application.ports.spotify_async import SpotifyRequest

    source = PausedClose()
    memory = transport_memory(tokens=(source,))
    task = asyncio.create_task(memory.transport.aclose())
    await asyncio.to_thread(source.started.wait)
    with pytest.raises(RuntimeError, match="closing"):
        await memory.transport.request(SpotifyRequest("GET", "me/"))
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    source.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert source.closed
    assert memory.transport.http.is_closed


@dataclass
class PausedTokenRead(TokenMemory):
    """Pause a cache read while allowing its rotation refresh to complete."""

    started: Event = field(default_factory=Event, init=False)
    release: Event = field(default_factory=Event, init=False)

    def token(self) -> str:
        """Read the selected token after observing a concurrent rotation.

        Returns:
            The originally selected credential's token.
        """
        self.started.set()
        assert self.release.wait(timeout=5)
        return super().token()


def test_connection_retry_keeps_its_credential_during_another_requests_rotation() -> (
    None
):
    """Do not silently switch an in-flight request's credential on a GET retry."""
    asyncio.run(_stable_credential())


async def _stable_credential() -> None:

    source = PausedTokenRead("app5")
    memory = transport_memory(
        [
            ResponseSpec(429),
            ResponseSpec(error=httpx.ReadError("reset")),
            ResponseSpec(payload={"ok": True}),
        ],
        (TokenMemory(), source, TokenMemory("app6")),
    )
    task = asyncio.create_task(memory.transport.request(SpotifyRequest("GET", "me/")))
    try:
        await asyncio.to_thread(source.started.wait)
        previous = 1
        assert await memory.transport.credentials.rotate(previous, {0, 1})
        source.release.set()
        assert await task == {"ok": True}
        tokens = [request.headers["Authorization"] for request in memory.http.requests]
        assert tokens == [
            "Bearer primary-token",
            "Bearer app5-token",
            "Bearer app5-token",
        ]
    finally:
        source.release.set()
        await task
        await memory.transport.aclose()
