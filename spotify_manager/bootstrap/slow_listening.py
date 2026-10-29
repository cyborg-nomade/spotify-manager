"""Compose synchronous Slow Listening integrations for one invocation."""

from pathlib import Path

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.runtime import Clock
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.runtime import ReviewProgress
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
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


class AutomaticAdvance:
    """Accept the existing default track advance without prompting."""

    async def choose_track(
        self, source: PlaylistTrack, target: ReleaseTrack, release: DiscographyRelease
    ) -> str:
        """Return the default action when no operator interaction was supplied.

        Args:
            source: Original marker.
            target: Proposed successor.
            release: Successor's release.

        Returns:
            The original advance action.
        """
        return "advance"


def slow_listening_dependencies(
    client: Spotify,
    playlist_id: str,
    order: ReleaseOrderReader,
    complete: CompletionNotifier,
    action: TrackActionReader | None,
    echo: Messages,
    progress: ReviewProgress | None,
    retry: RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    clock: Clock,
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
        client,
        playlist_id,
        retry or NoRetry(),
        state_path,
        state_service,
        log_path,
    )
    dependencies = SlowListeningDependencies(
        access,
        StudioObservations(access),
        order,
        action or AutomaticAdvance(),
        complete,
        SlowListeningPresenter(echo),
        clock,
        progress,
    )
    return dependencies
