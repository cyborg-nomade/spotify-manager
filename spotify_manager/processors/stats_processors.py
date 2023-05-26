"""Data processors for stats."""

from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.loaders_savers import save_stats_file


def calculate_stats(
    control_file: list[ControlFileItem], total_album_list: list[ControlFileItem]
) -> StatsFileItem:
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
        monthly_history={},
    )


def update_stats(
    control_file: list[ControlFileItem], total_album_list: list[ControlFileItem]
) -> bool:
    """Update stats file."""
    print("Updating stats...")
    stats = calculate_stats(control_file, total_album_list)
    print(f"These are your current stats: \n{stats.dict()}")
    save_stats_file(stats)
    print("Stats updated!")
    return True
