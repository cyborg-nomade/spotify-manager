import json

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spotify_manager.sorting import get_ordering_string, sort_key

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

results = sp.current_user_saved_albums(limit=50)
total_albums = results["total"]
albums = results["items"]
offset = results["offset"]

i = 0
total_pages = round(total_albums / 50)
while results["next"]:
    try:
        print(f"{i}/{total_pages}")
        i += 1
        last_next = results["next"]
        offset = results["offset"]
        results = sp.next(results)
        albums.extend(results["items"])
    except Exception as e:
        print(e)
        print(last_next)
        i -= 1
        results = sp.current_user_saved_albums(limit=50, offset=offset)

for index, album in enumerate(albums):
    if not album:
        print(index)
    if not album["album"]:
        print(index)

simplified_albums = [
    {
        "id": album["album"]["id"],
        "name": album["album"]["name"],
        "ordering_name": get_ordering_string(album["album"]["name"]),
        "artist": album["album"]["artists"][0]["name"],
    }
    for album in albums
    if album and album["album"]
]

sorted_albums = sorted(simplified_albums, key=sort_key)

with open("albums_total.json", "w") as main_file:
    json.dump(sorted_albums, main_file, ensure_ascii=False)

with open("albums_total.txt", "w") as second_file:
    for album in sorted_albums:
        album_name = album["name"]
        album_artist = album["artist"]

        second_file.write(f"{album_name} - {album_artist}: \n")
