"""Compose synchronous Slow Listening integrations for one invocation."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.slow_listening import SlowListeningDependencies
from spotify_manager.application.slow_listening_plan import StudioObservations
from spotify_manager.application.slow_listening_values import CompletionNotifier
from spotify_manager.application.slow_listening_values import ReleaseOrderReader
from spotify_manager.application.slow_listening_values import TrackActionReader
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.legacy.slow_listening import LegacySlowListening
from spotify_manager.interfaces.presenters.slow_listening import SlowListeningPresenter


def _direct(operation: Callable[[], object], description: str) -> object:
    return operation()


def _advance(
    source: PlaylistTrack, target: ReleaseTrack, release: DiscographyRelease
) -> str:
    return "advance"


def slow_listening_dependencies(
    client: Spotify,
    playlist_id: str,
    order: ReleaseOrderReader,
    complete: CompletionNotifier,
    action: TrackActionReader | None,
    echo: Callable[[str], None],
    progress: Callable[[int, int, str], None] | None,
    retry: RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    clock: Callable[[], datetime],
) -> SlowListeningDependencies:
    """Construct the invocation dependencies without executing the use case.

    Args:
        client: Caller-owned Spotify client.
        playlist_id: Configured destination.
        order: Operator's tie ordering callback.
        complete: Completion acknowledgement callback.
        action: Optional track choice callback; defaults to advance.
        echo: Existing message sink.
        progress: Optional progress/cancellation callback.
        retry: Optional existing retry policy; defaults to direct invocation.
        state_path: Original namespace path.
        state_service: Optional explicit shared state service.
        log_path: Original audit destination.
        clock: Original UTC timestamp source.

    Returns:
        The configured application dependencies or workflow.
    """
    access = LegacySlowListening(
        client, playlist_id, retry or _direct, state_path, state_service, log_path
    )
    dependencies = SlowListeningDependencies(
        access,
        StudioObservations(access),
        order,
        action or _advance,
        complete,
        SlowListeningPresenter(echo),
        clock,
        progress,
    )
    return dependencies
