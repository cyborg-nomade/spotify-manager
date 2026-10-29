"""Retain synchronous Python catalog resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.artist_review_membership as membership_ports
    import spotify_manager.infrastructure.genre_pages as source_genre_pages


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.artist_review_values import PlaylistMembership
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingMembership(Protocol):
    """Caller-owned synchronous Membership resource."""

    def membership(self, identity: str) -> PlaylistMembership:
        """Read or reuse complete membership.

        Args:
            identity: Queue identity.

        Returns:
            Complete mutable membership indexes.
        """
        ...


@dataclass(frozen=True)
class PythonMembership:
    """Await caller-owned Membership I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingMembership | membership_ports.MembershipAccess

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def membership(self, identity: str) -> PlaylistMembership:
        """Read or reuse complete membership.

        Args:
            identity: Queue identity.

        Returns:
            Complete mutable membership indexes.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_membership, identity)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_membership(
        self, identity: str
    ) -> PlaylistMembership | Awaitable[PlaylistMembership]:
        with LegacyControl():
            return self.source.membership(identity)


class BlockingGenrePages(Protocol):
    """Caller-owned synchronous GenrePages resource."""

    def read(self, url: str) -> str:
        """Read complete public HTML.

        Args:
            url: Original public source URL.

        Returns:
            Complete decoded page.
        """
        ...


@dataclass(frozen=True)
class PythonGenrePages:
    """Await caller-owned GenrePages I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingGenrePages | source_genre_pages.GenrePages

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def read(self, url: str) -> str:
        """Read complete public HTML.

        Args:
            url: Original public source URL.

        Returns:
            Complete decoded page.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_read, url))
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_read(self, url: str) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.read(url)
