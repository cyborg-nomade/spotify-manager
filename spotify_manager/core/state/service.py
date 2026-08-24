"""Single interface used by routines, CLI, API, and web state controls."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.models import canonical_json
from spotify_manager.core.state.models import namespace_value
from spotify_manager.core.state.models import validate_document
from spotify_manager.core.state.models import with_namespace
from spotify_manager.core.state.store import StateStore


StateFactory = Callable[[], dict[str, Any]]
StateValidator = Callable[[object], dict[str, Any]]
MAX_NAMESPACE_WRITE_ATTEMPTS = 5


def object_validator(raw: object) -> dict[str, Any]:
    """Validate a namespace whose domain validation happens in its routine."""
    if not isinstance(raw, dict):
        raise StateDocumentError("State namespace must be a JSON object.")
    return copy.deepcopy(raw)


class StateService:
    """Coordinate all reads, writes, edits, and exports of shared state."""

    def __init__(self, store: StateStore) -> None:
        """Use the provided persistence adapter for every state operation."""
        self._store = store

    def snapshot(self) -> StateSnapshot:
        """Return a detached, validated snapshot."""
        snapshot = self._store.read()
        return StateSnapshot(
            document=validate_document(snapshot.document),
            revision=snapshot.revision,
        )

    def namespace(
        self,
        name: str,
        default_factory: StateFactory,
        validator: StateValidator = object_validator,
    ) -> StateNamespace:
        """Return the only supported interface for one routine namespace."""
        return StateNamespace(self, name, default_factory, validator)

    def replace(
        self,
        document: dict[str, object],
        *,
        expected_revision: str,
        message: str = "Manually edit Spotify Manager state",
    ) -> StateSnapshot:
        """Validate and replace the complete document with a revision guard."""
        validated = validate_document(document)
        return self._store.write(
            validated,
            expected_revision=expected_revision,
            message=message,
        )

    def replace_namespace(
        self,
        name: str,
        value: dict[str, Any],
        *,
        expected_revision: str,
        validator: StateValidator = object_validator,
        message: str | None = None,
    ) -> StateSnapshot:
        """Validate and replace one namespace against the viewed revision."""
        latest = self.snapshot()
        if latest.revision != expected_revision:
            raise StateConflictError(
                "Shared state changed elsewhere. Reload it before saving."
            )
        try:
            validated = validator(value)
        except StateError:
            raise
        except Exception as exc:
            raise StateDocumentError(str(exc)) from exc
        document = with_namespace(latest.document, name, validated)
        return self.replace(
            document,
            expected_revision=expected_revision,
            message=message or f"Manually edit {name} state",
        )

    def export(self, destination: Path) -> StateSnapshot:
        """Write a readable snapshot without changing shared state."""
        snapshot = self.snapshot()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            canonical_json(
                {
                    "revision": snapshot.revision,
                    "document": snapshot.document,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return snapshot


class StateNamespace:
    """Optimistically synchronized view of one namespace."""

    def __init__(
        self,
        service: StateService,
        name: str,
        default_factory: StateFactory,
        validator: StateValidator,
    ) -> None:
        """Track one namespace and its last-loaded conflict baseline."""
        self._service = service
        self.name = name
        self._default_factory = default_factory
        self._validator = validator
        self._baseline: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        """Load and validate the namespace, using its default when absent."""
        snapshot = self._service.snapshot()
        raw = namespace_value(snapshot.document, self.name)
        value = self._validator(raw if raw is not None else self._default_factory())
        self._baseline = copy.deepcopy(value)
        return copy.deepcopy(value)

    def save(
        self,
        value: dict[str, Any],
        *,
        message: str | None = None,
    ) -> StateSnapshot:
        """Merge one namespace unless another writer changed that namespace."""
        validated = self._validator(value)
        baseline = self._baseline
        if baseline is None:
            raise StateDocumentError(
                f"State namespace {self.name!r} must be loaded before it is saved."
            )
        for attempt in range(MAX_NAMESPACE_WRITE_ATTEMPTS):
            latest = self._service.snapshot()
            latest_value = namespace_value(latest.document, self.name)
            comparable_latest = self._validator(
                latest_value if latest_value is not None else self._default_factory()
            )
            if canonical_json(comparable_latest) != canonical_json(baseline):
                raise StateConflictError(
                    f"State namespace {self.name!r} changed in another process. "
                    "Reload it before saving."
                )
            document = with_namespace(latest.document, self.name, validated)
            try:
                saved = self._service.replace(
                    document,
                    expected_revision=latest.revision,
                    message=message or f"Update {self.name} state",
                )
            except StateConflictError as exc:
                if attempt + 1 == MAX_NAMESPACE_WRITE_ATTEMPTS:
                    raise StateConflictError(
                        "Shared state kept changing while the namespace was saved. "
                        "Try again."
                    ) from exc
                continue
            self._baseline = copy.deepcopy(validated)
            return saved
        raise AssertionError("namespace write retry loop did not return")

    def replace(self, value: dict[str, Any], *, message: str) -> StateSnapshot:
        """Reload then replace this namespace with normal conflict handling."""
        self.load()
        return self.save(value, message=message)
