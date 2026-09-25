"""Explicit persistence construction and compatibility lifetime contracts."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import pytest

from spotify_manager.application.ports.mirrors import LibraryDataStore
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.ports.state import StateStore
from spotify_manager.bootstrap import library_data
from spotify_manager.bootstrap import state
from spotify_manager.core.library_data.models import ALL_ARTIFACTS
from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataDocumentError
from spotify_manager.core.library_data.store import (
    LibraryDataStore as LegacyLibraryStore,
)
from spotify_manager.core.state import RoutineState as LegacyRoutineState
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.models import new_document
from spotify_manager.core.state.store import StateStore as LegacyStateStore
from spotify_manager.infrastructure.huggingface.library_data_store import (
    HubLibraryDataStore,
)
from spotify_manager.infrastructure.huggingface.state_store import HubStateStore
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)
from spotify_manager.infrastructure.persistence.json_state_store import JsonStateStore


@dataclass
class MemoryStateStore:
    """Store detached documents with a monotonically increasing revision.

    Args:
        document: Initial valid shared-state document.
        revision: Current version counter.
    """

    document: dict[str, object] = field(default_factory=new_document)
    revision: int = 0

    def read(self) -> StateSnapshot:
        """Return a detached snapshot at the current revision.

        Returns:
            The current document and version counter.
        """
        return StateSnapshot(deepcopy(self.document), str(self.revision))

    def write(
        self, document: dict[str, object], *, expected_revision: str, message: str
    ) -> StateSnapshot:
        """Apply one guarded write or report the original conflict type.

        Args:
            document: Replacement shared-state document.
            expected_revision: Revision observed before the write.
            message: Description used when reporting a conflict.

        Returns:
            The updated snapshot.

        Raises:
            StateConflictError: The caller's revision is stale.
        """
        if expected_revision != str(self.revision):
            raise StateConflictError(message)
        self.document = deepcopy(document)
        self.revision += 1
        return self.read()


def _empty_state() -> dict[str, object]:
    return {}


def _paths(root: Path) -> dict[ArtifactName, Path]:
    return {name: root / ARTIFACT_FILENAMES[name] for name in ALL_ARTIFACTS}


def test_ports_keep_legacy_type_identity() -> None:
    """Preserve the public protocol identities through compatibility imports."""
    assert LegacyStateStore is StateStore
    assert LegacyLibraryStore is LibraryDataStore
    assert LegacyRoutineState is RoutineState


def test_explicit_store_reuses_namespace_conflicts_and_unrelated_merges() -> None:
    """Reuse namespace conflict checks while merging unrelated peer writes."""
    store = MemoryStateStore()
    first = state.create_state_service(store).namespace("queue", _empty_state)
    peer = state.create_state_service(store).namespace("queue", _empty_state)
    other = state.create_state_service(store).namespace("other", _empty_state)
    assert first.load() == peer.load() == other.load() == {}
    other.save({"n": 1})
    first.save({"n": 2})
    assert other.load() == {"n": 1}
    with pytest.raises(StateConflictError, match="another process"):
        peer.save({"n": 3})
    assert first.load() == {"n": 2}


def test_explicit_service_does_not_touch_environment_or_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct a working service despite invalid process configuration.

    Args:
        monkeypatch: Scoped environment patch manager.
    """
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "invalid")
    service = state.create_state_service(MemoryStateStore())
    original = service.snapshot()
    service.replace(original.document, expected_revision=original.revision)
    with pytest.raises(StateConflictError):
        service.replace(original.document, expected_revision=original.revision)


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, None),
        ({"HF_TOKEN": "generic"}, "generic"),
        ({"HF_TOKEN": "generic", "SPOTIFY_MANAGER_STATE_TOKEN": "state"}, "state"),
        ({"HF_TOKEN": "generic", "SPOTIFY_MANAGER_STATE_TOKEN": ""}, "generic"),
    ],
)
def test_state_token_precedence(
    environment: dict[str, str], expected: str | None
) -> None:
    """Keep state token aliases and fallback precedence unchanged.

    Args:
        environment: Explicit configuration snapshot.
        expected: Expected token selected by the precedence rule.
    """
    store = state.configured_state_store(environment)
    assert isinstance(store, HubStateStore)
    assert store.token == expected
    assert store.repo_id == state.DEFAULT_STATE_REPO
    assert store.filename == "state.json"


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, None),
        ({"HF_TOKEN": "generic"}, "generic"),
        ({"HF_TOKEN": "generic", "SPOTIFY_MANAGER_STATE_TOKEN": "state"}, "state"),
        (
            {
                "HF_TOKEN": "generic",
                "SPOTIFY_MANAGER_STATE_TOKEN": "state",
                "SPOTIFY_MANAGER_DATA_TOKEN": "data",
            },
            "data",
        ),
        (
            {"SPOTIFY_MANAGER_STATE_TOKEN": "state", "SPOTIFY_MANAGER_DATA_TOKEN": ""},
            "state",
        ),
    ],
)
def test_library_token_precedence(
    environment: dict[str, str], expected: str | None
) -> None:
    """Keep data, state, and generic token precedence unchanged.

    Args:
        environment: Explicit configuration snapshot.
        expected: Expected token selected by the precedence rule.
    """
    store = library_data.configured_library_store(environment)
    assert isinstance(store, HubLibraryDataStore)
    assert store.token == expected
    assert store.repo_id == library_data.DEFAULT_LIBRARY_DATA_REPO
    assert store.manifest_filename == "manifest.json"


