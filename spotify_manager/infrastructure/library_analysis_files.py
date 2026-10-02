"""Original tolerant Spotify library rows and resumable staging bytes."""

import json
import shutil
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import cast

from pydantic import BaseModel

from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.domain.library_analysis_values import IncompleteLiveResourceError
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


class JsonReader(Protocol):
    """Load unvalidated legacy JSON while preserving caller default semantics."""

    def __call__(self, path: Path, default: object | None = None) -> Any:
        """Read the permissive external JSON boundary.

        Args:
            path: Original complete file location.
            default: Original missing-file value.

        Returns:
            Unvalidated legacy JSON, preserving native malformed-value errors.
        """
        ...


def reset_staging(path: Path) -> None:
    """Replace original staging only when beginning a fresh incompatible run.

    Args:
        path: Original complete staging directory.
    """
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def remove(path: Path) -> None:
    """Remove original staging without failing on an already absent file.

    Args:
        path: Original complete candidate or resource staging file.
    """
    path.unlink(missing_ok=True)


def append_event(
    now: Callable[[], str],
    /,
    paths: LibraryAnalysisPaths,
    run_id: str,
    event: str,
    **details: object,
) -> None:
    """Append original timestamped analysis audit bytes.

    Args:
        paths: Original independent output family.
        run_id: Original sortable run identity.
        event: Original audit event name.
        now: Original UTC timestamp observation.
        details: Original complete event facts.
    """
    paths.event_log.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": now(),
        "run_id": run_id,
        "mode": paths.mode,
        "event": event,
        **details,
    }
    with paths.event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_models(
    path: Path,
    models: Sequence[BaseModel],
    *,
    write: Callable[[Path, object], None],
    publish: Callable[[Path, str], None],
) -> None:
    """Accept original complete model bytes before managed-file publication.

    Args:
        path: Original complete output location.
        models: Original ordered complete model values.
        write: Original atomic JSON acceptance boundary.
        publish: Original subsequent managed-file publication.
    """
    write(path, [model.model_dump() for model in models])
    publish(path, "Spotify live library refresh")


def latest_export_artists(
    paths: LibraryAnalysisPaths, load: Callable[[LibraryAnalysisPaths], YourLibraryFile]
) -> list[YourLibraryArtist]:
    """Read original export artist candidates only when the durable file exists.

    Args:
        paths: Original independent output family.
        load: Original tolerant export read.

    Returns:
        Original latest export artists, or no candidates for an absent export.
    """
    if not paths.your_library.exists():
        return []
    return load(paths).artists


def write_json_atomic(path: Path, value: object) -> None:
    """Write JSON through a sibling temporary file and atomically replace it.

    Args:
        path: Original complete file or staging location.
        value: Original complete JSON value to accept.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(path: Path, default: object | None = None) -> Any:
    """Load JSON, returning ``default`` when the file does not exist.

    Args:
        path: Original complete file or staging location.
        default: Original value returned when the file is absent.


    Returns:
        Unvalidated original external JSON or the caller-supplied default.
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibrarySyncError(f"Could not read valid JSON from {path}.") from exc


def append_models_jsonl(path: Path, models: Sequence[BaseModel]) -> None:
    """Append models to a resumable JSON-lines staging file.

    Args:
        path: Original complete file or staging location.
        models: Original complete ordered model values.
    """
    if not models:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for model in models:
            handle.write(json.dumps(model.model_dump(), ensure_ascii=False) + "\n")


def track_from_saved_item(item: object) -> YourLibraryTrack | None:
    """Convert one Spotify saved-track item into the local model.

    Args:
        item: Original unvalidated Spotify boundary row.


    Returns:
        Original saved-track model or none for unusable raw facts.
    """
    if not isinstance(item, dict) or not isinstance(item.get("track"), dict):
        return None
    track = item["track"]
    artists = track.get("artists")
    primary = artists[0] if isinstance(artists, list) and artists else {}
    album = track.get("album")
    spotify_id = track.get("id")
    name = track.get("name")
    artist_name = primary.get("name") if isinstance(primary, dict) else None
    album_name = album.get("name") if isinstance(album, dict) else None
    if not spotify_id or not name or not artist_name or not album_name:
        return None
    return YourLibraryTrack(
        artist=str(artist_name),
        album=str(album_name),
        track=str(name),
        uri=str(track.get("uri") or f"spotify:track:{spotify_id}"),
    )


