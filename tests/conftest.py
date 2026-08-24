"""Test configuration."""

from collections.abc import Iterator

# pytest
import pytest
from pytest_mock import MockerFixture

from spotify_manager.core.library_data.runtime import reset_library_data_service
from spotify_manager.core.state.runtime import reset_state_service
from spotify_manager.processors import library_lookups


@pytest.fixture(autouse=True)
def isolated_central_state(monkeypatch, tmp_path) -> Iterator[None]:
    """Keep production-default central state local and isolated in tests."""
    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "local")
    monkeypatch.setenv(
        "SPOTIFY_MANAGER_STATE_LOCAL_PATH",
        str(tmp_path / "central-state.json"),
    )
    reset_state_service()
    yield
    reset_state_service()


@pytest.fixture(autouse=True)
def isolated_library_data(monkeypatch, tmp_path) -> Iterator[None]:
    """Keep durable library-data tests local and isolated."""
    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "local")
    monkeypatch.setenv(
        "SPOTIFY_MANAGER_DATA_LOCAL_ROOT",
        str(tmp_path / "library-data"),
    )
    reset_library_data_service()
    yield
    reset_library_data_service()


@pytest.fixture(autouse=True)
def album_cache_store(monkeypatch) -> dict:
    """Redirect the album-tracklist cache to memory so tests never touch disk.

    Returns the in-memory store; tests that exercise caching can seed/inspect it.
    """
    store: dict[str, list[dict]] = {}

    def _load() -> dict:
        return {k: list(v) for k, v in store.items()}

    def _save(cache: dict) -> None:
        store.clear()
        store.update({k: list(v) for k, v in cache.items()})

    monkeypatch.setattr(library_lookups, "load_album_tracks_cache", _load)
    monkeypatch.setattr(library_lookups, "save_album_tracks_cache", _save)
    return store


@pytest.fixture
def mock_save_stats_file(mocker: MockerFixture) -> MockerFixture:
    """Mock the saving of total albums file."""
    return mocker.patch(
        ("spotify_manager.processors.stats_processors.save_stats_file"),
        return_value=None,
    )
