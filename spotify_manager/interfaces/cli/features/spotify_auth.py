"""Spotify credential maintenance at the CLI compatibility boundary."""

import asyncio
from dataclasses import dataclass
from typing import Never
from typing import cast

import typer

from spotify_manager.client import RotatingSpotify
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.interfaces.cli.resources import CliResources


@dataclass(kw_only=True)
class SpotifyAuthCLI:
    """Refresh configured Spotify application tokens.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        rotating_client_type: Interface presentation resource.
    """

    runtime: CliResources

    rotating_client_type: type[RotatingSpotify]

    async def _refresh_spotify_tokens(self) -> None:
        """Authenticate or force-refresh every configured Spotify app token."""
        spotify = await self.runtime.review_client()
        if not isinstance(spotify, (AsyncSpotify, self.rotating_client_type)):
            raise typer.BadParameter(
                "the configured client does not support app rotation"
            )
        try:
            refreshed = await self._refresh(spotify)
        except Exception as exc:
            self._report_refresh_spotify_tokens_exception(exc)
        typer.echo(f"Spotify tokens ready: {', '.join(refreshed)}")

    async def _refresh(
        self, spotify: AsyncSpotify | RotatingSpotify
    ) -> tuple[str, ...]:
        if isinstance(spotify, AsyncSpotify):
            native = cast(AsyncSpotify, spotify)
            return await native.refresh_all_app_tokens()
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(spotify.refresh_all_app_tokens)
            )
            return await finish_blocking(task)

    def _report_refresh_spotify_tokens_exception(self, exc: Exception) -> Never:
        typer.echo(f"Spotify token refresh failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
