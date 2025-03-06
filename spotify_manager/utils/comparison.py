"""."""

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.models.file_items import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryFile


def get_album_id_list_from_your_library_file(
    your_library_file: YourLibraryFile,
) -> list[str]:
    """."""
    return [album.spotify_id for album in your_library_file.albums]


def get_album_id_list_from_total_albums_file(
    total_albums_file: list[SimplifiedAlbum],
) -> list[str]:
    """."""
    return [album.spotify_id for album in total_albums_file]


def enrich_id_to_album_dict(album_id: str) -> dict:
    """."""
    print(album_id)
    sp = get_spotipy_client()
    album = sp.album(album_id)
    print(album["name"])
    return {
        "name": album["name"],
        "artist": album["artists"][0]["name"],
        "id": album_id,
    }


def compare_and_get_dict(
    your_library_id_list: list[str], total_albums_id_list: list[str]
) -> dict:
    """."""
    print("compare")
    ids_present_in_your_library_but_not_in_total_albums = [
        i for i in your_library_id_list if i not in total_albums_id_list
    ]
    ids_present_in_total_albums_but_not_in_your_library = [
        i for i in total_albums_id_list if i not in your_library_id_list
    ]
    comparison_dict = {
        "add": [
            enrich_id_to_album_dict(i)
            for i in ids_present_in_your_library_but_not_in_total_albums
        ],
        "remove": [
            enrich_id_to_album_dict(i)
            for i in ids_present_in_total_albums_but_not_in_your_library
        ],
    }
    return comparison_dict
