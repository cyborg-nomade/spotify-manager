"""Compatibility checks for state composition and its legacy import facade."""

from pathlib import Path

import pytest

from spotify_manager.bootstrap.state import configured_state_store
from spotify_manager.core.state import StateDocumentError
from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.runtime import reset_state_service
from spotify_manager.infrastructure.huggingface.state_store import HubStateStore


def _empty_state() -> dict[str, object]:
    return {}


def test_local_runtime_service_uses_one_configured_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse the configured state singleton until its cache is explicitly reset.

    Args:
        tmp_path: Isolated working directory.
        monkeypatch: Scoped environment patch manager.
    """
    path = tmp_path / "shared.json"
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "local")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_LOCAL_PATH", str(path))
    state = get_state_service()
    namespace = state.namespace("queue", _empty_state)
    namespace.load()
    namespace.save({"count": 3})
    assert path.exists()
    assert get_state_service() is state
    reset_state_service()
    assert get_state_service() is not state


def test_invalid_runtime_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the existing invalid-state-backend error.

    Args:
        monkeypatch: Scoped environment patch manager.
    """
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "database")
    with pytest.raises(StateConfigurationError, match="must be 'hub' or 'local'"):
        get_state_service()


def test_hub_runtime_uses_configured_dataset() -> None:
    """Construct the configured state adapter without private factory patches."""
    store = configured_state_store(
        {
            "SPOTIFY_MANAGER_STATE_BACKEND": "hub",
            "SPOTIFY_MANAGER_STATE_REPO": "owner/shared-state",
            "SPOTIFY_MANAGER_STATE_FILENAME": "shared.json",
            "SPOTIFY_MANAGER_STATE_TOKEN": "test-token",
        }
    )
    assert isinstance(store, HubStateStore)
    assert (store.repo_id, store.filename, store.token) == (
        "owner/shared-state",
        "shared.json",
        "test-token",
    )


def test_local_runtime_rejects_invalid_existing_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve validation of an existing malformed state file.

    Args:
        tmp_path: Isolated working directory.
        monkeypatch: Scoped environment patch manager.
    """
    path = tmp_path / "shared.json"
    path.write_text("{}")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "local")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_LOCAL_PATH", str(path))
    with pytest.raises(StateDocumentError):
        get_state_service().snapshot()
