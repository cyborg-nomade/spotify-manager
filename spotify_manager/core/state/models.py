"""Models and validation for the single shared state document."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any


STATE_SCHEMA_VERSION = 1


class StateError(RuntimeError):
    """Base error for central state operations."""


class StateDocumentError(StateError):
    """Raised when the shared state document is malformed."""


class StateConflictError(StateError):
    """Raised when a concurrent writer changed the same state."""


class StateConfigurationError(StateError):
    """Raised when the configured state store cannot be used."""


@dataclass(frozen=True)
class StateSnapshot:
    """One validated state document at a store revision."""

    document: dict[str, Any]
    revision: str


def utc_now() -> str:
    """Return a stable UTC timestamp for state metadata."""
    return datetime.now(UTC).isoformat()


def new_document() -> dict[str, Any]:
    """Return an empty state document using the current schema."""
    timestamp = utc_now()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "created_at": timestamp,
        "updated_at": timestamp,
        "namespaces": {},
    }


def validate_document(raw: object) -> dict[str, Any]:
    """Validate and detach a shared state document."""
    if not isinstance(raw, dict):
        raise StateDocumentError("State must be a JSON object.")
    if raw.get("schema_version") != STATE_SCHEMA_VERSION:
        raise StateDocumentError(
            f"State schema_version must be {STATE_SCHEMA_VERSION}."
        )
    namespaces = raw.get("namespaces")
    if not isinstance(namespaces, dict):
        raise StateDocumentError("State namespaces must be a JSON object.")
    for name, envelope in namespaces.items():
        if not isinstance(name, str) or not name.strip():
            raise StateDocumentError("State namespace names must be non-empty strings.")
        if not isinstance(envelope, dict):
            raise StateDocumentError(f"State namespace {name!r} must be an object.")
        if not isinstance(envelope.get("updated_at"), str):
            raise StateDocumentError(
                f"State namespace {name!r} must have an updated_at string."
            )
        if not isinstance(envelope.get("value"), dict):
            raise StateDocumentError(
                f"State namespace {name!r} value must be a JSON object."
            )
    for field in ("created_at", "updated_at"):
        if not isinstance(raw.get(field), str):
            raise StateDocumentError(f"State {field} must be a string.")
    try:
        json.dumps(raw, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StateDocumentError(f"State is not valid JSON data: {exc}") from exc
    return copy.deepcopy(raw)


def canonical_json(value: object) -> str:
    """Serialize JSON deterministically for comparisons and persistence."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StateDocumentError(f"State is not valid JSON data: {exc}") from exc


def namespace_value(document: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return a detached namespace value from a validated document."""
    envelope = document["namespaces"].get(name)
    if envelope is None:
        return None
    return copy.deepcopy(envelope["value"])


def with_namespace(
    document: dict[str, Any],
    name: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    """Return a document copy containing one updated namespace."""
    if not name.strip():
        raise StateDocumentError("State namespace name cannot be empty.")
    if not isinstance(value, dict):
        raise StateDocumentError("State namespace value must be a JSON object.")
    updated = validate_document(document)
    timestamp = utc_now()
    updated["updated_at"] = timestamp
    updated["namespaces"][name] = {
        "updated_at": timestamp,
        "value": copy.deepcopy(value),
    }
    return validate_document(updated)
