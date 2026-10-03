"""Stable releases result serialization."""

from spotify_manager.interfaces.http.models.releases import ReleaseCheckResultEntry
from spotify_manager.interfaces.operations import release_check as release_check


def release_check_result(
    result: release_check.ReleaseCheckResult,
) -> ReleaseCheckResultEntry:
    """Convert one release-check decision into its API representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return ReleaseCheckResultEntry(
        artist=result.artist,
        artist_rank=result.artist_rank,
        artist_scrobbles=result.artist_scrobbles,
        spotify_artist_id=result.spotify_artist_id,
        release_id=result.release_id,
        release=result.release,
        release_type=result.release_type,
        release_date=result.release_date,
        first_track_id=result.first_track_id,
        first_track=result.first_track,
        linked_future_release=result.linked_future_release,
        wine_cellar_action=result.wine_cellar_action,
        new_vintage_action=result.new_vintage_action,
        reason=result.reason,
        dry_run=result.dry_run,
    )
