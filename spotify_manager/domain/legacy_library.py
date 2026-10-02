"""Original legacy comparison, cursor, batching and listening-count rules."""

from collections.abc import Sequence
from dataclasses import dataclass


def unmatched_ids(wanted: Sequence[str], existing: Sequence[str]) -> list[str]:
    """Select unmatched identities without discarding duplicates.

    Args:
        wanted: Original encounter order.
        existing: Original membership authority.

    Returns:
        Every unmatched identity in encounter order.
    """
    result = []
    for identifier in wanted:
        if identifier not in existing:
            result.append(identifier)
    return result


def first_index(values: Sequence[str], expected: str) -> int:
    """Find the first match, retaining the original zero fallback.

    Args:
        values: Original ordered values.
        expected: Original requested value.

    Returns:
        First matching index, or zero even for an empty input.
    """
    for index, value in enumerate(values):
        if value == expected:
            return index
    return 0


def last_kept_index(results: Sequence[str]) -> int:
    """Find the last kept control entry with the original zero fallback.

    Args:
        results: Original control decisions.

    Returns:
        Last keep index or zero.
    """
    for index in range(len(results) - 1, -1, -1):
        if results[index] == "keep":
            return index
    return 0


def playlist_batches(uris: list[str]) -> list[list[str]]:
    """Retain one empty request and the original hundred-track boundary.

    Args:
        uris: Ordered playlist additions.

    Returns:
        Original ordered batches, including one batch for empty input.
    """
    if len(uris) <= 100:
        return [uris]
    result = []
    for offset in range(0, len(uris), 100):
        result.append(uris[offset : offset + 100])
    return result


@dataclass(frozen=True)
class LegacyStatistics:
    """Original counts and proportions, including unrecognized decisions.

    Args:
        saved: Original total album-list length.
        listened: Original control-list length.
        removed: Exact remove decisions.
    """

    saved: int
    listened: int
    removed: int

    def fields(self) -> dict[str, int | float]:
        """Calculate original proportions in their original evaluation order.

        Returns:
            Original statistics constructor fields.

        Raises:
            ZeroDivisionError: The original saved or listened denominator is zero.
        """
        kept = self.listened - self.removed
        return {
            "total_saved_albums": self.saved,
            "total_listened_albums": self.listened,
            "pct_listened_albums": self.listened / self.saved,
            "total_removed_albums": self.removed,
            "pct_removed_albums": self.removed / self.listened,
            "total_kept_albums": kept,
            "pct_kept_albums": kept / self.listened,
            "last_listened_to_index": self.listened - 1,
        }


def monthly_slice[T](albums: list[T], index: int, count: int) -> list[T]:
    """Retain the original permissive monthly slice.

    Args:
        albums: Original ordered authority.
        index: Original unvalidated starting position.
        count: Original unvalidated monthly size.

    Returns:
        Original slice, including Python's zero and negative bounds.
    """
    return albums[index : index + count]
