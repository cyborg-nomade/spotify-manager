"""Preserve Palace canonical mirror files, backups and exact JSON Lines audits."""

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol
from typing import cast

from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.application.palace_values import PalaceOfMemoryStateError
from spotify_manager.application.palace_values import PalaceOfMemorySummary
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.models.your_library import YourLibraryAlbum


class _IsoDate(Protocol):
    """Original duck-typed date serialization boundary used by JSON audits."""

    def isoformat(self) -> str:
        """Serialize the original boundary value as ISO text.

        Returns:
            Original date serialization.
        """


def _date_text(value: object) -> str:
    return cast(_IsoDate, value).isoformat()


def load_saved_albums(path: Path, minimum: int = 5) -> tuple[YourLibraryAlbum, ...]:
    """Read original saved-model JSON with unchanged validation and error messages.

    Args:
        path: Original canonical mirror location.
        minimum: Original minimum usable mirror size.

    Returns:
        Original complete boundary models in file order.

    Raises:
        PalaceOfMemoryDataError: Original file, root, models or population is invalid.
    """
    try:
        with path.open(encoding="utf-8") as album_file:
            payload = json.load(album_file)
    except OSError as exc:
        raise PalaceOfMemoryDataError(f"Could not read saved albums: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PalaceOfMemoryDataError(
            f"Saved albums are invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {path}"
        ) from exc
    if not isinstance(payload, list):
        raise PalaceOfMemoryDataError(f"Saved albums must be a JSON list: {path}")
    albums = _models(payload, path)
    if len(albums) < minimum:
        raise PalaceOfMemoryDataError(f"At least {minimum} saved albums are required.")
    return albums


def _models(payload: list[object], path: Path) -> tuple[YourLibraryAlbum, ...]:
    try:
        return tuple(YourLibraryAlbum.model_validate(item) for item in payload)
    except (TypeError, ValueError) as exc:
        raise PalaceOfMemoryDataError(f"Saved albums are invalid: {path}") from exc


def append_audit(
    path: Path, record: SavedAlbumRefresh | PalaceOfMemorySummary, label: str
) -> None:
    """Append original UTF-8 JSON Lines records without changing field or date order.

    Args:
        path: Original caller-owned audit location.
        record: Original complete preflight or completed-run facts.
        label: Original path-error label.

    Raises:
        PalaceOfMemoryStateError: The original audit append fails.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(
                json.dumps(asdict(record), ensure_ascii=False, default=_date_text)
                + "\n"
            )
    except OSError as exc:
        raise PalaceOfMemoryStateError(f"Could not write {label}: {path}") from exc


def replace_saved_albums(
    path: Path,
    backups: Path,
    albums: tuple[YourLibraryAlbum, ...],
    clock: Callable[[], datetime],
    write: Callable[[Path, tuple[YourLibraryAlbum, ...]], None],
) -> str | None:
    """Back up original bytes before atomic model replacement and publication.

    Args:
        path: Original canonical mirror location.
        backups: Original backup directory.
        albums: Original complete canonical replacement.
        clock: Original independent backup timestamp boundary.
        write: Original atomic model writer and publication boundary.

    Returns:
        Original backup location when a previous file exists.

    Raises:
        PalaceOfMemoryStateError: Original backup, replacement or publication fails.
    """
    backup: Path | None = None
    try:
        if path.exists():
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / (
                clock().strftime("%Y%m%dT%H%M%S%fZ") + "-albums_total_new.json"
            )
            shutil.copy2(path, backup)
        write(path, albums)
    except OSError as exc:
        raise PalaceOfMemoryStateError(
            f"Could not publish refreshed saved albums: {path}"
        ) from exc
    return str(backup) if backup is not None else None
