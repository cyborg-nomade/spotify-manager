"""Protect Queue capacity and marker-selection boundaries without external reads."""

import pytest

from spotify_manager.domain.queue_fill import first_unliked
from spotify_manager.domain.queue_fill import requested_additions
from tests.support.queue_fill import TRACK


@pytest.mark.parametrize(
    "count,maximum,before,expected",
    [
        (None, None, 12, 20),
        (3, None, 12, 3),
        (None, 10, 12, 0),
        (None, 10, 10, 0),
        (None, 10, 7, 3),
    ],
)
def test_original_queue_capacity(
    count: int | None,
    maximum: int | None,
    before: int,
    expected: int,
) -> None:
    """Preserve default, requested count and maximum-capacity arithmetic.

    Args:
        count: Original optional requested additions.
        maximum: Original optional maximum length.
        before: Original observed Queue length.
        expected: Original effective requested additions.
    """
    assert requested_additions(count, maximum, before) == expected


@pytest.mark.parametrize("liked", [{}, {"track": False}, {"track": True}])
def test_original_first_unliked_marker(liked: dict[str, bool]) -> None:
    """Treat missing statuses as unliked while retaining original source order.

    Args:
        liked: Original liked membership facts.
    """
    expected = None if liked.get("track", False) else TRACK
    assert first_unliked((TRACK,), liked) == expected


def test_empty_top_tracks_have_no_marker() -> None:
    """Keep an empty top-track window empty."""
    assert first_unliked((), {}) is None
