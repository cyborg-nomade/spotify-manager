"""Compatibility checks for durable-library composition and fallback behavior."""

from pathlib import Path

import pytest

from spotify_manager.bootstrap.library_data import configured_library_store
from spotify_manager.core.library_data import LibraryDataConfigurationError
from spotify_manager.core.library_data.runtime import get_library_data_service
from spotify_manager.core.library_data.runtime import hydrate_runtime_library_data
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.core.library_data.runtime import reset_library_data_service
from spotify_manager.infrastructure.huggingface.library_data_store import (
    HubLibraryDataStore,
)


def test_runtime_uses_configured_local_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the configured library singleton and its reset behavior.

    Args:
        tmp_path: Isolated working directory.
        monkeypatch: Scoped environment patch manager.
    """
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "local")
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_LOCAL_ROOT", str(tmp_path / "data"))
    service = get_library_data_service()
    assert service is get_library_data_service()
    assert service.snapshot().document["artifacts"] == {}
    reset_library_data_service()
    assert get_library_data_service() is not service


def test_runtime_uses_configured_hub_dataset() -> None:
    """Construct the configured library adapter without private factory patches."""
    store = configured_library_store(
        {
            "SPOTIFY_MANAGER_DATA_BACKEND": "hub",
            "SPOTIFY_MANAGER_DATA_REPO": "owner/data",
            "SPOTIFY_MANAGER_DATA_MANIFEST": "library.json",
            "SPOTIFY_MANAGER_DATA_TOKEN": "test-token",
        }
    )
    assert isinstance(store, HubLibraryDataStore)
    assert (store.repo_id, store.manifest_filename, store.token) == (
        "owner/data",
        "library.json",
        "test-token",
    )


def test_runtime_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain rejection of unsupported library backends.

    Args:
        monkeypatch: Scoped environment patch manager.
    """
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "database")
    with pytest.raises(LibraryDataConfigurationError, match="hub.*local"):
        get_library_data_service()


def test_runtime_ignores_unmanaged_path(tmp_path: Path) -> None:
    """Avoid publishing files outside the canonical artifact mapping.

    Args:
        tmp_path: Isolated working directory.
    """
    assert publish_managed_path(tmp_path / "other.json", source="test") is False


def test_non_strict_hydration_keeps_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain fallback statuses and strict-mode error propagation.

    Args:
        monkeypatch: Scoped environment patch manager.
    """
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "database")
    statuses = hydrate_runtime_library_data()
    assert len(statuses) == 4
    assert all(status.local_current is False for status in statuses)
    with pytest.raises(LibraryDataConfigurationError):
        hydrate_runtime_library_data(strict=True)


def test_infrastructure_packages_expose_lazy_adapters() -> None:
    """Keep the existing lazy infrastructure imports and unknown-name errors."""
    import spotify_manager.infrastructure.huggingface as hub
    import spotify_manager.infrastructure.persistence as persistence

    assert hub.HubLibraryDataStore.__name__ == "HubLibraryDataStore"
    assert hub.HubStateStore.__name__ == "HubStateStore"
    assert persistence.JsonLibraryDataStore.__name__ == "JsonLibraryDataStore"
    assert persistence.JsonStateStore.__name__ == "JsonStateStore"
    with pytest.raises(AttributeError):
        hub.__getattr__("UnknownStore")
