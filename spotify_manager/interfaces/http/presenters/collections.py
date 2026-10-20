"""Eager, ordered presentation of routine values at the HTTP boundary."""

from collections.abc import Iterable
from datetime import date


def date_strings(values: Iterable[date]) -> list[str]:
    """Format historical dates for the original JSON response fields.

    Args:
        values: Historical dates in their original order.

    Returns:
        ISO date strings suitable for the wire view.
    """
    entries = []
    for value in values:
        entries.append(value.isoformat())
    return entries
