"""Canonical edition preference and deterministic discovery catalog ranking."""

from collections import defaultdict

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery import ReleaseTier
from spotify_manager.domain.releases import review_date_key


type ReleaseDateKey = tuple[int, int, int, str]


def canonical_releases(
    candidates: tuple[RankedRelease, ...],
) -> tuple[RankedRelease, ...]:
    """Select one edition per identity/tier before applying discovery review order.

    Args:
        candidates: Parsed primary-credit releases in original observation order.

    Returns:
        Canonical releases with saved/plain edition preference and original rank ties.
    """
    editions: dict[tuple[str, ReleaseTier], list[RankedRelease]] = defaultdict(list)
    for candidate in candidates:
        editions[(candidate.identity, candidate.tier)].append(candidate)
    canonical = []
    for group in editions.values():
        canonical.append(min(group, key=_edition_key))
    return tuple(sorted(canonical, key=_review_key))


def _edition_key(
    release: RankedRelease,
) -> tuple[bool, bool, int, int, int, int, ReleaseDateKey, str]:
    return (
        not release.saved,
        not release.plain,
        release.tier,
        -(release.popularity if release.popularity is not None else -1),
        release.top_track_rank or 9999,
        release.total_tracks,
        review_date_key(release.release_date),
        release.name.casefold(),
    )


def _review_key(
    release: RankedRelease,
) -> tuple[int, bool, int, int, ReleaseDateKey, str, str]:
    return (
        release.tier,
        release.popularity is None,
        -(release.popularity or 0),
        release.top_track_rank or 9999,
        review_date_key(release.release_date),
        release.name.casefold(),
        release.spotify_id,
    )


def ordered_catalog_tracks(
    tracks: tuple[CatalogTrack, ...],
) -> tuple[CatalogTrack, ...]:
    """Order catalog tracks by disc and track position with stable duplicate ties.

    Args:
        tracks: Parsed release tracks in original page order.

    Returns:
        Original values ordered by disc/track position without deduplication.
    """
    return tuple(sorted(tracks, key=_track_position))


def _track_position(track: CatalogTrack) -> tuple[int, int]:
    return track.disc_number, track.track_number
