"""Parse Palace manual positions and tolerant durable cursor records."""

import json
from datetime import datetime
from pathlib import Path
from typing import cast

from spotify_manager.application.palace_values import PalaceOfMemoryConfigError
from spotify_manager.application.palace_values import PalaceOfMemoryStateError
from spotify_manager.domain.palace_albums import AlbumFacts


def validate_state(payload: object) -> dict[str, object]:
    """Validate original cursor shape while retaining unknown fields and booleans.

    Args:
        payload: Original decoded durable record.

    Returns:
        The original complete mutable dictionary.

    Raises:
        PalaceOfMemoryStateError: Original root or fallback position is invalid.
    """
    if not isinstance(payload, dict):
        raise PalaceOfMemoryStateError("Palace state must be an object.")
    fallback = payload.get("next_alphabetical_index", 0)
    if not isinstance(fallback, int) or fallback < 0:
        raise PalaceOfMemoryStateError(
            "Palace state has an invalid alphabetical index."
        )
    return cast(dict[str, object], payload)


def load_state(path: Path) -> dict[str, object]:
    """Read original cursor JSON with unchanged path and parsing error translations.

    Args:
        path: Caller-owned durable cursor location.

    Returns:
        Original mutable cursor document, or empty when missing.

    Raises:
        PalaceOfMemoryStateError: Original file cannot be read or validated.
    """
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as state_file:
            payload = json.load(state_file)
    except OSError as exc:
        raise PalaceOfMemoryStateError(f"Could not read Palace state: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PalaceOfMemoryStateError(
            f"Palace state is invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {path}"
        ) from exc
    try:
        return validate_state(payload)
    except PalaceOfMemoryStateError as exc:
        raise PalaceOfMemoryStateError(f"Palace state is invalid: {path}") from exc


def save_state(payload: dict[str, object], path: Path) -> None:
    """Atomically replace original complete cursor JSON without merging extra fields.

    Args:
        payload: Original complete replacement namespace.
        path: Caller-owned durable cursor location.

    Raises:
        PalaceOfMemoryStateError: Original validation or replacement fails.
    """
    normalized = validate_state(payload)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as state_file:
            json.dump(normalized, state_file, ensure_ascii=False, indent=2)
            state_file.write("\n")
        temporary.replace(path)
    except OSError as exc:
        raise PalaceOfMemoryStateError(f"Could not save Palace state: {path}") from exc


def cursor_record(
    next_index: int, last: AlbumFacts, now: datetime
) -> dict[str, object]:
    """Serialize original successful next-position facts with the supplied write clock.

    Args:
        next_index: Original next zero-based mirror position.
        last: Original last selected complete saved facts.
        now: Original independent write timestamp.

    Returns:
        Original complete replacement namespace.
    """
    return {
        "updated_at": now.isoformat(),
        "next_alphabetical_index": next_index,
        "last_alphabetical_album_id": last.spotify_id,
        "last_alphabetical_artist": last.artist,
        "last_alphabetical_album": last.album,
    }


def resolve_start(albums: tuple[AlbumFacts, ...], reference: str) -> int:
    """Parse original one-based position, album reference or exact normalized label.

    Args:
        albums: Original refreshed canonical mirror.
        reference: Original manual configuration value.

    Returns:
        Original unambiguous zero-based selected position.

    Raises:
        PalaceOfMemoryConfigError: Original reference is empty, invalid or ambiguous.
    """
    value = reference.strip()
    if not value:
        raise PalaceOfMemoryConfigError("Alphabetical start cannot be empty.")
    if value.isdecimal():
        return _numeric_position(value, len(albums))
    identity = _album_identity(value)
    for index, album in enumerate(albums):
        if album.spotify_id == identity:
            return index
    return _label_position(albums, value, reference)


def _numeric_position(value: str, size: int) -> int:
    position = int(value)
    if not 1 <= position <= size:
        raise PalaceOfMemoryConfigError(
            f"Alphabetical position must be between 1 and {size}."
        )
    return position - 1


def _album_identity(value: str) -> str:
    if value.startswith("spotify:album:"):
        return value.removeprefix("spotify:album:").split("?", 1)[0]
    if "open.spotify.com/album/" in value:
        return (
            value.split("open.spotify.com/album/", 1)[1]
            .split("?", 1)[0]
            .split("/", 1)[0]
        )
    return value


def _label_position(albums: tuple[AlbumFacts, ...], value: str, reference: str) -> int:
    expected = " ".join(value.casefold().split())
    matches = []
    for index, album in enumerate(albums):
        title = " ".join(album.album.casefold().split())
        label = " ".join(f"{album.artist} - {album.album}".casefold().split())
        if expected in {title, label}:
            matches.append(index)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        examples = _examples(albums, matches)
        raise PalaceOfMemoryConfigError(
            f"Alphabetical start is ambiguous; use a Spotify album id: {examples}"
        )
    raise PalaceOfMemoryConfigError(
        f"Alphabetical start was not found in the refreshed saved albums: {reference}"
    )


def _examples(albums: tuple[AlbumFacts, ...], matches: list[int]) -> str:
    result = []
    for index in matches[:5]:
        album = albums[index]
        result.append(f"{album.artist} - {album.album} ({album.spotify_id})")
    return "; ".join(result)
