"""Plan composer works progression without Spotify or durable storage dependencies."""

from dataclasses import asdict

from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.discovery_progression import composer_release
from spotify_manager.domain.discovery_progression import composer_source_index
from spotify_manager.domain.discovery_progression import composer_track


def composer_step(
    source: PlaylistTrack, tracks: tuple[PlaylistTrack, ...], limit: int = 40
) -> tuple[int, PlaylistTrack | None]:
    """Advance in original playlist order until the existing works limit is reached.

    Args:
        source: Current marker.
        tracks: Original ordered works playlist, retaining duplicates.
        limit: Existing maximum number of works to review.

    Returns:
        Completed count and next marker; an unmapped source starts at the first work.

    Raises:
        NewKidsError: The matched works playlist is empty.
    """
    if not tracks:
        raise NewKidsError("The matched composer works playlist is empty.")
    index = composer_source_index(source, tracks)
    if index is None:
        return 0, tracks[0]
    completed = index + 1
    if completed >= min(limit, len(tracks)):
        return completed, None
    return completed, tracks[index + 1]


def composer_plan(
    source: PlaylistTrack,
    artist_id: str,
    artist_name: str,
    playlist: OwnedPlaylist,
    tracks: tuple[PlaylistTrack, ...],
    *,
    current_liked: bool,
    assessment: ArtistAssessment | None,
    limit: int = 40,
) -> dict[str, object]:
    """Build the original durable advance or completion plan for a works playlist.

    Args:
        source: Current works marker.
        artist_id: Logical composer identifier.
        artist_name: Logical composer display name.
        playlist: Accepted owned works playlist.
        tracks: Original complete works observations in playlist order.
        current_liked: Current marker membership observation.
        assessment: Live artist assessment required only at completion.
        limit: Existing maximum number of works to review.

    Returns:
        Original mutable plan with its unchanged field layout and action rules.

    Raises:
        NewKidsError: The matched works playlist is empty.
        NewKidsStateError: Completion requires an absent artist assessment.
    """
    completed, next_source = composer_step(source, tracks, limit)
    common: dict[str, object] = {
        "current_release": asdict(composer_release(source, artist_id, artist_name)),
        "current_liked": current_liked,
        "consecutive_unliked": 0,
        "next_prior_unliked_streak": 0,
        "composer_playlist_id": playlist.spotify_id,
        "composer_playlist_name": playlist.name,
        "composer_position": completed,
        "composer_limit": min(limit, len(tracks)),
    }
    if next_source is not None:
        return _advance(common, next_source, artist_id, artist_name)
    if assessment is None:
        raise NewKidsStateError("Composer completion plan lacks assessment.")
    return {
        **common,
        "action": "finish",
        "result_action": _finish_action(assessment),
        "target_release": None,
        "target": None,
        "assessment": asdict(assessment),
        "composer_destination_track": asdict(
            composer_track(tracks[0], artist_id, artist_name)
        ),
    }


def _advance(
    common: dict[str, object], source: PlaylistTrack, artist_id: str, artist_name: str
) -> dict[str, object]:
    return {
        **common,
        "action": "advance",
        "result_action": "advance",
        "target_release": asdict(composer_release(source, artist_id, artist_name)),
        "target": asdict(composer_track(source, artist_id, artist_name)),
        "advance_reason": "next composer work",
    }


def _finish_action(assessment: ArtistAssessment) -> str:
    if assessment.top_liked_track is None:
        return "unfollowed"
    return "great discovery" if assessment.qualifies else "unlucky"
