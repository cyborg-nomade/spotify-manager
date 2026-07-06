"""Functions to load data from files."""

# Standard Library
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

# UFI
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


# Album track lists fetched from the API are cached here so repeated album
# evaluations don't re-hit Spotify. Resolved relative to this package so it
# works regardless of the current working directory.
ALBUM_TRACKS_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "files" / "album_tracks_cache.json"
)


def serialize_model_list(model_list: Sequence[BaseModel]) -> list[dict]:
    """Serialize a model list into."""
    return [item.model_dump() for item in model_list]


def load_album_tracks_cache() -> dict[str, list[dict]]:
    """Load the album-tracklist cache (album id -> list of track dicts)."""
    try:
        with open(ALBUM_TRACKS_CACHE_PATH) as cache_file:
            return json.load(cache_file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_album_tracks_cache(cache: dict[str, list[dict]]) -> None:
    """Persist the album-tracklist cache, creating the files dir if needed."""
    ALBUM_TRACKS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALBUM_TRACKS_CACHE_PATH, "w") as cache_file:
        json.dump(cache, cache_file, ensure_ascii=False)


def load_control_file() -> list[ControlFileItem]:
    """Load control file."""
    print("Loading control file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/control_file.json",
    ) as control_file:
        result_dict = json.load(control_file)
        print("OK!")
        return [ControlFileItem.model_validate(s) for s in result_dict]


def load_total_albums_file() -> list[SimplifiedAlbum]:
    """Load total albums file."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/albums_total.json",
    ) as main_file:
        print("Loading Total Albums file")
        result_dict = json.load(main_file)
        print("Done.")
        return [SimplifiedAlbum.model_validate(s) for s in result_dict]


def load_total_albums_new_file() -> list[YourLibraryAlbum]:
    """Load total albums file."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/albums_total_new.json",
    ) as main_file:
        print("Loading Total Albums file")
        result_dict = json.load(main_file)
        print("Done.")
        return [YourLibraryAlbum.model_validate(s) for s in result_dict]


def load_your_library_file() -> YourLibraryFile:
    """Load your library file."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/YourLibrary.json",
    ) as main_file:
        print("Loading Your Library file..")
        result_dict = json.load(main_file)
        print("Done.")
        return YourLibraryFile.model_validate(result_dict)


def load_comparison_file() -> dict:
    """."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/comparison.json",
    ) as main_file:
        result_dict = json.load(main_file)
        return result_dict


def load_total_artists_file() -> list[YourLibraryArtist]:
    """Load total artists file."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/artists_total.json",
    ) as main_file:
        print("Loading total artists file..")
        result_dict = json.load(main_file)
        print("Done.")
        return [YourLibraryArtist.model_validate(a) for a in result_dict]


def load_liked_tracks_file() -> list[YourLibraryTrack]:
    """Load liked tracks file."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/liked_tracks.json",
    ) as main_file:
        print("Loading liked tracks file..")
        result_dict = json.load(main_file)
        print("Done.")
        return [YourLibraryTrack.model_validate(t) for t in result_dict]


def load_stats_history_file() -> dict[str, StatsReport]:
    """Load liked tracks file."""
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/stats_history.json",
    ) as main_file:
        print("Loading liked tracks file..")
        result_dict: dict = json.load(main_file)
        print("Done.")
        parsed_dict = {k: StatsReport.model_validate(v) for k, v in result_dict.items()}
        return parsed_dict


def save_total_albums_file(total_albums_file_items: list[SimplifiedAlbum]) -> None:
    """Save total albums file."""
    print("Saving total albums file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/albums_total.json",
        "w",
    ) as main_file:
        json.dump(
            serialize_model_list(total_albums_file_items), main_file, ensure_ascii=False
        )
        print("OK!")


def save_total_albums_new_file(total_albums_file_items: list[YourLibraryAlbum]) -> None:
    """Save total albums file."""
    print("Saving total albums file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/albums_total_new.json",
        "w",
    ) as main_file:
        json.dump(
            serialize_model_list(total_albums_file_items), main_file, ensure_ascii=False
        )
        print("OK!")


def save_total_artists_file(total_artists_file_items: list[YourLibraryArtist]) -> None:
    """Save total artists file."""
    print("Saving total artists file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/artists_total.json",
        "w",
    ) as main_file:
        json.dump(
            serialize_model_list(total_artists_file_items),
            main_file,
            ensure_ascii=False,
        )
        print("OK!")


def save_liked_tracks_file(liked_tracks_file_items: list[YourLibraryTrack]) -> None:
    """Save liked tracks file."""
    print("Saving liked tracks file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/liked_tracks.json",
        "w",
    ) as main_file:
        json.dump(
            serialize_model_list(liked_tracks_file_items),
            main_file,
            ensure_ascii=False,
        )
        print("OK!")


def save_control_file(control_file_items: list[ControlFileItem]) -> None:
    """Save total albums file."""
    print("Saving control file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/control_file.json",
        "w",
    ) as main_file:
        json.dump(
            serialize_model_list(control_file_items), main_file, ensure_ascii=False
        )
        print("OK!")


def save_stats_file(stats_file_items: StatsFileItem) -> None:
    """Save total albums file."""
    print("Saving stats file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/stats_file.json",
        "w",
    ) as main_file:
        json.dump(stats_file_items.model_dump(), main_file, ensure_ascii=False)
        print("OK!")


def save_stats_history(stats_history: dict[str, StatsReport]) -> None:
    """Save total albums file."""
    print("Saving stats file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/stats_history.json",
        "w",
    ) as main_file:
        serialized_dict = {k: v.model_dump() for k, v in stats_history.items()}
        json.dump(serialized_dict, main_file, ensure_ascii=False)
        print("OK!")


def save_comparison_file(comparison_dict: dict) -> None:
    """."""
    print("Saving comparison file...")
    with open(
        "/Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/comparison.json",
        "w",
    ) as main_file:
        json.dump(comparison_dict, main_file, ensure_ascii=False)
        print("OK!")
