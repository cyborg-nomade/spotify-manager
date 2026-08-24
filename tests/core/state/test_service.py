import copy
import json

import pytest

from spotify_manager.core.state import StateConflictError
from spotify_manager.core.state import StateDocumentError
from spotify_manager.core.state import StateService
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.models import with_namespace
from spotify_manager.infrastructure.persistence import JsonStateStore


def service(tmp_path):
    return StateService(JsonStateStore(tmp_path / "state.json"))


def test_namespaces_share_one_document(tmp_path):
    state = service(tmp_path)
    first = state.namespace("first", lambda: {"count": 0})
    second = state.namespace("second", lambda: {"enabled": False})

    first_value = first.load()
    first_value["count"] = 2
    first.save(first_value)
    second_value = second.load()
    second_value["enabled"] = True
    second.save(second_value)

    document = json.loads((tmp_path / "state.json").read_text())
    assert document["namespaces"]["first"]["value"] == {"count": 2}
    assert document["namespaces"]["second"]["value"] == {"enabled": True}


def test_concurrent_different_namespaces_merge(tmp_path):
    state = service(tmp_path)
    first = state.namespace("first", lambda: {"count": 0})
    second = state.namespace("second", lambda: {"count": 0})
    first_value = first.load()
    second_value = second.load()

    first_value["count"] = 1
    first.save(first_value)
    second_value["count"] = 2
    second.save(second_value)

    snapshot = state.snapshot()
    assert snapshot.document["namespaces"]["first"]["value"]["count"] == 1
    assert snapshot.document["namespaces"]["second"]["value"]["count"] == 2


def test_namespace_write_rebases_after_store_conflict(tmp_path):
    backing_store = JsonStateStore(tmp_path / "state.json")

    class ConflictingStore:
        def __init__(self):
            self.should_conflict = True

        def read(self):
            return backing_store.read()

        def write(self, document, *, expected_revision, message):
            if self.should_conflict:
                self.should_conflict = False
                latest = backing_store.read()
                external = with_namespace(
                    latest.document,
                    "external",
                    {"completed": True},
                )
                backing_store.write(
                    external,
                    expected_revision=latest.revision,
                    message="external update",
                )
                raise StateConflictError("simulated parent conflict")
            return backing_store.write(
                document,
                expected_revision=expected_revision,
                message=message,
            )

    state = StateService(ConflictingStore())  # type: ignore[arg-type]
    queue = state.namespace("queue", lambda: {"count": 0})
    queue.load()

    saved = queue.save({"count": 1})

    assert isinstance(saved, StateSnapshot)
    assert saved.document["namespaces"]["queue"]["value"] == {"count": 1}
    assert saved.document["namespaces"]["external"]["value"] == {
        "completed": True
    }


def test_concurrent_same_namespace_is_rejected(tmp_path):
    state = service(tmp_path)
    first = state.namespace("queue", lambda: {"count": 0})
    second = state.namespace("queue", lambda: {"count": 0})
    first_value = first.load()
    second_value = second.load()

    first_value["count"] = 1
    first.save(first_value)
    second_value["count"] = 2

    with pytest.raises(StateConflictError, match="changed in another process"):
        second.save(second_value)


def test_load_returns_detached_values(tmp_path):
    state = service(tmp_path)
    namespace = state.namespace("queue", lambda: {"items": []})
    loaded = namespace.load()
    detached = copy.deepcopy(loaded)
    loaded["items"].append("one")

    assert detached == {"items": []}
    assert namespace.load() == {"items": []}


def test_save_requires_load(tmp_path):
    namespace = service(tmp_path).namespace("queue", lambda: {})

    with pytest.raises(StateDocumentError, match="must be loaded"):
        namespace.save({"count": 1})


def test_replace_uses_revision_guard(tmp_path):
    state = service(tmp_path)
    original = state.snapshot()
    first = state.namespace("queue", lambda: {})
    first.load()
    first.save({"count": 1})

    with pytest.raises(StateConflictError):
        state.replace(
            original.document,
            expected_revision=original.revision,
        )


def test_replace_namespace_validates_and_uses_revision_guard(tmp_path):
    state = service(tmp_path)
    original = state.snapshot()

    saved = state.replace_namespace(
        "queue",
        {"count": 2},
        expected_revision=original.revision,
        validator=lambda value: value if "count" in value else {},
    )

    assert saved.document["namespaces"]["queue"]["value"] == {"count": 2}
    with pytest.raises(StateConflictError, match="changed elsewhere"):
        state.replace_namespace(
            "queue",
            {"count": 3},
            expected_revision=original.revision,
        )


def test_replace_namespace_wraps_domain_validation_errors(tmp_path):
    state = service(tmp_path)
    original = state.snapshot()

    def reject(_value):
        raise RuntimeError("domain state is invalid")

    with pytest.raises(StateDocumentError, match="domain state is invalid"):
        state.replace_namespace(
            "queue",
            {"count": 2},
            expected_revision=original.revision,
            validator=reject,
        )


def test_export_does_not_change_state(tmp_path):
    state = service(tmp_path)
    namespace = state.namespace("queue", lambda: {})
    namespace.load()
    namespace.save({"count": 1})
    before = state.snapshot()

    exported = state.export(tmp_path / "snapshot.json")

    assert exported == before
    assert json.loads((tmp_path / "snapshot.json").read_text()) == {
        "revision": before.revision,
        "document": before.document,
    }
