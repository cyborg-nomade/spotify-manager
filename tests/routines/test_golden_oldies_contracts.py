"""Freeze original exact-label Golden Oldies counts and oldest-average ordering."""

import pytest

from tests.support.golden_oldies import cases
from tests.support.golden_oldies import original_outcome


@pytest.mark.parametrize(
    "profile,expected", cases(), ids=[name for name, _case in cases()]
)
def test_original_golden_oldies_ranking(profile: str, expected: object) -> None:
    """Preserve exact artist identities, title ties, limits and integer averages.

    Args:
        profile: Original history profile.
        expected: Immutable original ranking.
    """
    assert original_outcome(profile) == expected
