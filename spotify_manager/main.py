import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotify_manager.sorting import get_ordering_string

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
albums = results["items"]
offset = results["offset"]

i = 0
while results["next"]:
    try:
        print(i)
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


simplified_albums = [
    {
        "name": album["album"]["name"],
        "ordering_name": get_ordering_string(album["album"]["name"]),
        "artist": album["album"]["artists"][0]["name"],
    }
    for album in albums
]

sorted_albums = sorted(simplified_albums, key=lambda x: (x["ordering_name"]))

with open("albums_total.txt", "w") as main_file:
    for album in sorted_albums:
        album_name = album["name"]
        ordering_name = album["ordering_name"]

        # album_artist_name = album["artist"]

        # print(f"{album_name} - {ordering_name}: ")
        main_file.write(f"{album_name} - {ordering_name}: \n")
