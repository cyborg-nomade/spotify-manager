"""Original JSON persistence, byte formatting and publication boundaries.

Unchecked JSON values remain permissive here; callers retain native legacy errors.
"""

import json
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import cast

from pydantic import BaseModel

from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


type Serialize = Callable[[Sequence[BaseModel]], list[dict[str, Any]]]


class Publish(Protocol):
    """Publish a managed file after its original accepted replacement."""

    def __call__(self, path: Path, *, source: str) -> object:
        """Accept the original publication.

        Args:
            path: Original accepted file.
            source: Original publication label.

        Returns:
            Original external publication outcome.
        """
        ...


def serialize_model_list(model_list: Sequence[BaseModel]) -> list[dict[str, Any]]:
    """Serialize original models without changing dump mode or field order.

    Args:
        model_list: Original Pydantic model values.

    Returns:
        Original result with unchanged native boundary errors.
    """
    result = []
    for item in model_list:
        result.append(item.model_dump())
    return result


def load_album_tracks_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load the album-tracklist cache (album id -> list of track dicts).

    Args:
        path: Original file location; encoding and write timing remain unchanged.

    Returns:
        Original result with unchanged native boundary errors.
    """
    try:
        with open(path) as cache_file:
            return cast(dict[str, list[dict[str, Any]]], json.load(cache_file))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_album_tracks_cache(cache: dict[str, list[dict[str, Any]]], path: Path) -> None:
    """Persist the album-tracklist cache, creating the files dir if needed.

    Args:
        cache: Original unchecked cached track mapping.
        path: Original file location; encoding and write timing remain unchanged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as cache_file:
        json.dump(cache, cache_file, ensure_ascii=False)


def load_control_file(path: Path, echo: Echo) -> list[ControlFileItem]:
    """Load control file.

    Args:
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    echo("Loading control file...")
    with open(path) as control_file:
        result_dict = json.load(control_file)
        echo("OK!")
        return [ControlFileItem.model_validate(s) for s in result_dict]


def load_total_albums_file(path: Path, echo: Echo) -> list[SimplifiedAlbum]:
    """Load total albums file.

    Args:
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    with open(path) as main_file:
        echo("Loading Total Albums file")
        result_dict = json.load(main_file)
        echo("Done.")
        return [SimplifiedAlbum.model_validate(s) for s in result_dict]


def load_total_albums_new_file(path: Path, echo: Echo) -> list[YourLibraryAlbum]:
    """Load total albums file.

    Args:
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    with open(path) as main_file:
        echo("Loading Total Albums file")
        result_dict = json.load(main_file)
        echo("Done.")
        return [YourLibraryAlbum.model_validate(s) for s in result_dict]


def load_your_library_file(path: Path, echo: Echo) -> YourLibraryFile:
    """Load your library file.

    Args:
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    with open(path) as main_file:
        echo("Loading Your Library file..")
        result_dict = json.load(main_file)
        echo("Done.")
        return YourLibraryFile.model_validate(result_dict)


def load_comparison_file(path: Path) -> Comparison:
    """Read the original unchecked comparison JSON.

    Args:
        path: Original file location; encoding and write timing remain unchanged.

    Returns:
        Original result with unchanged native boundary errors.
    """
    with open(path) as main_file:
        result_dict = json.load(main_file)
        return cast(Comparison, result_dict)


