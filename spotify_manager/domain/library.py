"""Shared library identities and date rules independent of integration clocks."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AlbumArtist:
    """Artist identity observed in library or album metadata.

    Args:
        spotify_id: Original Spotify artist identifier.
        name: Original display name.
    """

    spotify_id: str
    name: str


def release_is_in_future(
    release_date: str | None, precision: str | None, today: date
) -> bool:
    """Compare a possibly partial release date using the legacy precision rules.

    Args:
        release_date: Observed date text, including malformed values.
        precision: Reported precision, or None to infer from the component count.
        today: Caller-observed date; the policy never reads the clock.

    Returns:
        Whether the reported precision proves the release lies in the future.
    """
    if not release_date:
        return False
    parts = release_date.split("-")
    effective = precision or {1: "year", 2: "month", 3: "day"}.get(len(parts))
    try:
        numbers = tuple(int(part) for part in parts)
        return _future_components(numbers, effective, today)
    except TypeError, ValueError:
        return False


def _future_components(
    numbers: tuple[int, ...], precision: str | None, today: date
) -> bool:
    if precision == "year" and len(numbers) >= 1:
        return numbers[0] > today.year
    if precision == "month" and len(numbers) >= 2:
        return numbers[:2] > (today.year, today.month)
    if precision == "day" and len(numbers) >= 3:
        return date(*numbers[:3]) > today
    return False