@pytest.mark.parametrize("backend", ["local", "LOCAL", "Local"])
def test_local_configuration_keeps_case_insensitivity(
    backend: str, tmp_path: Path
) -> None:
    """Resolve explicit local paths with case-insensitive backend names.

    Args:
        backend: Backend spelling under test.
        tmp_path: Isolated working directory.
    """
    state_store = state.configured_state_store(
        {
            "SPOTIFY_MANAGER_STATE_BACKEND": backend,
            "SPOTIFY_MANAGER_STATE_LOCAL_PATH": str(tmp_path / "state.json"),
        }
    )
    mirror_store = library_data.configured_library_store(
        {
            "SPOTIFY_MANAGER_DATA_BACKEND": backend,
            "SPOTIFY_MANAGER_DATA_LOCAL_ROOT": str(tmp_path / "data"),
            "SPOTIFY_MANAGER_DATA_MANIFEST": "custom.json",
        }
    )
    assert isinstance(state_store, JsonStateStore)
    assert state_store.path == tmp_path / "state.json"
    assert isinstance(mirror_store, JsonLibraryDataStore)
    assert mirror_store.read().document["artifacts"] == {}


def test_library_composition_preserves_publish_hydrate_and_integrity(
    tmp_path: Path,
) -> None:
    """Reuse publication, hydration, and payload validation through injected storage.

    Args:
        tmp_path: Isolated working directory.
    """
    store = JsonLibraryDataStore(tmp_path / "store")
    source_paths, target_paths = (
        _paths(tmp_path / "source"),
        _paths(tmp_path / "target"),
    )
    source_paths["albums"].parent.mkdir()
    source_paths["albums"].write_bytes(b"[]\n")
    source = library_data.create_library_data_service(store, source_paths)
    source.publish("albums", source="test")
    target = library_data.create_library_data_service(store, target_paths)
    assert target.hydrate("albums").local_current
    assert target_paths["albums"].read_bytes() == b"[]\n"
    source_paths["albums"].write_bytes(b"not JSON")
    with pytest.raises(LibraryDataDocumentError):
        source.publish("albums", source="test")


def test_explicit_mirror_paths_remain_required(tmp_path: Path) -> None:
    """Reject incomplete artifact bindings during explicit construction.

    Args:
        tmp_path: Isolated working directory.
    """
    with pytest.raises(ValueError, match="Missing library-data paths"):
        library_data.create_library_data_service(JsonLibraryDataStore(tmp_path), {})


def test_legacy_runtime_functions_are_bootstrap_functions() -> None:
    """Keep old and new imports attached to the same process cache."""
    from spotify_manager.core.library_data import runtime as mirrors
    from spotify_manager.core.state import runtime as shared_state

    assert mirrors.get_library_data_service is library_data.get_library_data_service
    assert mirrors.reset_library_data_service is library_data.reset_library_data_service
    assert shared_state.get_state_service is state.get_state_service
    assert shared_state.reset_state_service is state.reset_state_service


def test_managed_path_publication_uses_configured_service(tmp_path: Path) -> None:
    """Publish only the exact managed path through the shared library service.

    Args:
        tmp_path: Isolated directory for an unmanaged file with the same basename.
    """
    path = library_data.DEFAULT_ARTIFACT_PATHS["albums"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"[]\n")
    assert library_data.publish_managed_path(path, source="composition-test")
    snapshot = library_data.get_library_data_service().snapshot()
    metadata = snapshot.document["artifacts"]["albums"]
    assert metadata["source"] == "composition-test"
    assert not library_data.publish_managed_path(tmp_path / path.name, source="ignored")
