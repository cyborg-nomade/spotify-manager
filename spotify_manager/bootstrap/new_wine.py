"""Compose one complete synchronous New Wine invocation."""

from spotipy import Spotify

from spotify_manager.application.new_wine import NewWineDependencies
from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.new_wine_observations import WineObservations
from spotify_manager.application.ports.runtime import Clock
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.runtime import YearClock
from spotify_manager.application.wine_cellar import CellarWorkflow
from spotify_manager.infrastructure.legacy.new_wine import LegacyNewWine
from spotify_manager.infrastructure.legacy.wine_cellar import WineCellarAccess
from spotify_manager.interfaces.presenters.new_wine import NewWinePresenter
from spotify_manager.interfaces.presenters.wine_cellar import CellarPresenter
from spotify_manager.interfaces.requests.new_wine import NewWineCallbacks
from spotify_manager.interfaces.requests.new_wine import NewWineStorage


def new_wine_dependencies(
    client: Spotify,
    options: NewWineOptions,
    callbacks: NewWineCallbacks,
    storage: NewWineStorage,
    year: int | None,
    clock: Clock,
    local_year: YearClock,
) -> NewWineDependencies:
    """Bind the run-owned interactions and storage without executing a workflow.

    Args:
        client: Caller-owned synchronous Spotify client.
        options: Destinations and execution modes.
        callbacks: Operator decisions, notifications and retry ownership.
        storage: Namespace and persistent file locations.
        year: Review year, or the original local-year fallback.
        clock: UTC timestamp source.
        local_year: Local-calendar year source.

    Returns:
        Dependencies for the named New Wine application use case.
    """
    active_year = year or local_year.year()
    access = LegacyNewWine(
        client,
        callbacks.retry or NoRetry(),
        storage.state_path,
        storage.state_service,
        storage.log_path,
        storage.albums_path,
        storage.liked_tracks_path,
        storage.removed_albums_log_path,
    )
    cellar = CellarWorkflow(
        WineCellarAccess(
            client,
            access.retry,
            access,
            storage.log_path,
            storage.liked_tracks_path,
            storage.albums_path,
        ),
        CellarPresenter(callbacks.output),
    )
    return NewWineDependencies(
        access,
        WineObservations(access, active_year),
        cellar,
        callbacks.choose,
        callbacks.endpoint,
        NewWinePresenter(callbacks.output),
        clock,
        callbacks.progress,
    )
