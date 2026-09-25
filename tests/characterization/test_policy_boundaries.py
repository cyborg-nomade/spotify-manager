"""Decision boundaries required before extracting the first domain policies."""

import pytest

from spotify_manager.processors.library_lookups import required_liked_tracks


@pytest.mark.parametrize(
    "tracks,threshold,expected",
    [
        (0, 0, 1),
        (0, 0.5, 1),
        (-1, 0.5, 1),
        (1, 0, 0),
        (1, -0.1, 0),
        (1, 0.5, 1),
        (2, 0.5, 1),
        (3, 0.5, 1),
        (5, 0.5, 2),
        (3, 0.01, 1),
        (10, 0.3, 3),
        (10, 1.0, 10),
        (10, 1.1, 11),
    ],
)
def test_keep_threshold_preserves_floor_and_empty_album_contract(
    tracks: int, threshold: float, expected: int
) -> None:
    """Keep rounding and empty-album behavior at the specified policy boundaries.

    Args:
        tracks: Album track count, including invalid and empty inputs.
        threshold: Required liked-track proportion.
        expected: Legacy minimum count at this boundary.
    """
    assert required_liked_tracks(tracks, threshold) == expected
