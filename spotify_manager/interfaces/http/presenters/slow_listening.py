"""Stable slow listening result serialization."""

from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningTrackResult,
)
from spotify_manager.routines import slow_listening


def slow_listening_track_result(
    result: slow_listening.FlushResult,
) -> SlowListeningTrackResult:
    """Convert one Slow Listening result into its stable API representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return SlowListeningTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        skipped_candidates=list(result.skipped_candidates),
        reason=result.reason,
    )
