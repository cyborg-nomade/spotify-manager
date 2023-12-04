"""Convert Your Library file into All Albums model file."""

from spotipy import Spotify

# UFI
from spotify_manager.loaders_savers import load_comparison_file
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.loaders_savers import save_comparison_file
from spotify_manager.loaders_savers import save_total_albums_file
from spotify_manager.processors.control_file_processors import enrich_album
from spotify_manager.processors.total_albums_processor import (
    get_album_index_in_total_albums,
)
from spotify_manager.processors.your_library_processors import is_in_library_artist
from spotify_manager.processors.your_library_processors import is_in_library_track
from spotify_manager.processors.your_library_processors import save_to_library_artist
from spotify_manager.processors.your_library_processors import save_to_library_track
from spotify_manager.utils.comparison import compare_and_get_dict
from spotify_manager.utils.comparison import get_album_id_list_from_total_albums_file
from spotify_manager.utils.comparison import get_album_id_list_from_your_library_file
from spotify_manager.utils.sorting import sort_key


def compare_your_library_and_all_albums() -> None:
    """Create comparison between your_library and all albums files."""
    your_library_file = load_your_library_file()
    total_albums_file = load_total_albums_file()
    your_library_id_list = get_album_id_list_from_your_library_file(your_library_file)
    total_albums_id_list = get_album_id_list_from_total_albums_file(total_albums_file)
    comparison_dict = compare_and_get_dict(your_library_id_list, total_albums_id_list)
    save_comparison_file(comparison_dict)


def analyse_comparison(sp: Spotify) -> None:
    """."""
    comparison_dict = load_comparison_file()
    print(f"Albums to remove: {len(comparison_dict['remove'])}")
    for album in comparison_dict["remove"]:
        print(album)
        if sp.current_user_saved_albums_contains([album["id"]])[0]:
            print("     is saved")
    print(f"Albums to add: {len(comparison_dict['add'])}")
    for album in comparison_dict["add"]:
        print(album)
        if not sp.current_user_saved_albums_contains([album["id"]])[0]:
            print("     not saved")


def convert_your_library_file(sp: Spotify) -> None:
    """Convert Your Library File to all albums file."""
    total_albums_file = load_total_albums_file()
    comparison_dict = load_comparison_file()
    removed_albums = 0
    added_albums = 0
    for album in comparison_dict["remove"]:
        print(album)
        if not sp.current_user_saved_albums_contains([album["id"]])[0]:
            album_index = get_album_index_in_total_albums(
                album["id"], total_albums_file
            )
            print(album_index)
            print(total_albums_file[album_index])
            removed_albums += 1
            total_albums_file.pop(album_index)
    print(removed_albums)
    print(len(comparison_dict["remove"]))
    for album in comparison_dict["add"]:
        print(album)
        if sp.current_user_saved_albums_contains([album["id"]])[0]:
            simplified_album = enrich_album(album["id"], sp)
            print(simplified_album)
            total_albums_file.append(simplified_album)
            added_albums += 1
    print(added_albums)
    print(len(comparison_dict["add"]))
    sorted_albums = sorted(total_albums_file, key=sort_key)
    save_total_albums_file(sorted_albums)


def restore_your_library_from_file(sp: Spotify) -> None:
    """Convert Your Library File to all albums file."""
    your_library_file = load_your_library_file()
    artist_counter = 0
    track_counter = 0
    for artist in your_library_file.artists:
        print(artist.name)
        if not is_in_library_artist(sp, artist):
            save_to_library_artist(sp, artist)
            artist_counter += 1
            print("         saved!")
            print(f"\nArtists saved so far: {artist_counter}\n\n")
    for track in your_library_file.tracks:
        print(track.album)
        print(track.artist)
        print(track.uri)
        if not is_in_library_track(sp, track):
            save_to_library_track(sp, track)
            track_counter += 1
            print("         saved!")
            print(f"\nTracks saved so far: {track_counter}\n\n")
    print(f"\n\nArtists saved: {artist_counter}")
    print(f"\nTracks saved: {track_counter}")