def artist_from_api_item(item: object) -> YourLibraryArtist | None:
    """Convert one Spotify artist object into the local model.

    Args:
        item: Original unvalidated Spotify boundary row.


    Returns:
        Original artist model or none for unusable raw facts.
    """
    if not isinstance(item, dict):
        return None
    spotify_id = item.get("id")
    name = item.get("name")
    if not spotify_id or not name:
        return None
    return YourLibraryArtist(
        name=str(name),
        uri=str(item.get("uri") or f"spotify:artist:{spotify_id}"),
    )


def page_items(page: object, resource: ResourceName) -> list[object]:
    """Validate and return the item list from an offset page.

    Args:
        page: Original unvalidated live page envelope.
        resource: Original active library resource identity.


    Returns:
        The original mutable raw offset-page item list.
    """
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise IncompleteLiveResourceError(
            f"Spotify returned an invalid {resource} page."
        )
    return cast(list[object], page["items"])


def followed_artist_page_items(page: object) -> tuple[list[object], dict[str, object]]:
    """Validate and unpack a followed-artists cursor page.

    Args:
        page: Original unvalidated live page envelope.


    Returns:
        Original mutable artist items and page envelope.
    """
    if not isinstance(page, dict) or not isinstance(page.get("artists"), dict):
        raise IncompleteLiveResourceError(
            "Spotify returned an invalid followed-artists page."
        )
    artists = page["artists"]
    if not isinstance(artists.get("items"), list):
        raise IncompleteLiveResourceError(
            "Spotify returned an invalid followed-artists item list."
        )
    return cast(list[object], artists["items"]), cast(dict[str, object], artists)


def export_fingerprint(path: Path) -> dict[str, int]:
    """Return enough metadata to detect an export replaced between resumes.

    Args:
        path: Original complete file or staging location.


    Returns:
        Original export size and nanosecond modification time.
    """
    try:
        stat = path.stat()
    except OSError as exc:
        raise LibrarySyncError(f"Your Library export not found: {path}") from exc
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def load_model_list[T: BaseModel](
    path: Path, model: type[T], *, read: JsonReader
) -> list[T]:
    """Load a JSON array of models, treating a missing file as empty.

    Args:
        path: Original complete file or staging location.
        model: Original tolerant model constructor.
        read: Original permissive external JSON read.


    Returns:
        Original complete models in stored array order.
    """
    raw = read(path, default=[])
    if not isinstance(raw, list):
        raise LibrarySyncError(f"Expected a JSON list in {path}.")
    return [model.model_validate(item) for item in raw]


def load_your_library(
    paths: LibraryAnalysisPaths, *, read: JsonReader
) -> YourLibraryFile:
    """Load the Spotify export used exclusively by async analysis.

    Args:
        paths: Original independent output family.
        read: Original permissive external JSON read.


    Returns:
        Original validated export authority.
    """
    raw = read(paths.your_library)
    if raw is None:
        raise LibrarySyncError(f"Your Library export not found: {paths.your_library}")
    try:
        return YourLibraryFile.model_validate(raw)
    except ValueError as exc:
        raise LibrarySyncError(
            f"Your Library export is invalid: {paths.your_library}"
        ) from exc


def load_models_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Load models from JSON-lines staging, ignoring a torn final line.

    Args:
        path: Original complete file or staging location.
        model: Original tolerant model constructor.


    Returns:
        Original accepted staged models before a torn final record.
    """
    if not path.exists():
        return []
    models: list[T] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        item = _staged_model(path, model, line, index == len(lines) - 1)
        if item is None:
            break
        models.append(item)
    return models


def _staged_model[T: BaseModel](
    path: Path, model: type[T], line: str, final: bool
) -> T | None:
    try:
        return model.model_validate_json(line)
    except ValueError, json.JSONDecodeError:
        if final:
            return None
        raise LibrarySyncError(f"Invalid staging data in {path}.") from None
