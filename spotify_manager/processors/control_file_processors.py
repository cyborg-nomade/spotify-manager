"""Data processors for control file items."""

from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.client import get_spotipy_client
from spotify_manager.loaders_savers import save_control_file


def get_index_for_first_unevaluated_album(control_file: list[ControlFileItem]) -> int:
    """."""
    return next((i for i, item in enumerate(control_file) if item.result == ""), 0)


def get_unevaluated_albums(
    control_file: list[ControlFileItem],
) -> list[ControlFileItem]:
    """Get list of unevaluated albums from control file."""
    index_for_first_unevaluated_album = get_index_for_first_unevaluated_album(
        control_file
    )
    return control_file[index_for_first_unevaluated_album:]


def get_album_results_from_library(
    unevaluated_albums: list[ControlFileItem],
) -> list[ControlFileItem]:
    """Check against spotify library if albums have been removed or kept."""
    sp = get_spotipy_client()
    for item in unevaluated_albums:
        is_saved = sp.current_user_saved_albums_contains([item.album.spotify_id])
        if is_saved[0]:
            item.result = "keep"
        else:
            item.result = "remove"
    return unevaluated_albums


def update_control_file(
    control_file: list[ControlFileItem], album_results: list[ControlFileItem]
) -> list[ControlFileItem]:
    """Update and save control file with updated results."""
    index_for_first_unevaluated_album = get_index_for_first_unevaluated_album(
        control_file
    )
    new_control_file_items = control_file[:index_for_first_unevaluated_album].extend(
        album_results
    )
    save_control_file(new_control_file_items)
    return new_control_file_items


def check_album_results(control_file: list[ControlFileItem]) -> bool:
    """Check if non evaluated albums in control file are saved in library."""
    unevaluated_albums = get_unevaluated_albums(control_file)
    album_results = get_album_results_from_library(unevaluated_albums)
    update_control_file(control_file, album_results)
    return True


def get_starting_index(
    control_file: list[ControlFileItem], total_album_list: list[ControlFileItem]
) -> int:
    """Get starting index in total album list from last listened in control file."""
    last_album_id = control_file[-1].album.spotify_id
    return next(
        (
            i
            for i, item in enumerate(total_album_list)
            if item.album.spotify_id == last_album_id
        ),
        0,
    )
