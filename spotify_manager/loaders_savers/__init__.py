"""Functions to load data from files."""

# Standard Library
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from spotify_manager.application.legacy_library_effects import Comparison

# UFI
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.infrastructure import legacy_library_files as storage
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


# Album track lists fetched from the API are cached here so repeated album
# evaluations don't re-hit Spotify. Resolved relative to this package so it
# works regardless of the current working directory.
ALBUM_TRACKS_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "files" / "album_tracks_cache.json"
)
FILES_PATH = Path(__file__).resolve().parent.parent / "files"
CONTROL_FILE_PATH = FILES_PATH / "control_file.json"
TOTAL_ALBUMS_PATH = FILES_PATH / "albums_total.json"
TOTAL_ALBUMS_NEW_PATH = FILES_PATH / "albums_total_new.json"
YOUR_LIBRARY_PATH = FILES_PATH / "YourLibrary.json"
COMPARISON_PATH = FILES_PATH / "comparison.json"
TOTAL_ARTISTS_PATH = FILES_PATH / "artists_total.json"
STATS_HISTORY_PATH = FILES_PATH / "stats_history.json"
STATS_FILE_PATH = FILES_PATH / "stats_file.json"


def serialize_model_list(model_list: Sequence[BaseModel]) -> list[dict[str, Any]]:
    """Serialize a model list into.

    Args:
        model_list: Original persisted facts.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.serialize_model_list(model_list)


def load_album_tracks_cache() -> dict[str, list[dict[str, Any]]]:
    """Load the album-tracklist cache (album id -> list of track dicts).

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_album_tracks_cache(ALBUM_TRACKS_CACHE_PATH)


def save_album_tracks_cache(cache: dict[str, list[dict[str, Any]]]) -> None:
    """Persist the album-tracklist cache, creating the files dir if needed.

    Args:
        cache: Original persisted facts.

    """
    return storage.save_album_tracks_cache(cache, ALBUM_TRACKS_CACHE_PATH)


def load_control_file() -> list[ControlFileItem]:
    """Load control file.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_control_file(CONTROL_FILE_PATH, print)


def load_total_albums_file() -> list[SimplifiedAlbum]:
    """Load total albums file.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_total_albums_file(TOTAL_ALBUMS_PATH, print)


def load_total_albums_new_file() -> list[YourLibraryAlbum]:
    """Load total albums file.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_total_albums_new_file(TOTAL_ALBUMS_NEW_PATH, print)


def load_your_library_file() -> YourLibraryFile:
    """Load your library file.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_your_library_file(YOUR_LIBRARY_PATH, print)


def load_comparison_file() -> Comparison:
    """.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_comparison_file(COMPARISON_PATH)


def load_total_artists_file() -> list[YourLibraryArtist]:
    """Load total artists file.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_total_artists_file(TOTAL_ARTISTS_PATH, print)


def load_stats_history_file() -> dict[str, StatsReport]:
    """Load liked tracks file.

    Returns:
        Original file values with unchanged validation and native errors.
    """
    return storage.load_stats_history_file(STATS_HISTORY_PATH, print)


def save_total_albums_file(total_albums_file_items: list[SimplifiedAlbum]) -> None:
    """Save total albums file.

    Args:
        total_albums_file_items: Original persisted facts.

    """
    return storage.save_total_albums_file(
        total_albums_file_items, TOTAL_ALBUMS_PATH, print, serialize_model_list
    )


def save_total_albums_new_file(total_albums_file_items: list[YourLibraryAlbum]) -> None:
    """Save total albums file.

    Args:
        total_albums_file_items: Original persisted facts.

    """
    return storage.save_total_albums_new_file(
        total_albums_file_items,
        TOTAL_ALBUMS_NEW_PATH,
        print,
        serialize_model_list,
        publish_managed_path,
    )


def save_total_artists_file(total_artists_file_items: list[YourLibraryArtist]) -> None:
    """Save total artists file.

    Args:
        total_artists_file_items: Original persisted facts.

    """
    return storage.save_total_artists_file(
        total_artists_file_items,
        TOTAL_ARTISTS_PATH,
        print,
        serialize_model_list,
        publish_managed_path,
    )


def save_control_file(control_file_items: list[ControlFileItem]) -> None:
    """Save total albums file.

    Args:
        control_file_items: Original persisted facts.

    """
    return storage.save_control_file(
        control_file_items, CONTROL_FILE_PATH, print, serialize_model_list
    )


def save_stats_file(stats_file_items: StatsFileItem) -> None:
    """Save total albums file.

    Args:
        stats_file_items: Original persisted facts.

    """
    return storage.save_stats_file(stats_file_items, STATS_FILE_PATH, print)


def save_stats_history(stats_history: dict[str, StatsReport]) -> None:
    """Save total albums file.

    Args:
        stats_history: Original persisted facts.

    """
    return storage.save_stats_history(stats_history, STATS_HISTORY_PATH, print)


def save_comparison_file(comparison_dict: Comparison) -> None:
    """.

    Args:
        comparison_dict: Original persisted facts.

    """
    return storage.save_comparison_file(comparison_dict, COMPARISON_PATH, print)
