"""Data processors for total albums list."""
# Standard Library
from datetime import datetime
from operator import itemgetter

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.loaders_savers import save_control_file
from spotify_manager.loaders_savers import save_total_albums_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.settings import Settings
from spotify_manager.utils.sorting import get_ordering_string
from spotify_manager.utils.sorting import sort_key


settings = Settings()


def update_total_album_list(just_update: bool) -> list[SimplifiedAlbum]:
    """Get, update, save and return all saved albums."""
    print("Updating total albums...")
    sp = get_spotipy_client()
    offset = 0

    if just_update:
        already_stored_albums = load_total_albums_file()
        offset = len(already_stored_albums)

    results = sp.current_user_saved_albums(limit=settings.limit, offset=offset)
    total_albums = results["total"]
    albums = results["items"]
    offset = results["offset"]

    i = 0
    total_pages = round((total_albums - offset) / settings.limit)
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
            results = sp.current_user_saved_albums(limit=settings.limit, offset=offset)

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

    already_stored_albums.extend(simplified_albums)

    sorted_albums = sorted(already_stored_albums, key=sort_key)

    parsed_albums = [SimplifiedAlbum.parse_obj(album) for album in sorted_albums]

    save_total_albums_file(parsed_albums)
    print("Albums updated!")

    return parsed_albums


def get_months_items(
    all_albums: list[SimplifiedAlbum], initial_index: int
) -> list[SimplifiedAlbum]:
    """Get this months albums from all albums, starting from initial index."""
    return all_albums[initial_index : initial_index + settings.albums_to_add]


def create_playlist() -> str:
    """Create a playlist and return id."""
    print("Creating playlist...")
    sp = get_spotipy_client()
    year = str(datetime.now().year)
    month = (
        str(datetime.now().month)
        if datetime.now().month >= 10
        else f"0{str(datetime.now().month)}"
    )
    playlist_name = f"{year}.{month}"
    print(f"Playlist name: {playlist_name}")
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
    if len(ordered_tracks) <= 100:
        sp.playlist_add_items(playlist_id, track_uris)
    else:
        for i in range(0, len(ordered_tracks), 100):
            sp.playlist_add_items(playlist_id, track_uris[i : i + 100])
    print("Done!")


def add_monthly_albums(
    control_file: list[ControlFileItem],
    total_album_list: list[SimplifiedAlbum],
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
        playlist_id = create_playlist()
        for item in this_month_items:
            ordered_tracks = get_ordered_tracks(item)
            append_to_playlist(ordered_tracks, playlist_id)
            control_file.append(ControlFileItem(album=item, result=""))
            print(f"Added album {item.name} to control file")
        save_control_file(control_file)
        return True
    except Exception as e:
        print(e)
        return False
