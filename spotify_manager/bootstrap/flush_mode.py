"""Construct Flush Mode resources outside policy execution."""

from datetime import UTC
from datetime import datetime

from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.bootstrap.settings import Settings
from spotify_manager.bootstrap.state import get_state_service
from spotify_manager.infrastructure.flush_mode_counts import SpotifyQueueCounts
from spotify_manager.infrastructure.flush_mode_state import AsyncFlushModeState
from spotify_manager.infrastructure.flush_mode_state import FlushModeState


def flush_mode_state() -> FlushModeState:
    """Build the synchronous control resource without reading it.

    Returns:
        Conflict-aware owner of the dedicated shared namespace.
    """
    return FlushModeState(get_state_service())


def async_flush_mode_state() -> AsyncFlushModeState:
    """Build the async boundary for central state access.

    Returns:
        Resource finishing complete state operations off the event loop.
    """
    return AsyncFlushModeState(flush_mode_state())


def queue_counts(client: SpotifyClient) -> SpotifyQueueCounts:
    """Bind both configured queue references to an invocation-owned client.

    Args:
        client: Native Spotify client owned by the interface.

    Returns:
        Read-only total-field observer.
    """
    settings = Settings()
    return SpotifyQueueCounts(
        client, settings.the_queue_playlist, settings.the_queue_2_playlist
    )


class FlushModeClock:
    """Observe UTC at each check boundary."""

    def now(self) -> datetime:
        """Return the current aware UTC instant.

        Returns:
            Timestamp for ordering checks and successful observations.
        """
        return datetime.now(UTC)
