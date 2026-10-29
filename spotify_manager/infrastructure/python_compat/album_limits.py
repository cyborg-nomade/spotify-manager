"""Retain synchronous Python album_limits resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.routines.review_album_limits as source_review_album_limits


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum


class BlockingAlbumAction(Protocol):
    """Caller-owned synchronous AlbumAction resource."""

    def choose_action(
        self, album: YourLibraryAlbum, evaluation: AlbumEvaluation, /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            album: Original interaction value.
            evaluation: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonAlbumAction:
    """Await caller-owned AlbumAction I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingAlbumAction | source_review_album_limits.ActionReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_action(
        self, album: YourLibraryAlbum, evaluation: AlbumEvaluation, /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            album: Original interaction value.
            evaluation: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_action, album, evaluation)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_action(
        self, album: YourLibraryAlbum, evaluation: AlbumEvaluation, /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_action(album, evaluation)
