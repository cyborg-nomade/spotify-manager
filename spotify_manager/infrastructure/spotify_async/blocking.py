"""Bound unavoidable OAuth/cache work without offloading Spotify API requests."""

import asyncio
from dataclasses import dataclass
from typing import Protocol


class TokenSource(Protocol):
    """Own one synchronous SDK OAuth manager and its isolated cache."""

    label: str

    def token(self) -> str:
        """Read the original cache, refreshing an expired token through the SDK.

        Returns:
            Access token for this credential set.
        """
        ...

    def refresh(self) -> None:
        """Force-refresh this credential at the original rotation boundary."""
        ...

    def close(self) -> None:
        """Close this OAuth manager's synchronous session."""
        ...


class TokenProvisioner(Protocol):
    """Construct concrete SDK/cache resources outside the event loop."""

    def open_sources(self) -> tuple[TokenSource, ...]:
        """Build configured credential sources.

        Returns:
            Sources in the original primary/app5–app8 order.
        """
        ...


@dataclass
class BlockingOAuth:
    """Bound OAuth/cache work until its underlying thread actually finishes.

    Args:
        capacity: Maximum simultaneous blocking OAuth operations.
    """

    capacity: asyncio.Semaphore

    async def token(self, source: TokenSource) -> str:
        """Read credential state without blocking the event loop.

        Args:
            source: Named OAuth/cache owner.

        Returns:
            Current access token.
        """
        async with self.capacity:
            task = asyncio.create_task(asyncio.to_thread(source.token))
            return await finish_blocking(task)

    async def refresh(self, source: TokenSource) -> None:
        """Force-refresh without adding a token read before app activation.

        Args:
            source: Named OAuth/cache owner.
        """
        async with self.capacity:
            task = asyncio.create_task(asyncio.to_thread(source.refresh))
            await finish_blocking(task)

    async def open_sources(
        self, provisioner: TokenProvisioner
    ) -> tuple[TokenSource, ...]:
        """Build SDK resources inside the same bounded blocking boundary.

        Args:
            provisioner: Named configuration owner.

        Returns:
            Ordered credential sources.
        """
        async with self.capacity:
            task = asyncio.create_task(asyncio.to_thread(provisioner.open_sources))
            try:
                return await finish_blocking(task)
            except asyncio.CancelledError as error:
                cancellation = error
        cleanup = asyncio.create_task(self._close_prepared(task))
        await finish_blocking(cleanup)
        raise cancellation

    async def _close_prepared(
        self, task: asyncio.Task[tuple[TokenSource, ...]]
    ) -> None:
        if task.cancelled() or task.exception() is not None:
            return
        for source in task.result():
            await self.close(source)

    async def close(self, source: TokenSource) -> None:
        """Finish cache/session cleanup off the event loop.

        Args:
            source: Credential owner to close.
        """
        async with self.capacity:
            task = asyncio.create_task(asyncio.to_thread(source.close))
            await finish_blocking(task)


async def finish_blocking[T](task: asyncio.Task[T]) -> T:
    """Keep capacity occupied through cancellation until blocking work is complete.

    Args:
        task: Already bounded SDK/cache operation.

    Returns:
        Original operation result.

    Raises:
        asyncio.CancelledError: After the underlying operation reaches completion.
    """
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _drain(task)
        raise


async def _drain[T](task: asyncio.Task[T]) -> None:
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            continue
    if not task.cancelled():
        task.exception()
