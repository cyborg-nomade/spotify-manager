"""Compose the complete Requeue use case without owning its caller's client."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import Clock
from spotify_manager.application.ports.listening import MessageSink
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.requeue import RequeueDependencies
from spotify_manager.bootstrap.listening import requeue_audit
from spotify_manager.infrastructure.legacy.spotify import RequeuePlaylistAccess
from spotify_manager.infrastructure.legacy.spotify import SpotifyRequeueCatalog


def requeue_dependencies(
    client: Spotify,
    retry: RetryCall,
    echo: MessageSink,
    progress: MessageSink | None,
    log_path: Path,
    clock: Clock,
) -> RequeueDependencies:
    """Bind the existing integrations to one invocation's explicit dependencies.

    Args:
        client: Existing synchronous client with caller-owned callbacks.
        retry: Original retry and cancellation behavior.
        echo: Existing mutation message sink.
        progress: Existing progress sink, when enabled.
        log_path: Original audit destination.
        clock: Timestamp source used at the original result boundary.

    Returns:
        Dependencies for the complete application use case.
    """
    return RequeueDependencies(
        RequeuePlaylistAccess(client, retry),
        SpotifyRequeueCatalog(client, retry),
        echo,
        progress,
        requeue_audit(log_path),
        clock,
    )
