"""Convertion utilities."""

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.processors.control_file_processors import enrich_album


def convert_albums(
    your_library_albums: list[YourLibraryAlbum],
) -> list[SimplifiedAlbum]:
    """Convert from YourLibraryAlbum to SimplifiedAlbum."""
    print("Converting to simplified album")
    sp = get_spotipy_client()
    return [enrich_album(album.spotify_id, sp) for album in your_library_albums]
