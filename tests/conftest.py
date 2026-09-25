"""Test configuration."""

import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from tests.support.isolation import isolate_environment
from tests.support.isolation import protect_operator_files
from tests.support.isolation import redirect_artifacts


type AlbumCache = dict[str, list[dict[str, object]]]


@dataclass
class SessionIsolation:
    """Own the session patches and lifetime of its permanent Python audit hook.

    Args:
        patch: Environment and socket patches to undo at session end.
        temporary: Temporary state and cache directory.
        active: Whether the audit hook should still enforce isolation.
    """

    patch: pytest.MonkeyPatch
    temporary: tempfile.TemporaryDirectory[str]
    active: bool = True

    def audit(self, event: str, args: tuple[object, ...]) -> None:
        """Enforce isolation while this session is active.

        Args:
            event: Python audit event name.
            args: Arguments supplied by the audit event.

        Raises:
            AssertionError: The active session attempted forbidden I/O.
        """
        if self.active:
            protect_operator_files(event, args)

    def cleanup(self) -> None:
        """Disable the hook and restore the environment after the session.

        Raises:
            OSError: Temporary files cannot be removed.
        """
        self.active = False
        self.patch.undo()
        self.temporary.cleanup()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Isolate credentials and block sockets before importing test modules.

    Args:
        session: Pytest session whose cleanup restores process state.
    """
    patch = pytest.MonkeyPatch()
    temporary = tempfile.TemporaryDirectory(prefix="spotify-tests-")
    isolation = SessionIsolation(patch, temporary)
    isolate_environment(patch, Path(temporary.name))
    sys.addaudithook(isolation.audit)
    session.config.add_cleanup(isolation.cleanup)


@pytest.fixture(autouse=True)
def isolated_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Redirect logs, mirrors, backups, checkpoints, and relative files.

    Args:
        monkeypatch: Per-test patch manager.
        tmp_path_factory: Factory for an independent artifact directory.
    """
    redirect_artifacts(monkeypatch, tmp_path_factory.mktemp("artifacts"))


@pytest.fixture(autouse=True)
def isolated_central_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Keep production-default central state local and isolated in tests.

    Args:
        monkeypatch: Per-test environment patch manager.
        tmp_path: Directory for temporary central state.

    Yields:
        Control to the test, resetting the service before and after it.
    """
    from spotify_manager.core.state.runtime import reset_state_service

    monkeypatch.setenv("SPOTIFY_MANAGER_STATE_BACKEND", "local")
    monkeypatch.setenv(
        "SPOTIFY_MANAGER_STATE_LOCAL_PATH", str(tmp_path / "central-state.json")
    )
    reset_state_service()
    yield
    reset_state_service()


@pytest.fixture(autouse=True)
def isolated_library_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Keep durable library-data tests local and isolated.

    Args:
        monkeypatch: Per-test environment patch manager.
        tmp_path: Directory for temporary library data.

    Yields:
        Control to the test, resetting the service before and after it.
    """
    from spotify_manager.core.library_data.runtime import reset_library_data_service

    monkeypatch.setenv("SPOTIFY_MANAGER_DATA_BACKEND", "local")
    monkeypatch.setenv(
        "SPOTIFY_MANAGER_DATA_LOCAL_ROOT", str(tmp_path / "library-data")
    )
    reset_library_data_service()
    yield
    reset_library_data_service()


def _load_album_cache(store: AlbumCache) -> AlbumCache:
    result = {}
    for key, tracks in store.items():
        result[key] = list(tracks)
    return result


def _save_album_cache(store: AlbumCache, cache: AlbumCache) -> None:
    store.clear()
    store.update(_load_album_cache(cache))


@pytest.fixture(autouse=True)
def album_cache_store(monkeypatch: pytest.MonkeyPatch) -> AlbumCache:
    """Redirect the album-tracklist cache to memory instead of disk.

    Args:
        monkeypatch: Per-test patch manager.

    Returns:
        In-memory store that tests can seed and inspect.
    """
    from spotify_manager.processors import library_lookups

    store: AlbumCache = {}
    monkeypatch.setattr(
        library_lookups, "load_album_tracks_cache", partial(_load_album_cache, store)
    )
    monkeypatch.setattr(
        library_lookups, "save_album_tracks_cache", partial(_save_album_cache, store)
    )
    return store


@pytest.fixture
def mock_save_stats_file(mocker: MockerFixture) -> Mock:
    """Replace the stats-file writer with an observable mock.

    Args:
        mocker: Pytest mock manager.

    Returns:
        Mock of the stats-file writer, returning None.
    """
    return mocker.patch(
        "spotify_manager.processors.stats_processors.save_stats_file", return_value=None
    )
