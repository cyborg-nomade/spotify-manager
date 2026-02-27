"""Data processors for stats."""

# Standard Library
from datetime import datetime

# UFI
from spotify_manager.loaders_savers import load_stats_history_file
from spotify_manager.loaders_savers import save_stats_file
from spotify_manager.loaders_savers import save_stats_history
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats


def calculate_stats(
    control_file: list[ControlFileItem], total_album_list: list[SimplifiedAlbum]
) -> StatsFileItem:
    """Calculate stats."""
    print("Calculating stats...")
    total_saved_albums = len(total_album_list)
    total_listened_albums = len(control_file)
    total_removed_albums = len(
        [item for item in control_file if item.result == "remove"]
    )
    total_kept_albums = total_listened_albums - total_removed_albums
    return StatsFileItem(
        total_saved_albums=total_saved_albums,
        total_listened_albums=total_listened_albums,
        pct_listened_albums=total_listened_albums / total_saved_albums,
        total_removed_albums=total_removed_albums,
        pct_removed_albums=total_removed_albums / total_listened_albums,
        total_kept_albums=total_kept_albums,
        pct_kept_albums=total_kept_albums / total_listened_albums,
        last_listened_to_index=total_listened_albums - 1,
    )


def update_stats(
    control_file: list[ControlFileItem], total_album_list: list[SimplifiedAlbum]
) -> bool:
    """Update stats file."""
    print("Updating stats...")
    stats = calculate_stats(control_file, total_album_list)
    print(f"These are your current stats: \n{stats.dict()}")
    save_stats_file(stats)
    print("Stats updated!")
    return True


def process_stats(
    albums_stats: AlbumsStats, artists_stats: ArtistsStats, tracks_stats: TracksStats
) -> StatsReport:
    """Process stats and return report."""
    print("Processing stats")
    year = str(datetime.now().year)
    month = (
        str(datetime.now().month)
        if datetime.now().month >= 10
        else f"0{str(datetime.now().month)}"
    )
    key = f"{year}.{month}"

    report = StatsReport(
        albums_stats=albums_stats,
        artists_stats=artists_stats,
        tracks_stats=tracks_stats,
        avg_albums_per_artists=albums_stats.total_saved_albums
        // artists_stats.total_followed_artists,
        avg_liked_tracks_per_artists=tracks_stats.total_liked_tracks
        // artists_stats.total_followed_artists,
    )

    stats_history_dict = load_stats_history_file()
    stats_history_dict[key] = report
    save_stats_history(stats_history_dict)

    return report
