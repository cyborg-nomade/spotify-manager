"""Test configuration."""

import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

# pytest
import pytest
from pytest_mock import MockerFixture

from tests.support.isolation import isolate_environment
from tests.support.isolation import protect_operator_files
from tests.support.isolation import redirect_artifacts


def pytest_sessionstart(session: pytest.Session) -> None:
    """Isolate credentials and block sockets before importing test modules."""
    patch = pytest.MonkeyPatch()
    temporary = tempfile.TemporaryDirectory(prefix="spotify-tests-")
    isolate_environment(patch, Path(temporary.name))
    active = True

    def audit(event: str, args: tuple[object, ...]) -> None:
        if active:
            protect_operator_files(event, args)

    def cleanup() -> None:
        nonlocal active
        active = False
        patch.undo()
        temporary.cleanup()

    sys.addaudithook(audit)
    session.config.add_cleanup(cleanup)


@pytest.fixture(autouse=True)
def isolated_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Redirect logs, mirrors, backups, checkpoints, and relative files."""
    redirect_artifacts(monkeypatch, tmp_path_factory.mktemp("artifacts"))


@pytest.fixture(autouse=True)
def isolated_central_state(monkeypatch, tmp_path) -> Iterator[None]:
    """Keep production-default central state local and isolated in tests."""
    from spotify_manager.core.state.runtime import reset_state_service

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
    from spotify_manager.core.library_data.runtime import reset_library_data_service

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
    from spotify_manager.processors import library_lookups

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
