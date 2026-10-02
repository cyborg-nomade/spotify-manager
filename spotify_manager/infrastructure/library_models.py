"""Shared tolerant saved-album conversion and newest-value model identity records."""

from collections.abc import Sequence

from spotify_manager.domain.library_analysis import deduplicate_models as deduplicate
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


type LibraryModel = YourLibraryAlbum | YourLibraryTrack | YourLibraryArtist


def deduplicate_models[T: LibraryModel](models: Sequence[T]) -> list[T]:
    """Deduplicate models by Spotify id while preserving the newest value.

    Args:
        models: Original complete boundary models in encounter order.

    Returns:
        Original latest values in first-identity encounter order.
    """
    return deduplicate(models)


def album_from_saved_item(item: object) -> YourLibraryAlbum | None:
    """Convert one Spotify saved-album item into the local model.

    Args:
        item: Original raw live saved-album row.

    Returns:
        Original complete model or none for unusable raw facts.
    """
    if not isinstance(item, dict) or not isinstance(item.get("album"), dict):
        return None
    album = item["album"]
    artists = album.get("artists")
    primary = artists[0] if isinstance(artists, list) and artists else {}
    spotify_id = album.get("id")
    name = album.get("name")
    artist_name = primary.get("name") if isinstance(primary, dict) else None
    if not spotify_id or not name or not artist_name:
        return None
    return YourLibraryAlbum(
        artist=str(artist_name),
        album=str(name),
        uri=str(album.get("uri") or f"spotify:album:{spotify_id}"),
    )
