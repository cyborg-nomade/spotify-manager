"""Present typed Flush Mode state without observing external services."""

from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import flush_reason
from spotify_manager.interfaces.http.models.flush_mode import FlushModeStatus


def flush_status(state: FlushState) -> FlushModeStatus:
    """Expose effective mode and the freshness of retained observations.

    Args:
        state: Validated shared control and automatic decision.

    Returns:
        Stable HTTP representation with unknown counts kept explicit.
    """
    return FlushModeStatus(
        control=state.control,
        active=state.active,
        automatic_active=state.automatic_active,
        queue_tracks=state.counts.queue if state.counts else None,
        queue_2_tracks=state.counts.queue_2 if state.counts else None,
        checked_at=state.checked_at,
        attempted_at=state.attempted_at,
        error=state.error,
        reason=flush_reason(state),
    )