def load_total_artists_file(path: Path, echo: Echo) -> list[YourLibraryArtist]:
    """Load total artists file.

    Args:
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    with open(path) as main_file:
        echo("Loading total artists file..")
        result_dict = json.load(main_file)
        echo("Done.")
        return [YourLibraryArtist.model_validate(a) for a in result_dict]


def load_stats_history_file(path: Path, echo: Echo) -> dict[str, StatsReport]:
    """Load liked tracks file.

    Args:
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.

    Returns:
        Original result with unchanged native boundary errors.
    """
    with open(path) as main_file:
        echo("Loading liked tracks file..")
        result_dict: dict[str, object] = json.load(main_file)
        echo("Done.")
        parsed_dict = validate_history(result_dict)
        return parsed_dict


def save_total_albums_file(
    total_albums_file_items: list[SimplifiedAlbum],
    path: Path,
    echo: Echo,
    serialize: Serialize,
) -> None:
    """Save total albums file.

    Args:
        total_albums_file_items: Original album entries.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
        serialize: Original serializer, evaluated after opening the target.
    """
    echo("Saving total albums file...")
    with open(path, "w") as main_file:
        json.dump(serialize(total_albums_file_items), main_file, ensure_ascii=False)
        echo("OK!")


def save_total_albums_new_file(
    total_albums_file_items: list[YourLibraryAlbum],
    path: Path,
    echo: Echo,
    serialize: Serialize,
    publish: Publish,
) -> None:
    """Save total albums file.

    Args:
        total_albums_file_items: Original album entries.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
        serialize: Original serializer, evaluated after opening the target.
        publish: Original managed-file publication after accepted replacement.
    """
    echo("Saving total albums file...")
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w") as main_file:
        json.dump(serialize(total_albums_file_items), main_file, ensure_ascii=False)
    temporary.replace(path)
    publish(path, source="library routine")
    echo("OK!")


def save_total_artists_file(
    total_artists_file_items: list[YourLibraryArtist],
    path: Path,
    echo: Echo,
    serialize: Serialize,
    publish: Publish,
) -> None:
    """Save total artists file.

    Args:
        total_artists_file_items: Original artist entries.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
        serialize: Original serializer, evaluated after opening the target.
        publish: Original managed-file publication after accepted replacement.
    """
    echo("Saving total artists file...")
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w") as main_file:
        json.dump(
            serialize(total_artists_file_items),
            main_file,
            ensure_ascii=False,
        )
    temporary.replace(path)
    publish(path, source="library routine")
    echo("OK!")


def save_control_file(
    control_file_items: list[ControlFileItem],
    path: Path,
    echo: Echo,
    serialize: Serialize,
) -> None:
    """Save total albums file.

    Args:
        control_file_items: Original control entries.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
        serialize: Original serializer, evaluated after opening the target.
    """
    echo("Saving control file...")
    with open(path, "w") as main_file:
        json.dump(serialize(control_file_items), main_file, ensure_ascii=False)
        echo("OK!")


def save_stats_file(stats_file_items: StatsFileItem, path: Path, echo: Echo) -> None:
    """Save total albums file.

    Args:
        stats_file_items: Original statistics model.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
    """
    echo("Saving stats file...")
    with open(path, "w") as main_file:
        json.dump(stats_file_items.model_dump(), main_file, ensure_ascii=False)
        echo("OK!")


def save_stats_history(
    stats_history: dict[str, StatsReport], path: Path, echo: Echo
) -> None:
    """Save total albums file.

    Args:
        stats_history: Original typed period history.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
    """
    echo("Saving stats file...")
    with open(path, "w") as main_file:
        serialized_dict = serialize_history(stats_history)
        json.dump(serialized_dict, main_file, ensure_ascii=False)
        echo("OK!")


def save_comparison_file(comparison_dict: Comparison, path: Path, echo: Echo) -> None:
    """Write the original unchecked comparison JSON.

    Args:
        comparison_dict: Original unchecked add/remove mapping.
        path: Original file location; encoding and write timing remain unchanged.
        echo: Original visible presenter.
    """
    echo("Saving comparison file...")
    with open(path, "w") as main_file:
        json.dump(comparison_dict, main_file, ensure_ascii=False)
        echo("OK!")


def validate_history(payload: dict[str, object]) -> dict[str, StatsReport]:
    """Validate original history values without reordering their period keys.

    Args:
        payload: Original unchecked history mapping.

    Returns:
        Original result with unchanged native boundary errors.
    """
    result = {}
    for key, value in payload.items():
        result[key] = StatsReport.model_validate(value)
    return result


def serialize_history(history: dict[str, StatsReport]) -> dict[str, Any]:
    """Serialize history after the original target has been truncated.

    Args:
        history: Original typed history values.

    Returns:
        Original result with unchanged native boundary errors.
    """
    result = {}
    for key, value in history.items():
        result[key] = value.model_dump()
    return result
