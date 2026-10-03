"""Small typed helpers for existing HTTP option validation."""

from collections.abc import Iterable
from typing import Protocol


class IdentifiedOption(Protocol):
    """Expose the original Spotify identifier of a presented choice."""

    @property
    def spotify_id(self) -> str:
        """Read the existing option identifier.

        Returns:
            Original unmodified identifier.
        """
        ...


def option_ids(options: Iterable[IdentifiedOption]) -> list[str]:
    """Read available identifiers in their original encounter order.

    Args:
        options: Existing wire choices without additional normalization.

    Returns:
        Original identifiers, retaining duplicates for the caller's validation.
    """
    result = []
    for option in options:
        result.append(option.spotify_id)
    return result
