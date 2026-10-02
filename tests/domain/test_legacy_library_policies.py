"""Exercise legacy policy boundaries without file models or runtime imports."""

import pytest

from spotify_manager.domain.legacy_library import LegacyStatistics
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import last_kept_index
from spotify_manager.domain.legacy_library import monthly_slice
from spotify_manager.domain.legacy_library import playlist_batches
from spotify_manager.domain.legacy_library import unmatched_ids


@pytest.mark.parametrize(
    "wanted,existing,expected",
    [([], [], []), (["a", "a", "b"], ["b"], ["a", "a"]), (["b", "a"], ["a", "b"], [])],
)
def test_unmatched_preserves_duplicates(
    wanted: list[str], existing: list[str], expected: list[str]
) -> None:
    """Retain membership authority and encounter order.

    Args:
        wanted: Original requested identities.
        existing: Original membership authority.
        expected: Frozen original unmatched encounter order.
    """
    assert unmatched_ids(wanted, existing) == expected


@pytest.mark.parametrize(
    "values,expected", [([], 0), (["x"], 0), (["x", "keep", "keep"], 1)]
)
def test_first_index_fallback(values: list[str], expected: int) -> None:
    """Retain first-match and zero fallback behavior.

    Args:
        values: Original ordered input.
        expected: Original index.
    """
    assert first_index(values, "keep") == expected


@pytest.mark.parametrize(
    "values,expected",
    [([], 0), (["x"], 0), (["keep", "x", "keep"], 2), (["keep", "x"], 0)],
)
def test_last_kept_fallback(values: list[str], expected: int) -> None:
    """Retain last-match and zero fallback behavior.

    Args:
        values: Original ordered decisions.
        expected: Original index.
    """
    assert last_kept_index(values) == expected


@pytest.mark.parametrize(
    "size,lengths",
    [(0, [0]), (1, [1]), (100, [100]), (101, [100, 1]), (205, [100, 100, 5])],
)
def test_batch_boundaries(size: int, lengths: list[int]) -> None:
    """Preserve every ordered URI and the original empty request.

    Args:
        size: Original raw ordered size.
        lengths: Expected original batch sizes.
    """
    uris = [str(index) for index in range(size)]
    batches = playlist_batches(uris)
    assert [len(batch) for batch in batches] == lengths
    flattened = []
    for batch in batches:
        flattened.extend(batch)
    assert flattened == uris


@pytest.mark.parametrize("saved,listened", [(0, 0), (0, 2), (2, 0)])
def test_statistics_keeps_original_zero_failure(saved: int, listened: int) -> None:
    """Retain native denominator errors instead of introducing a fallback.

    Args:
        saved: Original total-album count.
        listened: Original control count.
    """
    with pytest.raises(ZeroDivisionError):
        LegacyStatistics(saved, listened, 0).fields()


def test_statistics_counts_unknown_decisions_as_kept() -> None:
    """Preserve original ratios and the last control index."""
    assert LegacyStatistics(4, 3, 1).fields() == {
        "total_saved_albums": 4,
        "total_listened_albums": 3,
        "pct_listened_albums": 0.75,
        "total_removed_albums": 1,
        "pct_removed_albums": 1 / 3,
        "total_kept_albums": 2,
        "pct_kept_albums": 2 / 3,
        "last_listened_to_index": 2,
    }


@pytest.mark.parametrize(
    "index,count,expected",
    [(0, 0, []), (1, 2, [1, 2]), (-2, 3, []), (0, -1, [0, 1, 2])],
)
def test_monthly_slice_keeps_native_bounds(
    index: int, count: int, expected: list[int]
) -> None:
    """Retain zero, negative and ordinary monthly slice bounds.

    Args:
        index: Original start index.
        count: Original configured size.
        expected: Original native slice result.
    """
    assert monthly_slice([0, 1, 2, 3], index, count) == expected
