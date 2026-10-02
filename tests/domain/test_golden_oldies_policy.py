"""Verify original Golden Oldies rankings without history services or Spotify."""

import json
from dataclasses import asdict

import pytest

from spotify_manager.domain.golden_oldies import rank_golden_oldies
from spotify_manager.domain.history import Scrobble
from tests.support.golden_oldies import cases
from tests.support.golden_oldies import plays


@pytest.mark.parametrize(
    "profile,expected", cases(), ids=[name for name, _case in cases()]
)
def test_independent_golden_oldies_matches_original(
    profile: str, expected: object
) -> None:
    """Match original exact identities, title ties and oldest-average timestamps.

    Args:
        profile: Original immutable history profile.
        expected: Original complete ranking observations.
    """
    result = rank_golden_oldies(plays(profile))
    assert json.loads(json.dumps([asdict(artist) for artist in result])) == expected


@pytest.mark.parametrize("count", [49, 50, 51])
def test_golden_oldies_minimum_is_inclusive(count: int) -> None:
    """Retain the original inclusive fifty-play eligibility boundary.

    Args:
        count: Original artist's observed number of plays.
    """
    history = tuple(
        Scrobble("Track", "Artist", "Album", index) for index in range(count)
    )
    result = rank_golden_oldies(history)
    assert len(result) == (1 if count >= 50 else 0)


def test_golden_oldies_integer_average_uses_floor() -> None:
    """Retain integer timestamp flooring rather than floating-point mean ordering."""
    history = (
        Scrobble("Track", "Artist", "Album", -1),
        Scrobble("Track", "Artist", "Album", 0),
    )
    assert rank_golden_oldies(history, minimum_plays=2)[0].average_scrobble_ms == -1
