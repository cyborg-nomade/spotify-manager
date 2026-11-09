"""Validate the dedicated Flush Mode namespace at its JSON boundary."""

from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from typing import cast

from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts


def _timestamp(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise StateDocumentError("Flush Mode timestamps must be UTC strings.")
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise StateDocumentError("Invalid Flush Mode timestamp.") from exc
    if stamp.tzinfo is None:
        raise StateDocumentError("Flush Mode timestamps require a timezone.")
    return stamp.astimezone(UTC).isoformat()


def _counts(raw: object) -> QueueCounts | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise StateDocumentError("Flush Mode counts must describe both queues.")
    first, second = raw.get("queue"), raw.get("queue_2")
    if type(first) is not int or type(second) is not int:
        raise StateDocumentError("Flush Mode counts must be whole numbers.")
    if first < 0 or second < 0:
        raise StateDocumentError("Flush Mode counts cannot be negative.")
    return QueueCounts(first, second)


def decode_flush_state(raw: object) -> FlushState:
    """Validate control and observations before any policy decision.

    Args:
        raw: Untrusted namespace value.

    Returns:
        Typed, detached state with normalized UTC timestamps.

    Raises:
        StateDocumentError: Persisted control or observations are malformed.
    """
    if not isinstance(raw, dict):
        raise StateDocumentError("Flush Mode state must be an object.")
    if type(raw.get("version")) is not int or raw.get("version") != 1:
        raise StateDocumentError("Flush Mode state requires version 1.")
    control = raw.get("control")
    if not isinstance(control, str) or control not in {"automatic", "on", "off"}:
        raise StateDocumentError("Flush Mode control must be automatic, on or off.")
    active, error = raw.get("automatic_active"), raw.get("error")
    if type(active) is not bool or (error is not None and not isinstance(error, str)):
        raise StateDocumentError("Invalid Flush Mode decision or error.")
    return FlushState(
        cast(FlushControl, control),
        active,
        _counts(raw.get("counts")),
        _timestamp(raw.get("checked_at")),
        _timestamp(raw.get("attempted_at")),
        error,
    )


def encode_flush_state(state: FlushState) -> dict[str, object]:
    """Encode typed state without including other routine namespaces.

    Args:
        state: Complete typed control and observations.

    Returns:
        Versioned JSON namespace.
    """
    return {"version": 1, **asdict(state)}


class FlushModeDefinition:
    """Own defaults and validation for the shared Flush Mode namespace."""

    def default(self) -> dict[str, object]:
        """Return fresh, unobserved Automatic state.

        Returns:
            Default versioned namespace.
        """
        return encode_flush_state(FlushState())

    def validate(self, raw: object) -> dict[str, object]:
        """Validate the persisted namespace through its typed schema.

        Args:
            raw: Untrusted persisted or manually edited data.

        Returns:
            Validated and normalized JSON namespace.

        Raises:
            StateDocumentError: The candidate is invalid.
        """
        return encode_flush_state(decode_flush_state(raw))
