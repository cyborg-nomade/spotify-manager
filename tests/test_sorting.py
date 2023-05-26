"""Test sorting functions."""

import random

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spotify_manager.utils.sorting import get_ordering_string


def test_get_ordering_string() -> None:
    """Check if ordering strings make sense."""
    SPOTIPY_CLIENT_ID = "fc70707ebf5d4ca3af5bdcd88bdd9b17"
    SPOTIPY_CLIENT_SECRET = "bc624df47d1c48b5a3f5dcef186c2b6c"
    SPOTIPY_REDIRECT_URI = "http://localhost"

    scope = "user-library-read"

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scope,
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
            redirect_uri=SPOTIPY_REDIRECT_URI,
        )
    )

    random_offset = int(random.random() * 70000)
    print(random_offset)

    results = sp.current_user_saved_albums(limit=50, offset=random_offset)
    albums = results["items"]

    simplified_albums = [
        {
            "name": album["album"]["name"],
            "ordering_name": get_ordering_string(album["album"]["name"]),
            "artist": album["album"]["artists"][0]["name"],
        }
        for album in albums
    ]

    sorted_albums = sorted(simplified_albums, key=lambda x: (x["ordering_name"]))

    for album in sorted_albums:
        name = album["name"]
        ordering_name = album["ordering_name"]
        print(f"{name} - {ordering_name}")


if __name__ == "__main__":
    test_get_ordering_string()
