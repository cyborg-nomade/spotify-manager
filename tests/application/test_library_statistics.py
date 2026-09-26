"""Retain review and recovery arithmetic over existing statistics records."""

import pytest

from spotify_manager.application.library_statistics import report_with_followed_artist
from spotify_manager.application.library_statistics import report_with_recovered_counts
from spotify_manager.application.library_statistics import reset_period
from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats


def _report(artists: int = 10) -> StatsReport:
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=20, removed_albums=3, added_albums=5, growth=0
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=artists, removed_artists=2, added_artists=4, growth=0
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=100, removed_tracks=7, added_tracks=9, growth=0
        ),
        avg_albums_per_artists=2,
        avg_liked_tracks_per_artists=10,
    )


@pytest.mark.parametrize(
    "existing,added,removed,growth",
    [
        (True, 5, 2, 37.5),
        (False, 1, 0, 10.0),
    ],
)
def test_followed_artist_period_arithmetic(
    existing: bool, added: int, removed: int, growth: float
) -> None:
    """Retain period-sensitive increments without mutating the input report.

    Args:
        existing: Whether deltas belong to this period.
        added: Expected new-follow count.
        removed: Expected retained removal count.
        growth: Expected percentage from the original period baseline.
    """
    source = _report()
    result = report_with_followed_artist(source, existing)
    assert result.artists_stats == ArtistsStats(
        total_followed_artists=11,
        added_artists=added,
        removed_artists=removed,
        growth=growth,
    )
    assert result.avg_albums_per_artists == 1
    assert result.avg_liked_tracks_per_artists == 9
    assert source == _report()


def test_new_period_resets_only_deltas() -> None:
    """Seeding a new period retains totals and previously stored ratios."""
    source = _report()
    result = reset_period(source)
    assert result.albums_stats.added_albums == 0
    assert result.artists_stats.removed_artists == 0
    assert result.tracks_stats.added_tracks == 0
    assert result.avg_albums_per_artists == source.avg_albums_per_artists
    assert result.albums_stats.total_saved_albums == 20
    assert source == _report()


@pytest.mark.parametrize(
    "albums,artists,expected_albums,expected_artists",
    [
        (None, None, 20, 10),
        (0, 0, 0, 0),
        (23, 13, 23, 13),
        (None, 11, 20, 11),
        (21, None, 21, 10),
    ],
)
def test_recovery_reconciles_observed_counts(
    albums: int | None, artists: int | None, expected_albums: int, expected_artists: int
) -> None:
    """Retain optional count updates and the zero-artist ratio denominator.

    Args:
        albums: New album observation when present.
        artists: New artist observation when present.
        expected_albums: Expected resulting total.
        expected_artists: Expected resulting total.
    """
    result = report_with_recovered_counts(_report(), albums, artists)
    assert result.albums_stats.total_saved_albums == expected_albums
    assert result.artists_stats.total_followed_artists == expected_artists
    assert result.avg_albums_per_artists == expected_albums // max(1, expected_artists)
    if albums is not None:
        assert result.albums_stats.added_albums == max(0, albums - 15)
        assert result.albums_stats.growth == pytest.approx((albums - 18) / 18 * 100)
    if artists is not None:
        assert result.artists_stats.added_artists == max(0, artists - 6)
        assert result.artists_stats.growth == pytest.approx((artists - 8) / 8 * 100)


def test_review_retains_zero_denominator_error_instead_of_recovery_clamp() -> None:
    """The two legacy arithmetic paths intentionally keep different edge behavior."""
    with pytest.raises(ZeroDivisionError):
        report_with_followed_artist(_report(-1), False)
