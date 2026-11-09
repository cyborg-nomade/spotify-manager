"""Original tolerant nightly API JSON and durable timestamp codecs."""

import json
from datetime import UTC
from datetime import datetime
from typing import cast

from spotify_manager.application.automation_values import DURABLE_ARTIFACT_FILENAMES
from spotify_manager.application.automation_values import AutomationError
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts


def flush_observation(payload: object) -> FlushState:
    """Decode the policy endpoint using only the Actions standard library.

    Args:
        payload: Untrusted HTTP status or check response.

    Returns:
        Validated state with normalized UTC timestamps.

    Raises:
        AutomationError: Control, counts, timestamps or effective mode are invalid.
    """
    if not isinstance(payload, dict):
        raise AutomationError("Flush Mode returned an invalid status.")
    control, automatic = payload.get("control"), payload.get("automatic_active")
    error = payload.get("error")
    if not isinstance(control, str) or control not in {"automatic", "on", "off"}:
        raise AutomationError("Flush Mode returned an invalid control.")
    if type(automatic) is not bool or (
        error is not None and not isinstance(error, str)
    ):
        raise AutomationError("Flush Mode returned an invalid decision or error.")
    state = FlushState(
        cast(FlushControl, control),
        automatic,
        _flush_counts(payload),
        _flush_timestamp(payload.get("checked_at")),
        _flush_timestamp(payload.get("attempted_at")),
        error,
    )
    if type(payload.get("active")) is not bool or payload["active"] != state.active:
        raise AutomationError("Flush Mode returned an inconsistent effective decision.")
    return state


def _flush_counts(payload: dict[str, object]) -> QueueCounts | None:
    first, second = payload.get("queue_tracks"), payload.get("queue_2_tracks")
    if first is None and second is None:
        return None
    if type(first) is not int or type(second) is not int or first < 0 or second < 0:
        raise AutomationError("Flush Mode returned invalid queue counts.")
    return QueueCounts(first, second)


def _flush_timestamp(raw: object) -> str | None:
    if raw is None:
        return None
    try:
        stamp = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError as exc:
        raise AutomationError("Flush Mode returned an invalid timestamp.") from exc
    if stamp is None or stamp.tzinfo is None:
        raise AutomationError("Flush Mode timestamps require a timezone.")
    return stamp.astimezone(UTC).isoformat()


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
