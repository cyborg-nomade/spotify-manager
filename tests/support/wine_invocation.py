"""Retain legacy fixture observations across the typed New Wine interface."""

from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from inspect import isawaitable

from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.new_wine_values import FlushSummary
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.requests.new_wine import NewWineCallbacks
from spotify_manager.interfaces.requests.new_wine import NewWineStorage


@dataclass(frozen=True)
class WineInvocation:
    """Adapt an existing fixture oracle without changing its observed behavior.

    Args:
        operation: Existing synthetic choice, retry or error fixture.
    """

    operation: Callable[..., FlushSummary | Awaitable[FlushSummary]]

    async def __call__(
        self,
        client: Spotify,
        options: NewWineOptions,
        callbacks: NewWineCallbacks,
        storage: NewWineStorage | None = None,
        year: int | None = None,
    ) -> FlushSummary:
        """Expose the same fixture inputs from the cohesive production records.

        Args:
            client: Synthetic Spotify client.
            options: Destinations and execution modes.
            callbacks: Real worker-owned interaction callbacks.
            storage: Optional isolated persistence locations.
            year: Optional review-year override.

        Returns:
            The original fixture outcome.

        Raises:
            RuntimeError: The scripted failure occurs at its original boundary.
        """
        result = self.operation(
            client,
            options.destination,
            options.sauvignon,
            choice_reader=callbacks.choose,
            endpoint_choice_reader=callbacks.endpoint,
            wine_cellar_playlist_id=options.cellar,
            no_discovery=options.no_discovery,
            choose_album_endpoints=options.endpoint_mode,
            dry_run=options.dry_run,
            echo=callbacks.output,
            progress_callback=callbacks.progress,
            retry_call=callbacks.retry,
        )

        if isawaitable(result):
            return await result
        return result
