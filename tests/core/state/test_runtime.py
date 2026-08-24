import pytest

from spotify_manager.core.state import StateDocumentError
from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.runtime import reset_state_service
from spotify_manager.core.state import runtime


@pytest.fixture(autouse=True)
def reset_runtime_service():
    reset_state_service()
    yield
    reset_state_service()


def test_local_runtime_service_uses_one_configured_file(tmp_path, monkeypatch):
    path = tmp_path / "shared.json"
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "local")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_LOCAL_PATH", str(path))
    state = get_state_service()
    namespace = state.namespace("queue", lambda: {})
    namespace.load()
    namespace.save({"count": 3})

    assert path.exists()
    assert get_state_service() is state


def test_invalid_runtime_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "database")

    with pytest.raises(StateConfigurationError, match="must be 'hub' or 'local'"):
        get_state_service()


def test_hub_runtime_uses_configured_dataset(monkeypatch):
    configured = {}

    class FakeHubStore:
        def __init__(self, repo_id, *, filename, token):
            configured.update(repo_id=repo_id, filename=filename, token=token)

    monkeypatch.setattr(runtime, "HubStateStore", FakeHubStore)
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "hub")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_REPO", "owner/shared-state")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_FILENAME", "shared.json")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_TOKEN", "secret")

    get_state_service()

    assert configured == {
        "repo_id": "owner/shared-state",
        "filename": "shared.json",
        "token": "secret",
    }


def test_local_runtime_rejects_invalid_existing_document(tmp_path, monkeypatch):
    path = tmp_path / "shared.json"
    path.write_text("{}")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "local")
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_LOCAL_PATH", str(path))

    with pytest.raises(StateDocumentError):
        get_state_service().snapshot()
