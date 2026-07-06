"""Tests for album ordering when processing YourLibrary exports."""

from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.processors import your_library_processors


def album(name: str, album_id: str) -> YourLibraryAlbum:
    """Build a saved album model."""
    return YourLibraryAlbum(
        artist="Radiohead",
        album=name,
        uri=f"spotify:album:{album_id}",
    )


def test_process_albums_saves_spotify_like_album_order(monkeypatch) -> None:
    saved_albums: list[list[YourLibraryAlbum]] = []
    incoming_albums = [
        album("A Moon Shaped Pool", "moon"),
        album("Zebra", "zebra"),
        album("The Bends", "bends"),
    ]

    monkeypatch.setattr(
        your_library_processors, "load_total_albums_new_file", lambda: []
    )
    monkeypatch.setattr(
        your_library_processors,
        "save_total_albums_new_file",
        lambda items: saved_albums.append(list(items)),
    )

    your_library_processors.process_albums(incoming_albums)

    assert [[album.album for album in saved] for saved in saved_albums] == [
        ["The Bends", "A Moon Shaped Pool", "Zebra"]
    ]
