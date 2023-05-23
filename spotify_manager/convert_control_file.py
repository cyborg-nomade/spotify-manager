"""Convert control file to JSON standard."""

import json

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.sorting import get_ordering_string


def search_album(search_query: str) -> dict:
    """Search an album given a certain string."""

    SPOTIPY_CLIENT_ID = "fc70707ebf5d4ca3af5bdcd88bdd9b17"
    SPOTIPY_CLIENT_SECRET = "bc624df47d1c48b5a3f5dcef186c2b6c"
    SPOTIPY_REDIRECT_URI = "http://localhost"

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
            redirect_uri=SPOTIPY_REDIRECT_URI,
        )
    )

    return sp.search(search_query, type="album")


def get_album_from_line_parts(line_parts: list[str]) -> SimplifiedAlbum:
    """Return a SimplifiedAlbum for a given line parts list."""
    search_query = line_parts[1] + " " + line_parts[2]
    search_dict = search_album(search_query)

    return SimplifiedAlbum(
        spotify_id=search_dict["albums"]["items"][0]["id"],
        name=search_dict["albums"]["items"][0]["name"],
        artist=SimplifiedArtist(
            spotify_id=search_dict["albums"]["items"][0]["artists"][0]["id"],
            name=search_dict["albums"]["items"][0]["artists"][0]["name"],
        ),
        ordering_string=get_ordering_string(search_dict["albums"]["items"][0]["name"]),
    )


def get_control_file_item_for_album(
    album: SimplifiedAlbum, line_parts: list[str]
) -> ControlFileItem:
    """Return ControlFileItem for a given SimplifiedAlbum."""
    return ControlFileItem(album=album, result=line_parts[3])


def extract_initial_data(file_path: str) -> list[ControlFileItem]:
    """Extract data in the initial control file and return a list of ControlFileItem."""

    split_line_parts = []

    with open(file_path, "r") as initial_control_file:
        lines = initial_control_file.readlines()
        for index, line in enumerate(lines):
            line_parts = line.split("|")
            if len(line_parts) != 5:
                print(index)
            split_line_parts.append(line_parts)

    control_file_items = []

    for index, line_parts in enumerate(split_line_parts):
        for attempt in range(100):
            try:
                print(f"{index}/{len(split_line_parts)}")
                album = get_album_from_line_parts(line_parts)
                control_file_item = get_control_file_item_for_album(album, line_parts)
                control_file_items.append(control_file_item)
                print(control_file_item)
            except Exception as e:
                print(e)
                print("Oops... Retrying")
            else:
                break
        else:
            print(attempt)

    return control_file_items


def save_new_control_file(
    control_file_items: list[ControlFileItem], final_file_path: str
) -> bool:
    """Saves JSON file for converted control file items."""
    serialized_control_file_items = [
        control_file_item.dict() for control_file_item in control_file_items
    ]
    with open(final_file_path, "w") as final_file:
        json.dump(serialized_control_file_items, final_file, ensure_ascii=False)
    return True


def convert_control_file(initial_file_path: str, final_file_path: str) -> bool:
    """Convert control file into manageable format."""
    control_file_items = extract_initial_data(initial_file_path)
    result = save_new_control_file(control_file_items, final_file_path)
    return result


if __name__ == "__main__":
    result = convert_control_file(
        "/home/ufiori/dev/spotify-manager/spotify_manager/"
        "files/Spotify Albuns (03-11-2020).txt",
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/control_file.json",
    )
    if result:
        print("Done!")
    else:
        print("there was an error")
