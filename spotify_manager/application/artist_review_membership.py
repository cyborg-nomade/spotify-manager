"""Gather complete queue membership with original raw-page accounting."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import PlaylistMembership


@dataclass(frozen=True)
class QueueMarker:
    """Retain original independent marker identity and primary-credit observations.

    Args:
        identity: Original stripped track identity, possibly empty.
        primary: Original first credited identity, when present.
        uri: Original stripped marker URI, possibly empty.
    """

    identity: str
    primary: str | None
    uri: str


@dataclass(frozen=True)
class MembershipPage:
    """Retain original raw-row accounting alongside parsed queue marker facts.

    Args:
        markers: Original usable raw queue marker facts.
        rows: Original complete raw page size.
        has_next: Original next-page truthiness.
        total: Original integer total, including booleans, or None.
    """

    markers: tuple[QueueMarker, ...]
    rows: int
    has_next: bool
    total: int | None


def playlist_membership(
    identity: str, read: Callable[[int], MembershipPage]
) -> PlaylistMembership:
    """Gather original complete primary-credit and marker indexes in page order.

    Args:
        identity: Original queue identity for failure presentation.
        read: Original retried parsed page reader.

    Returns:
        Original complete mutable queue membership.

    Raises:
        ArtistReviewError: Original next/total authority has no raw rows.
    """
    membership = PlaylistMembership(set(), set(), {})
    offset = 0
    while True:
        page = read(offset)
        for marker in page.markers:
            _retain(membership, marker)
        offset += page.rows
        has_more = page.has_next
        if page.total is not None:
            has_more = has_more or offset < page.total
        if not has_more:
            return membership
        if not page.rows:
            raise ArtistReviewError(
                f"Spotify returned an empty playlist page for {identity}."
            )


def _retain(membership: PlaylistMembership, marker: QueueMarker) -> None:
    if marker.identity:
        membership.track_ids.add(marker.identity)
    if marker.primary is None:
        return
    membership.primary_artist_ids.add(marker.primary)
    if marker.uri:
        membership.track_uris_by_primary_artist.setdefault(marker.primary, []).append(
            marker.uri
        )
