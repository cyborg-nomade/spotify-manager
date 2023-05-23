"""Add monthly albums into playlist."""

import json
from operator import itemgetter

import spotipy
from spotipy.oauth2 import SpotifyOAuth


def load_all_albums() -> list[dict]:
    """Load all albums from file."""
    with open("/home/ufiori/dev/spotify-manager/albums_total.json", "r") as main_file:
        return json.load(main_file)


def get_months_albums(all_albums: list[dict], initial_index: int) -> list[dict]:
    """Get this months albums from all albums, starting from initial index."""
    return all_albums[initial_index : initial_index + 243]


def get_ordered_tracks(album: dict) -> list[dict]:
    """Return the list of ordered tracks for the given album."""
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

    results = sp.album_tracks(album["id"])
    tracks = results["items"]

    while results["next"]:
        results = sp.next(results)
        tracks.extend(results["items"])

    simplified_tracks = [
        {
            "disc_number": int(track["disc_number"]),
            "track_number": int(track["track_number"]),
            "uri": track["uri"],
        }
        for track in tracks
        if track
    ]

    sorted_tracks = sorted(
        simplified_tracks, key=itemgetter("disc_number", "track_number")
    )
    return sorted_tracks


def append_to_playlist(ordered_tracks: list[dict]) -> None:
    """Append given list of tracks to playlist."""
    SPOTIPY_CLIENT_ID = "fc70707ebf5d4ca3af5bdcd88bdd9b17"
    SPOTIPY_CLIENT_SECRET = "bc624df47d1c48b5a3f5dcef186c2b6c"
    SPOTIPY_REDIRECT_URI = "http://localhost"

    scope = ["playlist-modify-public", "playlist-modify-private"]

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scope,
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
            redirect_uri=SPOTIPY_REDIRECT_URI,
        )
    )
    track_uris = [track["uri"] for track in ordered_tracks]
    sp.playlist_add_items("2r6gUPqqfTMicaHuv31d7m", track_uris)


def add_monthly_albums_to_playlist(initial_index: int) -> bool:
    """Add monthly albums tracks to playlist.

    Receives initial index of the first album to be added.
    Returns bool whether the process worked accordingly."""
    try:
        all_albums = load_all_albums()
        this_month_albums = get_months_albums(all_albums, initial_index)
        # print(this_month_albums)
        for album in this_month_albums:
            ordered_tracks = get_ordered_tracks(album)
            print(ordered_tracks)
            append_to_playlist(ordered_tracks)
        return True
    except Exception as e:
        print(e)
        return False


if __name__ == "__main__":
    result = add_monthly_albums_to_playlist(38551)
    print(result)
