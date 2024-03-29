"""Functions to load data from files."""

# Standard Library
import json

from pydantic import BaseModel

# UFI
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.your_library import YourLibraryFile


def serialize_model_list(model_list: list[BaseModel]) -> list[dict]:
    """Serialize a model list into."""
    return [item.dict() for item in model_list]


def load_control_file() -> list[ControlFileItem]:
    """Load control file."""
    print("Loading control file...")
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/control_file.json", "r"
    ) as control_file:
        result_dict = json.load(control_file)
        print("OK!")
        return [ControlFileItem.parse_obj(s) for s in result_dict]


def load_total_albums_file() -> list[SimplifiedAlbum]:
    """Load total albums file."""
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/albums_total.json", "r"
    ) as main_file:
        print("Loading Total Albums file")
        result_dict = json.load(main_file)
        print("Done.")
        return [SimplifiedAlbum.parse_obj(s) for s in result_dict]


def load_your_library_file() -> YourLibraryFile:
    """Load your library file."""
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/YourLibrary.json", "r"
    ) as main_file:
        print("Loading Your Library file..")
        result_dict = json.load(main_file)
        print("Done.")
        return YourLibraryFile.parse_obj(result_dict)


def load_comparison_file() -> None:
    """."""
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/comparison.json", "r"
    ) as main_file:
        result_dict = json.load(main_file)
        return result_dict


def save_total_albums_file(total_albums_file_items: list[SimplifiedAlbum]):
    """Save total albums file."""
    print("Saving total albums file...")
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/albums_total.json", "w"
    ) as main_file:
        json.dump(
            serialize_model_list(total_albums_file_items), main_file, ensure_ascii=False
        )
        print("OK!")


def save_control_file(control_file_items: list[ControlFileItem]) -> None:
    """Save total albums file."""
    print("Saving control file...")
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/control_file.json", "w"
    ) as main_file:
        json.dump(
            serialize_model_list(control_file_items), main_file, ensure_ascii=False
        )
        print("OK!")


def save_stats_file(stats_file_items: StatsFileItem):
    """Save total albums file."""
    print("Saving stats file...")
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/stats_file.json", "w"
    ) as main_file:
        json.dump(stats_file_items.dict(), main_file, ensure_ascii=False)
        print("OK!")


def save_comparison_file(comparison_dict: dict) -> None:
    """."""
    print("Saving comparison file...")
    with open(
        "/home/ufiori/dev/spotify-manager/spotify_manager/files/comparison.json", "w"
    ) as main_file:
        json.dump(comparison_dict, main_file, ensure_ascii=False)
        print("OK!")
