"""Eager, ordered presentation of routine values at the HTTP boundary."""

from collections.abc import Callable
from collections.abc import Iterable
from datetime import date


def present_entries[T, R](values: Iterable[T], present: Callable[[T], R]) -> list[R]:
    """Present entries in encounter order, propagating the first conversion error.

    Args:
        values: Routine values in their original order.
        present: Feature presenter supplied by the compatibility facade.

    Returns:
        Eagerly converted response entries.
    """
    entries = []
    for value in values:
        entries.append(present(value))
    return entries


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
