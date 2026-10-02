"""Retain original review JSON, audit bytes, mirror publication and log replay."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from spotify_manager.application.artist_review_state import apply_review_event
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.utils.sorting import artist_sort_key


JsonReader = Callable[[Path, object], object]
JsonWriter = Callable[[Path, object], None]


def load_json(path: Path, default: object) -> object:
    """Read original JSON or return the original same missing-file default.

    Args:
        path: Original local file.
        default: Original fallback object.

    Returns:
        Original decoded JSON or same default.

    Raises:
        ArtistReviewError: Original local JSON is invalid.
        OSError: Original file cannot be read.
    """
    try:
        with open(path) as input_file:
            return cast(object, json.load(input_file))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ArtistReviewError(f"Invalid JSON in {path}.") from exc


def write_json_atomic(path: Path, value: object) -> None:
    """Write original UTF-8 JSON through a sibling temporary before replacement.

    Args:
        path: Original local destination.
        value: Original complete serializable value.

    Raises:
        OSError: Writing or replacement fails, retaining the original temporary.
        TypeError: Original value cannot be JSON-encoded.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(temporary_path, "w") as output_file:
        json.dump(value, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(path)


def append_events(path: Path, events: list[dict[str, object]]) -> None:
    """Retain original non-ASCII JSON Lines bytes and the empty-write guard.

    Args:
        path: Original local audit destination.
        events: Original ordered complete events.

    Raises:
        OSError: Original destination cannot be appended.
        TypeError: An original event cannot be JSON-encoded.
    """
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as output_file:
        for event in events:
            output_file.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_models[T: BaseModel](
    path: Path, model_type: type[T], read: JsonReader
) -> list[T]:
    """Retain original complete model construction and missing-file empty lists.

    Args:
        path: Original canonical mirror.
        model_type: Original complete validation model.
        read: Original caller-owned JSON read boundary.

    Returns:
        Original complete validated models in stored order.

    Raises:
        ArtistReviewError: Original root is not a list.
        ValueError: An original model record cannot be validated.
    """
    raw = read(path, [])
    if not isinstance(raw, list):
        raise ArtistReviewError(f"Expected a JSON list in {path}.")
    return [model_type.model_validate(item) for item in raw]


def save_artists(
    path: Path,
    artists: list[YourLibraryArtist],
    write: JsonWriter,
    publish: Callable[[Path], object],
) -> None:
    """Sort caller-owned artists, replace their mirror, then publish in that order.

    Args:
        path: Original canonical destination.
        artists: Original same mutable list to sort and persist.
        write: Original caller-owned atomic JSON writer.
        publish: Original canonical mirror publication boundary.
    """
    artists.sort(key=artist_sort_key)
    write(path, [artist.model_dump() for artist in artists])
    publish(path)


def load_cache(
    path: Path, refresh: bool, read: JsonReader
) -> dict[str, dict[str, object]]:
    """Retain original refresh-before-read and shallow catalog-cache validation.

    Args:
        path: Original complete metadata file.
        refresh: Original option to skip the existing cache.
        read: Original caller-owned JSON read boundary.

    Returns:
        Original same mutable complete metadata object or an empty refresh.

    Raises:
        ArtistReviewError: The original root is not an object.
    """
    if refresh:
        return {}
    raw = read(path, {})
    if not isinstance(raw, dict):
        raise ArtistReviewError(f"Expected a JSON object in {path}.")
    return cast(dict[str, dict[str, object]], raw)


def load_review_state(path: Path) -> ArtistReviewState:
    """Replay original nonblank valid JSON lines, retaining native object failures.

    Args:
        path: Original explicit legacy progress log.

    Returns:
        Original mutable completed and pending progress.

    Raises:
        OSError: Original log cannot be read.
        AttributeError: An original valid JSON line is not an object.
    """
    state = ArtistReviewState(set(), {}, {})
    if not path.exists():
        return state
    with open(path) as handle:
        for line in handle:
            _replay_line(state, line)
    return state


def _replay_line(state: ArtistReviewState, line: str) -> None:
    if not line.strip():
        return
    try:
        event = cast(dict[str, object], json.loads(line))
    except json.JSONDecodeError:
        return
    apply_review_event(state, event)
