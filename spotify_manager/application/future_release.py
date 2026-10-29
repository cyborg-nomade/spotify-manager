"""Observe future records in order and retain original caller-owned cache updates."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.release_check import contains_single
from spotify_manager.domain.release_check import normalized_track_title
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


class ReleaseTracks(Protocol):
    """Observe complete future-release track lists through a named catalog."""

    async def read(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Read original release tracks in response order.

        Args:
            release: Original announced release.

        Returns:
            Original complete playable release tracks.
        """


@dataclass(frozen=True)
class FutureRecordMatching:
    """Own the named containing-record stage and its concrete catalog boundary.

    Args:
        catalog: Original ordered release-track observations.
    """

    catalog: ReleaseTracks

    async def run(
        self,
        track: ReleaseTrack,
        records: tuple[ReleaseCandidate, ...],
        cache: dict[str, tuple[ReleaseTrack, ...]] | None = None,
    ) -> ReleaseCandidate | None:
        """Find the original first containing record with the caller-owned cache.

        Args:
            track: Original single marker.
            records: Original ordered eligible records.
            cache: Shared accepted release-track observations.

        Returns:
            Original first match or no containing record.
        """
        return await matching_future_record(self.catalog, track, records, cache)


async def matching_future_record(
    catalog: ReleaseTracks,
    single_track: ReleaseTrack,
    future_releases: tuple[ReleaseCandidate, ...],
    track_cache: dict[str, tuple[ReleaseTrack, ...]] | None = None,
) -> ReleaseCandidate | None:
    """Return the first original matching announced record, caching each accepted read.

    Args:
        catalog: Named external catalog observations used by this stage.
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
            tracks = await catalog.read(release)
            cached[release.spotify_id] = tracks
        if contains_single(single_track.spotify_id, expected_name, tracks):
            return release
    return None
