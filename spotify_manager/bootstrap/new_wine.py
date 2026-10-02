"""Compose one complete synchronous New Wine invocation."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.new_wine import NewWineDependencies
from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.new_wine import flush_new_wine
from spotify_manager.application.new_wine_observations import WineObservations
from spotify_manager.application.new_wine_values import EndpointChoiceReader
from spotify_manager.application.new_wine_values import FlushSummary
from spotify_manager.application.new_wine_values import ReleaseChoiceReader
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.new_wine import LegacyNewWine
from spotify_manager.interfaces.presenters.new_wine import NewWinePresenter


def _direct(operation: Callable[[], object], description: str) -> object:
    return operation()


def run_new_wine(
    client: Spotify,
    options: NewWineOptions,
    choose: ReleaseChoiceReader,
    endpoint: EndpointChoiceReader | None,
    year: int | None,
    echo: Callable[[str], None],
    progress: Callable[[int, int, str], None] | None,
    retry: RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    albums_path: Path,
    liked_path: Path,
    removed_path: Path,
    clock: Callable[[], datetime],
    local_year: Callable[[], int],
) -> FlushSummary:
    """Bind original paths, callbacks and clocks before the first playlist observation.

    Args:
        client: Caller-owned synchronous Spotify client.
        options: Original destinations and invocation modes.
        choose: Release selection callback.
        endpoint: Optional album endpoint callback.
        year: Existing year override; falsey values use the original local clock.
        echo: Existing message sink.
        progress: Optional progress/cancellation callback.
        retry: Existing retry callback, defaulting to direct invocation.
        state_path: Original namespace path.
        state_service: Optional shared state service.
        log_path: Original audit destination.
        albums_path: Canonical saved-album mirror.
        liked_path: Canonical liked-track mirror.
        removed_path: Removed-album recovery log.
        clock: Original UTC timestamp source.
        local_year: Original local-calendar year source.

    Returns:
        Original public New Wine summary.
    """
    active_year = year or local_year()
    access = LegacyNewWine(
        client,
        options.destination,
        retry or _direct,
        state_path,
        state_service,
        log_path,
        albums_path,
        liked_path,
        removed_path,
        echo,
    )
    dependencies = NewWineDependencies(
        access,
        WineObservations(access, active_year),
        choose,
        endpoint,
        NewWinePresenter(echo),
        clock,
        progress,
    )
    return flush_new_wine(options, dependencies)
