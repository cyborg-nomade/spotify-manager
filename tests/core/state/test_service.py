"""Preserve shared namespace revisions, validation and detached values."""

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from spotify_manager.core.state import StateConflictError
from spotify_manager.core.state import StateDocumentError
from spotify_manager.core.state import StateService
from spotify_manager.core.state.definitions import ObjectDefinition
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.models import with_namespace
from spotify_manager.infrastructure.persistence import JsonStateStore


@dataclass
class ConflictingStore:
    """Inject one external namespace write before the original guarded write.

    Args:
        backing_store: Original JSON persistence authority.
        should_conflict: Whether the original first-write fault is pending.
    """

    backing_store: JsonStateStore
    should_conflict: bool = True

    def read(self) -> StateSnapshot:
        """Return the original backing snapshot.

        Returns:
            Current document and revision.
        """
        return self.backing_store.read()

    def write(
        self, document: dict[str, Any], *, expected_revision: str, message: str
    ) -> StateSnapshot:
        """Inject the original one-shot conflict before accepting later writes.

        Args:
            document: Replacement shared document.
            expected_revision: Caller-observed revision.
            message: Original audit description.

        Returns:
            Accepted backing snapshot.

        Raises:
            StateConflictError: The original external write wins the race.
        """
        if self.should_conflict:
            self._conflict()
        return self.backing_store.write(
            document, expected_revision=expected_revision, message=message
        )

    def _conflict(self) -> None:
        self.should_conflict = False
        latest = self.backing_store.read()
        external = with_namespace(latest.document, "external", {"completed": True})
        self.backing_store.write(
            external, expected_revision=latest.revision, message="external update"
        )
        raise StateConflictError("simulated parent conflict")


class CountDefinition(ObjectDefinition):
    """Keep the original count-key validation behavior."""

    def validate(self, raw: object) -> dict[str, Any]:
        """Retain an object only when it contains the original count key.

        Args:
            raw: Original namespace payload.

        Returns:
            Original count payload or an empty object.
        """
        value = super().validate(raw)
        return value if "count" in value else {}


class RejectedDefinition(ObjectDefinition):
    """Reject the original scripted domain state."""

    def validate(self, raw: object) -> dict[str, Any]:
        """Raise the original domain validation failure.

        Args:
            raw: Original namespace payload.

        Raises:
            RuntimeError: The original scripted domain state is invalid.
        """
        raise RuntimeError("domain state is invalid")


def service(tmp_path: Path) -> StateService:
    """Build an isolated local state service.

    Args:
        tmp_path: Original test storage directory.

    Returns:
        Fresh service backed by the original JSON file.
    """
    return StateService(JsonStateStore(tmp_path / "state.json"))


def test_namespaces_share_one_document(tmp_path: Path) -> None:
    """Namespaces share one document.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    first = state.namespace("first", ObjectDefinition({"count": 0}))
    second = state.namespace("second", ObjectDefinition({"enabled": False}))

    first_value = first.load()
    first_value["count"] = 2
    first.save(first_value)
    second_value = second.load()
    second_value["enabled"] = True
    second.save(second_value)

    document = json.loads((tmp_path / "state.json").read_text())
    assert document["namespaces"]["first"]["value"] == {"count": 2}
    assert document["namespaces"]["second"]["value"] == {"enabled": True}


def test_concurrent_different_namespaces_merge(tmp_path: Path) -> None:
    """Concurrent different namespaces merge.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    first = state.namespace("first", ObjectDefinition({"count": 0}))
    second = state.namespace("second", ObjectDefinition({"count": 0}))
    first_value = first.load()
    second_value = second.load()

    first_value["count"] = 1
    first.save(first_value)
    second_value["count"] = 2
    second.save(second_value)

    snapshot = state.snapshot()
    assert snapshot.document["namespaces"]["first"]["value"]["count"] == 1
    assert snapshot.document["namespaces"]["second"]["value"]["count"] == 2


def test_namespace_write_rebases_after_store_conflict(tmp_path: Path) -> None:
    """Namespace write rebases after store conflict.

    Args:
        tmp_path: Isolated local storage directory.
    """
    backing_store = JsonStateStore(tmp_path / "state.json")

    state = StateService(ConflictingStore(backing_store))
    queue = state.namespace("queue", ObjectDefinition({"count": 0}))
    queue.load()

    saved = queue.save({"count": 1})

    assert isinstance(saved, StateSnapshot)
    assert saved.document["namespaces"]["queue"]["value"] == {"count": 1}
    assert saved.document["namespaces"]["external"]["value"] == {"completed": True}


def test_concurrent_same_namespace_is_rejected(tmp_path: Path) -> None:
    """Concurrent same namespace is rejected.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    first = state.namespace("queue", ObjectDefinition({"count": 0}))
    second = state.namespace("queue", ObjectDefinition({"count": 0}))
    first_value = first.load()
    second_value = second.load()

    first_value["count"] = 1
    first.save(first_value)
    second_value["count"] = 2

    with pytest.raises(StateConflictError, match="changed in another process"):
        second.save(second_value)


def test_load_returns_detached_values(tmp_path: Path) -> None:
    """Load returns detached values.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    namespace = state.namespace("queue", ObjectDefinition({"items": []}))
    loaded = namespace.load()
    detached = copy.deepcopy(loaded)
    loaded["items"].append("one")

    assert detached == {"items": []}
    assert namespace.load() == {"items": []}


def test_save_requires_load(tmp_path: Path) -> None:
    """Save requires load.

    Args:
        tmp_path: Isolated local storage directory.
    """
    namespace = service(tmp_path).namespace("queue", ObjectDefinition())

    with pytest.raises(StateDocumentError, match="must be loaded"):
        namespace.save({"count": 1})


def test_replace_uses_revision_guard(tmp_path: Path) -> None:
    """Replace uses revision guard.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    original = state.snapshot()
    first = state.namespace("queue", ObjectDefinition())
    first.load()
    first.save({"count": 1})

    with pytest.raises(StateConflictError):
        state.replace(
            original.document,
            expected_revision=original.revision,
        )


def test_replace_namespace_validates_and_uses_revision_guard(tmp_path: Path) -> None:
    """Replace namespace validates and uses revision guard.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    original = state.snapshot()

    saved = state.replace_namespace(
        "queue",
        {"count": 2},
        expected_revision=original.revision,
        validator=CountDefinition(),
    )

    assert saved.document["namespaces"]["queue"]["value"] == {"count": 2}
    with pytest.raises(StateConflictError, match="changed elsewhere"):
        state.replace_namespace(
            "queue",
            {"count": 3},
            expected_revision=original.revision,
        )


def test_replace_namespace_wraps_domain_validation_errors(tmp_path: Path) -> None:
    """Replace namespace wraps domain validation errors.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    original = state.snapshot()

    with pytest.raises(StateDocumentError, match="domain state is invalid"):
        state.replace_namespace(
            "queue",
            {"count": 2},
            expected_revision=original.revision,
            validator=RejectedDefinition(),
        )


def test_export_does_not_change_state(tmp_path: Path) -> None:
    """Export does not change state.

    Args:
        tmp_path: Isolated local storage directory.
    """
    state = service(tmp_path)
    namespace = state.namespace("queue", ObjectDefinition())
    namespace.load()
    namespace.save({"count": 1})
    before = state.snapshot()

    exported = state.export(tmp_path / "snapshot.json")

    assert exported == before
    assert json.loads((tmp_path / "snapshot.json").read_text()) == {
        "revision": before.revision,
        "document": before.document,
    }
