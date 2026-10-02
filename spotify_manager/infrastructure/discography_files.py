"""Preserve original Discography state validation, atomic cleanup and audit bytes."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from spotify_manager.application.discography_values import DiscographyStateError
from spotify_manager.domain.discography_values import QUEUE_ORDER
from spotify_manager.domain.discography_values import ArtistSelection
from spotify_manager.domain.discography_values import QueueName


STATE_VERSION = 1


def default_state() -> dict[str, object]:
    """Return the initial queue-priority state.

    Returns:
        Original complete compatible result.
    """
    return {"version": STATE_VERSION, "next_queue": "requeue"}


def load_state(path: Path) -> dict[str, object]:
    """Load persisted queue priority without hiding malformed state.

    Args:
        path: Original path boundary.

    Returns:
        Original complete compatible result.

    Raises:
        DiscographyStateError: Original state or audit validation/persistence fails.
    """
    if not path.exists():
        return default_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscographyStateError(f"Discography state is invalid: {path}") from exc
    try:
        return validate_state(state)
    except DiscographyStateError as exc:
        raise DiscographyStateError(f"Discography state is invalid: {path}") from exc


def validate_state(state: object) -> dict[str, object]:
    """Validate discography queue rotation independently of storage.

    Args:
        state: Original state boundary.

    Returns:
        Original complete compatible result.

    Raises:
        DiscographyStateError: Original state or audit validation/persistence fails.
    """
    if (
        not isinstance(state, dict)
        or state.get("version") != STATE_VERSION
        or state.get("next_queue") not in QUEUE_ORDER
    ):
        raise DiscographyStateError("Discography state is invalid.")
    return state


def save_next_queue(
    next_queue: QueueName,
    path: Path,
) -> None:
    """Persist the next source queue through an atomic replacement.

    Args:
        next_queue: Original next queue boundary.
        path: Original path boundary.

    Raises:
        DiscographyStateError: Original state or audit validation/persistence fails.
    """
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(
                {"version": STATE_VERSION, "next_queue": next_queue},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise DiscographyStateError(
            f"Could not save discography state: {path}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def append_log(
    selection: ArtistSelection,
    next_queue: QueueName,
    path: Path,
    recorded_at: datetime,
) -> None:
    """Append one successfully removed artist with the exact release set.

    Args:
        selection: Original selection boundary.
        next_queue: Original next queue boundary.
        path: Original path boundary.
        recorded_at: Original recorded at boundary.

    Raises:
        DiscographyStateError: Original state or audit validation/persistence fails.
    """
    record = {
        "recorded_at": recorded_at.isoformat(),
        "artist_id": selection.spotify_id,
        "artist": selection.name,
        "source_queue": selection.source_queue,
        "releases": [asdict(release) for release in selection.releases],
        "markers": [asdict(marker) for marker in selection.markers],
        "next_queue": next_queue,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise DiscographyStateError(
            f"Could not write discography routine log: {path}"
        ) from exc
