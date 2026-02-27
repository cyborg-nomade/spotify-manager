"""."""

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.models.file_items import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


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


def compare_albums(
    total_albums_file: list[YourLibraryAlbum],
    your_library_albums: list[YourLibraryAlbum],
) -> tuple[int, int]:
    """Compare albums and return removed and added."""
    print("Comparing album files...")
    your_library_albums_ids = [album.spotify_id for album in your_library_albums]
    total_albums_file_ids = [album.spotify_id for album in total_albums_file]

    added_albums = len(
        [
            album
            for album in your_library_albums
            if album.spotify_id not in total_albums_file_ids
        ]
    )
    removed_albums = len(
        [
            album
            for album in total_albums_file
            if album.spotify_id not in your_library_albums_ids
        ]
    )
    return removed_albums, added_albums


def compare_artists(
    total_artists_file: list[YourLibraryArtist],
    your_library_artists: list[YourLibraryArtist],
) -> tuple[int, int]:
    """Compare artists and return removed and added."""
    print("Comparing artist files...")
    your_library_artists_ids = [album.spotify_id for album in your_library_artists]
    total_artists_file_ids = [album.spotify_id for album in total_artists_file]

    added_artists = len(
        [
            artist
            for artist in your_library_artists
            if artist.spotify_id not in total_artists_file_ids
        ]
    )
    removed_artists = len(
        [
            artist
            for artist in total_artists_file
            if artist.spotify_id not in your_library_artists_ids
        ]
    )
    return removed_artists, added_artists


def compare_tracks(
    liked_tracks_file: list[YourLibraryTrack],
    your_library_tracks: list[YourLibraryTrack],
) -> tuple[int, int]:
    """Compare tracks and return removed and added."""
    print("Comparing track files...")
    your_library_tracks_ids = [album.spotify_id for album in your_library_tracks]
    liked_tracks_file_ids = [album.spotify_id for album in liked_tracks_file]

    added_tracks = len(
        [
            track
            for track in your_library_tracks
            if track.spotify_id not in liked_tracks_file_ids
        ]
    )
    removed_tracks = len(
        [
            track
            for track in liked_tracks_file
            if track.spotify_id not in your_library_tracks_ids
        ]
    )
    return removed_tracks, added_tracks
