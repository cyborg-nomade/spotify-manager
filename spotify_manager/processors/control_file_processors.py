"""Data processors for control file items."""


from spotipy.client import Spotify

# UFI
from spotify_manager.loaders_savers import save_control_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.processors.total_albums_processor import (
    updated_total_albums_with_results,
)
from spotify_manager.utils.sorting import get_ordering_string


def get_index_for_first_unevaluated_album(control_file: list[ControlFileItem]) -> int:
    """Get index for first unevaluated album in control file."""
    return next((i for i, item in enumerate(control_file) if item.result == ""), 0)


def get_unevaluated_albums(
    control_file: list[ControlFileItem],
) -> list[ControlFileItem]:
    """Get list of unevaluated albums from control file."""
    print("Getting unevaluated albums...")
    index_for_first_unevaluated_album = get_index_for_first_unevaluated_album(
        control_file
    )
    print(f"First unevaluated album index: {index_for_first_unevaluated_album}")
    return control_file[index_for_first_unevaluated_album:]


def get_album_results_from_library(
    sp: Spotify,
    unevaluated_albums: list[ControlFileItem],
) -> list[ControlFileItem]:
    """Check against spotify library if albums have been removed or kept."""
    print("Checking against library...")
    for item in unevaluated_albums:
        is_saved = sp.current_user_saved_albums_contains([item.album.spotify_id])
        if is_saved[0]:
            item.result = "keep"
        else:
            item.result = "remove"
        print(f"album:{item.album.name}: result: {item.result}")
    return unevaluated_albums


def check_album_results(
    sp: Spotify,
    control_file: list[ControlFileItem],
    total_albums_file: list[SimplifiedAlbum],
) -> bool:
    """Check if non evaluated albums in control file are saved in library."""
    print("Checking album results...")
    unevaluated_albums = get_unevaluated_albums(control_file)
    get_album_results_from_library(sp, unevaluated_albums)
    updated_total_albums_with_results(total_albums_file, unevaluated_albums)
    save_control_file(control_file)
    print("Results checked!")
    return True


def get_last_kept_album_item_index(control_file: list[ControlFileItem]) -> int:
    """Get index last album item in control file whose result was "keep"."""
    return next(
        (
            i
            for i, item in reversed(list(enumerate(control_file)))
            if item.result == "keep"
        ),
        0,
    )


def get_starting_index(
    control_file: list[ControlFileItem], total_album_list: list[SimplifiedAlbum]
) -> int:
    """Get starting index in total album list from last listened in control file."""
    print("Getting starting index...")
    last_kept_album_item_index = get_last_kept_album_item_index(control_file)
    print("last_kept_album_item_index: ", last_kept_album_item_index)
    last_album_id = control_file[last_kept_album_item_index].album.spotify_id
    return (
        next(
            (
                i
                for i, item in enumerate(total_album_list)
                if item.spotify_id == last_album_id
            ),
            0,
        )
        + 1
    )


def enrich_album(spotify_id: str, sp: Spotify) -> SimplifiedAlbum:
    """."""
    album = sp.album(spotify_id)
    simplified_album = SimplifiedAlbum(
        spotify_id=album["id"],
        name=album["name"],
        artist=SimplifiedArtist(
            spotify_id=album["artists"][0]["id"],
            name=album["artists"][0]["name"],
        ),
        ordering_string=get_ordering_string(album["name"]),
    )
    return simplified_album
