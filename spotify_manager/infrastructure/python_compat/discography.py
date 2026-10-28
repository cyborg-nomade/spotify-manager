"""Retain synchronous Python discography resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.discography_planning as discography_ports


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingDiscographySelection(Protocol):
    """Caller-owned synchronous DiscographySelection resource."""

    def select_releases(
        self, artist: QueueArtist, releases: tuple[CatalogRelease, ...], /
    ) -> tuple[str, ...]:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            releases: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonDiscographySelection:
    """Await caller-owned DiscographySelection I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingDiscographySelection | discography_ports.ReleaseSelector

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def select_releases(
        self, artist: QueueArtist, releases: tuple[CatalogRelease, ...], /
    ) -> tuple[str, ...]:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            releases: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_select_releases, artist, releases)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_select_releases(
        self, artist: QueueArtist, releases: tuple[CatalogRelease, ...], /
    ) -> tuple[str, ...] | Awaitable[tuple[str, ...]]:
        with LegacyControl():
            return self.source.select_releases(artist, releases)
