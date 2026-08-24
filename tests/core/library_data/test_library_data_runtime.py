import pytest

from spotify_manager.core.library_data import LibraryDataConfigurationError
from spotify_manager.core.library_data import runtime
from spotify_manager.core.library_data.runtime import get_library_data_service
from spotify_manager.core.library_data.runtime import hydrate_runtime_library_data
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.core.library_data.runtime import reset_library_data_service


@pytest.fixture(autouse=True)
def reset_runtime():
    reset_library_data_service()
    yield
    reset_library_data_service()


def test_runtime_uses_configured_local_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "local")
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_LOCAL_ROOT", str(tmp_path / "data"))

    assert get_library_data_service() is get_library_data_service()
    assert get_library_data_service().snapshot().document["artifacts"] == {}


def test_runtime_uses_configured_hub_dataset(monkeypatch):
    configured = {}

    class FakeStore:
        def __init__(self, repo_id, *, manifest_filename, token):
            configured.update(
                repo_id=repo_id,
                manifest_filename=manifest_filename,
                token=token,
            )

    monkeypatch.setattr(runtime, "HubLibraryDataStore", FakeStore)
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "hub")
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_REPO", "owner/data")
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_MANIFEST", "library.json")
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_TOKEN", "secret")

    get_library_data_service()

    assert configured == {
        "repo_id": "owner/data",
        "manifest_filename": "library.json",
        "token": "secret",
    }


def test_runtime_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "database")

    with pytest.raises(LibraryDataConfigurationError, match="hub.*local"):
        get_library_data_service()


def test_runtime_ignores_unmanaged_path(tmp_path):
    assert publish_managed_path(tmp_path / "other.json", source="test") is False


def test_non_strict_hydration_keeps_fallbacks(monkeypatch):
    class UnavailableService:
        def hydrate_all(self):
            raise LibraryDataConfigurationError("offline")

    with monkeypatch.context() as patch:
        patch.setattr(
            runtime,
            "get_library_data_service",
            lambda: UnavailableService(),
        )
        statuses = hydrate_runtime_library_data()

    assert len(statuses) == 4
    assert all(status.local_current is False for status in statuses)


def test_infrastructure_packages_expose_lazy_adapters():
    import spotify_manager.infrastructure.huggingface as hub
    import spotify_manager.infrastructure.persistence as persistence

    assert hub.HubLibraryDataStore.__name__ == "HubLibraryDataStore"
    assert hub.HubStateStore.__name__ == "HubStateStore"
    assert persistence.JsonLibraryDataStore.__name__ == "JsonLibraryDataStore"
    assert persistence.JsonStateStore.__name__ == "JsonStateStore"
    with pytest.raises(AttributeError):
        hub.__getattr__("UnknownStore")
