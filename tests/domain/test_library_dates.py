"""Preserve partial-date recovery policy without reading the system clock."""

from datetime import date

import pytest

from spotify_manager.domain.library import release_is_in_future


@pytest.mark.parametrize(
    "value,precision,expected",
    [
        (None, None, False),
        ("", None, False),
        ("2027", None, True),
        ("2026", "year", False),
        ("2027-99", "year", True),
        ("2026-08", None, True),
        ("2026-07", "month", False),
        ("2026-99", "month", True),
        ("2027", "month", False),
        ("2026-07-15", None, True),
        ("2026-07-14", "day", False),
        ("2026-02-30", "day", False),
        ("2026-07", "day", False),
        ("2026-07-15-99", "day", True),
        ("2026-07-15-99", None, False),
        ("2026-07-15", "invalid", False),
        ("invalid", "day", False),
        ("2026-07-15", "", True),
    ],
)
def test_future_release_precision(
    value: str | None, precision: str | None, expected: bool
) -> None:
    """Retain legacy inference, malformed values, and partial-date comparisons.

    Args:
        value: Original release-date text.
        precision: Reported precision, when present.
        expected: Original recovery eligibility.
    """
    assert release_is_in_future(value, precision, date(2026, 7, 14)) is expected
