"""Adapt synchronous Python album recommendation choices."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.album_recommendations as recommendation_ports


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingRecommendedAlbumChoice(Protocol):
    """Caller-owned synchronous RecommendedAlbumChoice resource."""

    def choose_album(
        self,
        recommendation: AlbumRecommendation,
        options: tuple[SpotifyAlbumOption, ...],
        /,
    ) -> str:
        """Choose an edition or return the original skip/quit marker.

        Args:
            recommendation: Ranked recommendation being resolved.
            options: Ordered candidate editions.

        Returns:
            Original selected identity or control response.
        """
        ...


@dataclass(frozen=True)
class PythonRecommendedAlbumChoice:
    """Await the original caller-owned recommendation choice.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingRecommendedAlbumChoice | recommendation_ports.AlbumChoices

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_album(
        self,
        recommendation: AlbumRecommendation,
        options: tuple[SpotifyAlbumOption, ...],
        /,
    ) -> str:
        """Choose an edition or return the original skip/quit marker.

        Args:
            recommendation: Ranked recommendation being resolved.
            options: Ordered candidate editions.

        Returns:
            Original selected identity or control response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_album, recommendation, options)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_album(
        self,
        recommendation: AlbumRecommendation,
        options: tuple[SpotifyAlbumOption, ...],
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_album(recommendation, options)
