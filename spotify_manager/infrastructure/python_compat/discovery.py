"""Retain synchronous Python discovery resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.ports.discovery as source_discovery


import asyncio
from collections.abc import Awaitable
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.python_compat.retry import PythonRetry
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingDiscoveryInteraction(Protocol):
    """Caller-owned synchronous DiscoveryInteraction resource."""

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Return the original synchronous retry attempts.

        Args:
            description: Original operation label for retry diagnostics.

        Returns:
            Attempt scopes retaining the caller's retry and cancellation rules.
        """
        ...

    def choose(
        self, artist: str, candidates: tuple[RankedRelease | OwnedPlaylist, ...]
    ) -> str:
        """Obtain the operator's release or composer-playlist decision.

        Args:
            artist: Reviewed artist's display name.
            candidates: Ordered choices displayed to the operator.

        Returns:
            Selected identity or the original skip/quit control value.
        """
        ...

    def echo(self, message: str) -> None:
        """Present an observation or an accepted effect.

        Args:
            message: Original complete message.
        """
        ...

    def progress(self, completed: int, total: int, detail: str) -> None:
        """Report current progress and observe cancellation.

        Args:
            completed: Original completed-entry count.
            total: Original expected-entry count.
            detail: Original current operation description.
        """
        ...


@dataclass(frozen=True)
class PythonDiscoveryInteraction:
    """Await caller-owned DiscoveryInteraction I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingDiscoveryInteraction | source_discovery.DiscoveryInteraction

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Adapt the original retry scopes without wrapping the requested operation.

        Args:
            description: Original operation label for retry diagnostics.

        Returns:
            Attempt scopes retaining the caller's retry and cancellation rules.
        """
        return PythonRetry(self.source).attempts(description)

    async def choose(
        self, artist: str, candidates: tuple[RankedRelease | OwnedPlaylist, ...]
    ) -> str:
        """Obtain the operator's release or composer-playlist decision.

        Args:
            artist: Reviewed artist's display name.
            candidates: Ordered choices displayed to the operator.

        Returns:
            Selected identity or the original skip/quit control value.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose, artist, candidates)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose(
        self, artist: str, candidates: tuple[RankedRelease | OwnedPlaylist, ...]
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose(artist, candidates)

    def echo(self, message: str) -> None:
        """Present an observation or an accepted effect.

        Args:
            message: Original complete message.
        """
        return self.source.echo(message)

    def progress(self, completed: int, total: int, detail: str) -> None:
        """Report current progress and observe cancellation.

        Args:
            completed: Original completed-entry count.
            total: Original expected-entry count.
            detail: Original current operation description.
        """
        return self.source.progress(completed, total, detail)
