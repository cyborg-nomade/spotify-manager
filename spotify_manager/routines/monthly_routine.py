"""Execute all monthly routines."""

from spotify_manager.loaders_savers import load_control_file
from spotify_manager.processors.control_file_processors import (
    check_album_results,
    get_starting_index,
)
from spotify_manager.processors.stats_processors import update_stats
from spotify_manager.processors.total_albums_processor import (
    add_monthly_albums,
    update_total_album_list,
)


def run_monthly_routines() -> None:
    """Run all monthly routines."""
    print("Running monthly routines...")
    control_file = load_control_file()
    total_album_list = update_total_album_list()

    check_album_results(control_file)
    update_stats(control_file, total_album_list)
    starting_index = get_starting_index(control_file, total_album_list)
    print(f"Starting index: {starting_index}")
    add_monthly_albums(control_file, total_album_list, starting_index)
    print("Monthly routine complete.")
