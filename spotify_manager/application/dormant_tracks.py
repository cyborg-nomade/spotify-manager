"""Observe liked top tracks before falling back to the primary-credit catalog."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.dormant_artists import most_popular


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
        top: Read original top tracks.
        liked: Observe live liked membership, including empty batches.
        catalog: Read original primary-credit catalog, only when needed.
        populate: Read original liked-track popularity details.
    """

    top: Callable[[], tuple[CatalogTrack, ...]]
    liked: Callable[[tuple[CatalogTrack, ...]], dict[str, bool]]
    catalog: Callable[[], tuple[CatalogTrack, ...]]
    populate: Callable[[tuple[CatalogTrack, ...]], tuple[CatalogTrack, ...]]

    def run(self) -> CatalogTrack | None:
        """Select the original preferred live-liked marker.

        Returns:
            Original preferred track, or no live-liked primary-credit track.

        Raises:
            BlastFromPastArtistsError: An original liked/detail response is invalid.
        """
        top = self.top()
        liked_top = _liked(top, self.liked(top))
        if liked_top:
            return most_popular(liked_top, True)
        catalog = self.catalog()
        liked_catalog = _liked(catalog, self.liked(catalog))
        if not liked_catalog:
            return None
        return most_popular(self.populate(liked_catalog), False)
