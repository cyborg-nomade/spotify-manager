"""Original tolerant nightly API JSON and durable timestamp codecs."""

import json
from datetime import UTC
from datetime import datetime

from spotify_manager.application.automation_values import DURABLE_ARTIFACT_FILENAMES
from spotify_manager.application.automation_values import AutomationError


def decode_response(raw: bytes) -> object:
    """Decode original empty or JSON response bytes.

    Args:
        raw: Original complete HTTP body.

    Returns:
        Original decoded JSON, or an empty object for no bytes.

    Raises:
        AutomationError: Original JSON decoding fails.
        UnicodeDecodeError: Original bytes cannot be decoded as JSON text.
    """
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise AutomationError("Space returned a non-JSON response.") from error


def artifact_updates(payload: object) -> dict[str, datetime] | None:
    """Retain original last valid aware timestamp per known existing artifact.

    Args:
        payload: Original unvalidated status response.

    Returns:
        Original timestamp observations or no valid file container.
    """
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return None
    updated = {}
    for item in files:
        if not isinstance(item, dict) or not item.get("exists"):
            continue
        observation = _artifact_timestamp(item)
        if observation is not None:
            filename, timestamp = observation
            updated[filename] = timestamp
    return updated


def _artifact_timestamp(item: dict[str, object]) -> tuple[str, datetime] | None:
    filename = str(item.get("filename") or "")
    raw = item.get("updated_at")
    if filename not in DURABLE_ARTIFACT_FILENAMES or not isinstance(raw, str):
        return None
    try:
        timestamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return filename, timestamp.astimezone(UTC)
