"""Stable something old result serialization."""

from spotify_manager.interfaces.http.models.something_old import SomethingOldTrackResult
from spotify_manager.interfaces.operations import something_old as something_old


def something_old_track_result(
    track: something_old.SelectedTrack,
) -> SomethingOldTrackResult:
    """Convert one Something Old selection into its API representation.

    Args:
        track: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return SomethingOldTrackResult(
        spotify_id=track.spotify_id,
        track=track.track,
        album=track.album,
        artists=list(track.artists),
        source=track.source,
        lastfm_scrobbles=track.lastfm_scrobbles,
    )
