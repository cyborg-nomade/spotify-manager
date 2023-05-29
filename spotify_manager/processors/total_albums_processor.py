"""Data processors for total albums list."""
# Standard Library
from datetime import datetime
from operator import itemgetter

# UFI

from spotify_manager.client import get_spotipy_client
from spotify_manager.loaders_savers import save_total_albums_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.utils.sorting import get_ordering_string
from spotify_manager.utils.sorting import sort_key


ALBUMS_TO_ADD = 250


def update_total_album_list() -> list[ControlFileItem]:
    """Get, update, save and return all saved albums."""
    print("Updating total albums...")
    sp = get_spotipy_client()
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
        SimplifiedAlbum(
            spotify_id=album["album"]["id"],
            name=album["album"]["name"],
            artist=SimplifiedArtist(
                spotify_id=album["album"]["artists"][0]["id"],
                name=album["album"]["artists"][0]["name"],
            ),
            ordering_string=get_ordering_string(album["album"]["name"]),
        )
        for album in albums
        if album and album["album"]
    ]

    sorted_albums = sorted(simplified_albums, key=sort_key)

    control_file_items = [
        ControlFileItem(album=album, result="") for album in sorted_albums
    ]

    save_total_albums_file(control_file_items)
    print("Albums updated!")

    return control_file_items


def get_months_items(
    all_albums: list[ControlFileItem], initial_index: int
) -> list[ControlFileItem]:
    """Get this months albums from all albums, starting from initial index."""
    return all_albums[initial_index : initial_index + ALBUMS_TO_ADD]


def create_playlist() -> str:
    """Create a playlist and return id."""
    print("Creating playlist...")
    sp = get_spotipy_client()
    playlist_name = f"{str(datetime.now().year)}.{str(datetime.now().month)}"
    result = sp.user_playlist_create("12161013970", name=playlist_name)
    print("Done!")
    return result["id"]


def get_ordered_tracks(album: SimplifiedAlbum) -> list[SimplifiedTrack]:
    """Return the list of ordered tracks for the given album."""
    sp = get_spotipy_client()

    results = sp.album_tracks(album.spotify_id)
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
    return [SimplifiedTrack.parse_obj(s) for s in sorted_tracks]


def append_to_playlist(ordered_tracks: list[SimplifiedTrack], playlist_id: str) -> None:
    """Append given list of tracks to playlist."""
    print("Appending tracks to playlist...")
    track_uris = [track.uri for track in ordered_tracks]

    sp = get_spotipy_client()
    sp.playlist_add_items(playlist_id, track_uris)
    print("Done!")


def add_monthly_albums(
    control_file: list[ControlFileItem],
    total_album_list: list[ControlFileItem],
    starting_index: int,
):
    """
    Add monthly albums tracks to playlist.

    Receives initial index of the first album to be added.
    Returns bool whether the process worked accordingly.
    """
    print("Adding monthly albums to playlist and control file...")
    try:
        this_month_items = get_months_items(total_album_list, starting_index)
        for item in this_month_items:
            ordered_tracks = get_ordered_tracks(item.album)
            playlist_id = create_playlist()
            append_to_playlist(ordered_tracks, playlist_id)
            control_file.append(item)
            print(f"Added album {item.album.name} to control file")
        return True
    except Exception as e:
        print(e)
        return False
