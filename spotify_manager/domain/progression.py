"""Track advancement rules that consume existing observations in order."""

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Protocol


class CreditedTrack(Protocol):
    """A track whose already-parsed primary artist can be compared."""

    @property
    def primary_artist_id(self) -> str:
        """Return the first accepted artist credit.

        Returns:
            The primary artist identifier supplied by the boundary parser.
        """
        ...


class IdentifiedTrack(Protocol):
    """A track whose identity indexes previously observed liked statuses."""

    @property
    def spotify_id(self) -> str:
        """Return the catalog identifier.

        Returns:
            Track identifier used in the liked-status mapping.
        """
        ...


def primary_artist_tracks[T: CreditedTrack](
    tracks: Iterable[T], artist_id: str
) -> tuple[T, ...]:
    """Retain primary-credit tracks in input order, including duplicates.

    Args:
        tracks: Already-parsed tracks; malformed credits belong to boundary codecs.
        artist_id: Artist whose primary-credit tracks are eligible.

    Returns:
        Eligible original track objects, preserving identity and order.
    """
    result = []
    for track in tracks:
        if track.primary_artist_id == artist_id:
            result.append(track)
    return tuple(result)


def trailing_unliked(statuses: Iterable[bool]) -> int:
    """Count preceding unliked tracks supplied in reverse listening order.

    Args:
        statuses: Nearest preceding status first; consumed only until a like.

    Returns:
        The length of the consecutive unliked tail.
    """
    count = 0
    for liked in statuses:
        if liked:
            break
        count += 1
    return count


def advance_streak(prior_streak: int, current_liked: bool) -> int:
    """Reset the streak on a like or extend its persisted value otherwise.

    Args:
        prior_streak: Existing streak, retaining legacy negative values too.
        current_liked: Whether the current track is liked.

    Returns:
        The streak after the current track.
    """
    return 0 if current_liked else prior_streak + 1


def next_liked_track[T: IdentifiedTrack](
    tracks: Sequence[T],
    source_index: int | None,
    liked: Mapping[str, bool],
) -> T | None:
    """Find the first liked successor after the current marker.

    Args:
        tracks: Ordered tracks within the active canonical endpoint.
        source_index: Current marker position, or None if no match exists.
        liked: Observed statuses, consulted only through the first liked successor.

    Returns:
        The original successor object, or None when no eligible successor exists.

    Raises:
        KeyError: A consulted track lacks its required liked-status observation.
    """
    if source_index is None:
        return None
    for track in tracks[source_index + 1 :]:
        if liked[track.spotify_id]:
            return track
    return None
