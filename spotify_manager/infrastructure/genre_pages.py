"""Named public-page access and the retained external Python reader hook."""

import asyncio
from typing import Protocol

from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


class GenrePages(Protocol):
    """Read Every Noise and Spotify embed pages."""

    async def read(self, url: str) -> str:
        """Read complete public HTML.

        Args:
            url: Original public source URL.

        Returns:
            Complete decoded page.
        """
        ...


class PublicGenrePages:
    """Read public pages through the original HTTP implementation."""

    async def read(self, url: str) -> str:
        """Read complete public HTML.

        Args:
            url: Original source URL.

        Returns:
            Complete decoded page.
        """
        from spotify_manager.routines.genre_reveal import (
            read_public_page as _read_public_page,
        )

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_read_public_page, url)
            )
            return await finish_blocking(file_operation)


PUBLIC_GENRE_PAGES = PublicGenrePages()
