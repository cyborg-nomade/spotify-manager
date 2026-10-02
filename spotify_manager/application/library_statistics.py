"""Pure transformations of the existing validated library statistics records."""

from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.utils.growth import calculate_growth


def _with_ratios(
    report: StatsReport, albums: AlbumsStats, artists: ArtistsStats, denominator: int
) -> StatsReport:
    return report.model_copy(
        update={
            "albums_stats": albums,
            "artists_stats": artists,
            "avg_albums_per_artists": albums.total_saved_albums // denominator,
            "avg_liked_tracks_per_artists": report.tracks_stats.total_liked_tracks
            // denominator,
        }
    )


def _increment_artist(stats: ArtistsStats, existing_period: bool) -> ArtistsStats:
    total = stats.total_followed_artists + 1
    previous = stats.total_followed_artists
    if existing_period:
        previous = previous - stats.added_artists + stats.removed_artists
    return stats.model_copy(
        update={
            "total_followed_artists": total,
            "removed_artists": stats.removed_artists if existing_period else 0,
            "added_artists": stats.added_artists + 1 if existing_period else 1,
            "growth": calculate_growth(total, previous),
        }
    )


def report_with_followed_artist(
    report: StatsReport, existing_period: bool
) -> StatsReport:
    """Increment one followed artist with the review routine's original arithmetic.

    Args:
        report: Prior statistics observation.
        existing_period: Whether its deltas belong to the current period.

    Returns:
        Copied statistics and recomputed integer ratios.

    Raises:
        ZeroDivisionError: The incremented artist count is zero, as in the legacy path.
    """
    artists = _increment_artist(report.artists_stats, existing_period)
    return _with_ratios(
        report, report.albums_stats, artists, artists.total_followed_artists
    )


def reset_period(report: StatsReport) -> StatsReport:
    """Reset period deltas without recomputing stored ratios or total counts.

    Args:
        report: Last stored report used to seed a new period.

    Returns:
        A copied report with zeroed added, removed, and growth fields.
    """
    albums = report.albums_stats.model_copy(
        update={"removed_albums": 0, "added_albums": 0, "growth": 0.0}
    )
    artists = report.artists_stats.model_copy(
        update={"removed_artists": 0, "added_artists": 0, "growth": 0.0}
    )
    tracks = report.tracks_stats.model_copy(
        update={"removed_tracks": 0, "added_tracks": 0, "growth": 0.0}
    )
    return report.model_copy(
        update={
            "albums_stats": albums,
            "artists_stats": artists,
            "tracks_stats": tracks,
        }
    )


def _album_totals(stats: AlbumsStats, total: int | None) -> AlbumsStats:
    if total is None:
        return stats
    previous = stats.total_saved_albums - stats.added_albums + stats.removed_albums
    return stats.model_copy(
        update={
            "total_saved_albums": total,
            "added_albums": max(0, total - previous + stats.removed_albums),
            "growth": calculate_growth(total, previous),
        }
    )


def _artist_totals(stats: ArtistsStats, total: int | None) -> ArtistsStats:
    if total is None:
        return stats
    previous = (
        stats.total_followed_artists - stats.added_artists + stats.removed_artists
    )
    return stats.model_copy(
        update={
            "total_followed_artists": total,
            "added_artists": max(0, total - previous + stats.removed_artists),
            "growth": calculate_growth(total, previous),
        }
    )


def report_with_recovered_counts(
    report: StatsReport, total_albums: int | None, total_artists: int | None
) -> StatsReport:
    """Reconcile current counts using recovery's original zero-count denominator.

    Args:
        report: Current-period report.
        total_albums: New album count, or None to retain its observation.
        total_artists: New artist count, or None to retain its observation.

    Returns:
        Copied counters, growth percentages, and integer per-artist ratios.
    """
    albums = _album_totals(report.albums_stats, total_albums)
    artists = _artist_totals(report.artists_stats, total_artists)
    return _with_ratios(report, albums, artists, max(1, artists.total_followed_artists))


def period_report(history: dict[str, StatsReport], key: str) -> tuple[str, StatsReport]:
    """Select an existing period or reset the last insertion-ordered report.

    Args:
        history: Original complete insertion-ordered report history.
        key: Original period identity supplied by the outer clock boundary.

    Returns:
        Original effective key and existing or reset report.

    Raises:
        StopIteration: No report exists to seed a missing period.
    """
    if key in history:
        return key, history[key]
    return key, reset_period(next(reversed(history.values())))


def report_with_unfollowed_artists(
    report: StatsReport, total: int, removed: int
) -> StatsReport:
    """Retain original post-unfollow deltas and the clamped ratio denominator.

    Args:
        report: Original current-period report.
        total: Original current followed-artist count after the accepted batch.
        removed: Original accepted unfollow batch size.

    Returns:
        Original copied artist counters and integer library ratios.
    """
    previous = (
        report.artists_stats.total_followed_artists
        - report.artists_stats.added_artists
        + report.artists_stats.removed_artists
    )
    artists = report.artists_stats.model_copy(
        update={
            "total_followed_artists": total,
            "removed_artists": report.artists_stats.removed_artists + removed,
            "growth": calculate_growth(total, previous),
        }
    )
    return report.model_copy(
        update={
            "artists_stats": artists,
            "avg_albums_per_artists": report.albums_stats.total_saved_albums
            // max(1, total),
            "avg_liked_tracks_per_artists": report.tracks_stats.total_liked_tracks
            // max(1, total),
        }
    )
