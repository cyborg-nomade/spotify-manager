"""Explicit process resources shared by command adapters."""

from typing import Protocol

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.core.state.service import StateService
from spotify_manager.settings import Settings


class CliResources(Protocol):
    """Own deferred clients, configuration and durable service access."""

    async def client(self) -> Spotify:
        """Resolve the cached standard client.

        Returns:
            Caller-owned synchronous Spotify client.
        """
        ...

    async def review_client(self) -> Spotify:
        """Resolve the cached client without automatic SDK retries.

        Returns:
            Caller-owned interactive Spotify client.
        """
        ...

    async def configuration(self) -> Settings:
        """Observe current environment-backed configuration.

        Returns:
            Current settings.
        """
        ...

    async def get_state_service(self) -> StateService:
        """Resolve durable routine state.

        Returns:
            Existing shared state service.
        """
        ...

    async def get_library_data_service(self) -> LibraryDataService:
        """Resolve durable library artifacts.

        Returns:
            Existing shared artifact service.
        """
        ...
