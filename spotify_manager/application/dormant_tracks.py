"""Observe liked top tracks before falling back to the primary-credit catalog."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.dormant_artists import most_popular


class DormantCatalog(Protocol):
    """Read original artist tracks, live likes and fallback popularity."""

    def top(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Read the original eligible top tracks.

        Args:
            artist_id: Original mapped artist identity.

        Returns:
            Original ordered top tracks.
        """

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Read original live liked statuses.

        Args:
            tracks: Original observed markers.

        Returns:
            Liked membership keyed by original identity.
        """

    def tracks(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Read the original complete primary-credit catalog.

        Args:
            artist_id: Original mapped artist identity.

        Returns:
            Original ordered complete catalog markers.
        """

    def populate(self, tracks: tuple[CatalogTrack, ...]) -> tuple[CatalogTrack, ...]:
        """Read original fallback popularity facts.

        Args:
            tracks: Original filtered liked markers.

        Returns:
            Original complete markers with live popularity.
        """


def _liked(
    tracks: tuple[CatalogTrack, ...], statuses: dict[str, bool]
) -> tuple[CatalogTrack, ...]:
    result = []
    for track in tracks:
        if statuses.get(track.spotify_id, False):
            result.append(track)
    return tuple(result)


@dataclass(frozen=True)
class DormantLikedTrack:
    """Retain original top-first catalog observation and popularity order.

    Args:
        catalog: Read original primary-credit catalog, only when needed.
    """

    catalog: DormantCatalog

    def run(self, artist_id: str) -> CatalogTrack | None:
        """Select the original preferred live-liked marker.

        Returns:
            Original preferred track, or no live-liked primary-credit track.

        Raises:
            BlastFromPastArtistsError: An original liked/detail response is invalid.

        Args:
            artist_id: Original mapped artist identity.

        Returns:
            Original preferred track, or no live-liked primary-credit track.

        Raises:
            BlastFromPastArtistsError: An original liked/detail response is invalid.

        Args:
            artist_id: Original mapped artist identity.

        Returns:
            Original preferred track, or no live-liked primary-credit track.

        Raises:
            BlastFromPastArtistsError: An original liked/detail response is invalid.
        """
        top = self.catalog.top(artist_id)
        liked_top = _liked(top, self.catalog.liked(top))
        if liked_top:
            return most_popular(liked_top, True)
        catalog = self.catalog.tracks(artist_id)
        liked_catalog = _liked(catalog, self.catalog.liked(catalog))
        if not liked_catalog:
            return None
        return most_popular(self.catalog.populate(liked_catalog), False)
