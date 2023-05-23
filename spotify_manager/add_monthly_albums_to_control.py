"""Add monthyl albums to Control File."""
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotify_manager.add_monthly_tracks import load_all_albums, get_months_albums
from spotify_manager.convert_control_file import save_new_control_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem

import json
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.sorting import get_ordering_string


def load_control_file_albums() -> list[ControlFileItem]:
    """Load all albums from file."""
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/control_file.json", "r"
    ) as control_file:
        result_dict = json.load(control_file)
        return [ControlFileItem.parse_obj(s) for s in result_dict]


def get_simplified_album(album_id: str) -> SimplifiedAlbum:
    """."""
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

    album = sp.album(album_id)

    return SimplifiedAlbum(
        spotify_id=album["id"],
        name=album["name"],
        artist=SimplifiedArtist(
            spotify_id=album["artists"][0]["id"],
            name=album["artists"][0]["name"],
        ),
        ordering_string=get_ordering_string(album["name"]),
    )


def add_monthly_albums_to_control_file(
    initial_index: int, final_file_path: str
) -> bool:
    """."""
    all_albums = load_all_albums()
    this_month_albums = get_months_albums(all_albums, initial_index)
    control_file_items = load_control_file_albums()

    for index, album in enumerate(this_month_albums):
        print(f"{index}/{len(this_month_albums)}")
        album_id = album["id"]
        print(album_id)
        simplified_album = get_simplified_album(album_id)
        print(simplified_album)
        control_file_item = ControlFileItem(album=simplified_album, result="")
        print(control_file_item)
        control_file_items.append(control_file_item)
    save_new_control_file(control_file_items, final_file_path)
    return True


if __name__ == "__main__":
    result = add_monthly_albums_to_control_file(
        38551,
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/control_file.json",
    )
    if result:
        print("Done!")
    else:
        print("there was an error")
