"""Observe future records in order and retain original caller-owned cache updates."""

from collections.abc import Callable

from spotify_manager.domain.release_check import contains_single
from spotify_manager.domain.release_check import normalized_track_title
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


def matching_future_record(
    load_tracks: Callable[[ReleaseCandidate], tuple[ReleaseTrack, ...]],
    single_track: ReleaseTrack,
    future_releases: tuple[ReleaseCandidate, ...],
    track_cache: dict[str, tuple[ReleaseTrack, ...]] | None = None,
) -> ReleaseCandidate | None:
    """Return the first original matching announced record, caching each accepted read.

    Args:
        load_tracks: Original ordered album-track observation.
        single_track: Original selected single marker.
        future_releases: Original ordered eligible announced records.
        track_cache: Optional caller-owned original track cache.

    Returns:
        First original matching record or no match.

    Raises:
        ReleaseCheckSpotifyError: Original track observation is unusable.
    """
    cached = track_cache if track_cache is not None else {}
    expected_name = normalized_track_title(single_track.name)
    for release in future_releases:
        tracks = cached.get(release.spotify_id)
        if tracks is None:
            tracks = load_tracks(release)
            cached[release.spotify_id] = tracks
        if contains_single(single_track.spotify_id, expected_name, tracks):
            return release
    return None
