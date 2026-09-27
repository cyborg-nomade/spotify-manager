"""Release classification and composer marker identities for discovery review."""

import re
from dataclasses import replace

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import name_tokens
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery import ReleaseTier
from spotify_manager.domain.releases import release_identity


LIVE_PATTERN = re.compile(
    r"(?:\blive\b|ao vivo|en vivo|in concert|unplugged|concert)", re.IGNORECASE
)
DECORATED_PATTERN = re.compile(
    r"(?:deluxe|expanded|anniversary|remaster|reissue|special edition|bonus)",
    re.IGNORECASE,
)


def release_kind(
    raw_type: object, total_tracks: int, name: str
) -> tuple[str, ReleaseTier]:
    """Classify a release using the existing discovery-tier precedence.

    Args:
        raw_type: Original Spotify or compatibility release classification.
        total_tracks: Observed track count for EP/single differentiation.
        name: Release title inspected for live-work qualifiers.

    Returns:
        Original display classification and discovery preference tier.
    """
    normalized = str(raw_type or "").casefold()
    if normalized == "compilation":
        return "Compilation", 3
    if LIVE_PATTERN.search(name):
        return "Live", 2
    if normalized == "album":
        return "Album", 0
    if normalized == "ep" or (normalized == "single" and total_tracks >= 4):
        return "EP", 0
    return "Single", 1


def source_release(source: PlaylistTrack) -> RankedRelease:
    """Adapt an existing playlist marker's release into the discovery catalog.

    Args:
        source: Original marker, retaining its track-level primary credit.

    Returns:
        Unsaved, unranked catalog value with the original title policies.
    """
    kind, tier = release_kind(
        source.release.release_type, source.release.total_tracks, source.release.name
    )
    return RankedRelease(
        source.release.spotify_id,
        source.release.uri,
        source.release.name,
        kind,
        source.release.release_date,
        source.release.total_tracks,
        source.primary_artist_id,
        source.primary_artist_name,
        None,
        None,
        tier,
        release_identity(source.release.name),
        False,
        not DECORATED_PATTERN.search(source.release.name),
    )


def composer_release(
    source: PlaylistTrack, artist_id: str, artist_name: str
) -> RankedRelease:
    """Attribute a works marker's release to the selected logical composer.

    Args:
        source: Original performer-credited marker.
        artist_id: Logical composer identifier.
        artist_name: Logical composer display name.

    Returns:
        Original source release with only the logical primary credit replaced.
    """
    return replace(
        source_release(source),
        primary_artist_id=artist_id,
        primary_artist_name=artist_name,
    )


def composer_track(
    source: PlaylistTrack, artist_id: str, artist_name: str
) -> CatalogTrack:
    """Adapt a works marker to the original durable catalog-track layout.

    Args:
        source: Original works-playlist marker.
        artist_id: Logical composer identifier.
        artist_name: Logical composer display name.

    Returns:
        Marker assigned to the logical composer at the original default position.
    """
    return CatalogTrack(
        source.spotify_id, source.uri, source.name, 1, 1, artist_id, artist_name
    )


def composer_source_index(
    source: PlaylistTrack, tracks: tuple[PlaylistTrack, ...]
) -> int | None:
    """Locate a works marker by ID, then by one unique token-normalized title.

    Args:
        source: Current source marker.
        tracks: Original owned-playlist order, retaining duplicates.

    Returns:
        First matching ID or unique normalized-title position, otherwise None.
    """
    for index, track in enumerate(tracks):
        if track.spotify_id == source.spotify_id:
            return index
    source_tokens = name_tokens(source.name)
    matches = []
    for index, track in enumerate(tracks):
        if name_tokens(track.name) == source_tokens:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None
