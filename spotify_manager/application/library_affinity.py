"""Observe existing library affinity with the original early-stop thresholds."""

from collections.abc import Callable
from typing import Protocol


class ArtistMembership(Protocol):
    """Read validated membership for one artist's known candidate IDs."""

    def albums(self, ids: list[str]) -> tuple[bool, ...]:
        """Read saved-album membership at the original freshness boundary.

        Args:
            ids: Ordered candidate IDs from the canonical mirror.

        Returns:
            Validated statuses in input order.
        """

    def tracks(self, ids: list[str]) -> tuple[bool, ...]:
        """Read liked-track membership at the original freshness boundary.

        Args:
            ids: Ordered candidate IDs from the canonical mirror.

        Returns:
            Validated statuses in input order.
        """


def library_affinity(
    membership: ArtistMembership,
    album_ids: tuple[str, ...],
    track_ids: tuple[str, ...],
    *,
    batch_size: int = 10,
    minimum_albums: int = 3,
    minimum_tracks: int = 18,
) -> tuple[int | None, int, bool]:
    """Count saved albums first, consulting liked tracks only when still necessary.

    Args:
        membership: Artist-specific validated membership boundary.
        album_ids: Saved-album candidates in original order.
        track_ids: Liked-track candidates in original order.
        batch_size: Existing conservative request batch size.
        minimum_albums: Saved-album qualification threshold.
        minimum_tracks: Liked-track qualification threshold.

    Returns:
        Liked count (omitted when albums suffice), observed saved-album count,
        and qualification. Full accepted batches count even past a threshold.
    """
    albums, qualifies = _count_until(
        album_ids, membership.albums, batch_size, minimum_albums
    )
    if qualifies:
        return None, albums, True
    tracks, qualifies = _count_until(
        track_ids, membership.tracks, batch_size, minimum_tracks
    )
    return tracks, albums, qualifies


def _count_until(
    ids: tuple[str, ...],
    read: Callable[[list[str]], tuple[bool, ...]],
    batch_size: int,
    threshold: int,
) -> tuple[int, bool]:
    count = 0
    for start in range(0, len(ids), batch_size):
        count += sum(read(list(ids[start : start + batch_size])))
        if count >= threshold:
            return count, True
    return count, False
