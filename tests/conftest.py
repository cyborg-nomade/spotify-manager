"""Test configuration."""

# pytest
import pytest
from pytest_mock import MockerFixture

from spotify_manager.processors import library_lookups


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
def mock_save_control_file(mocker: MockerFixture) -> MockerFixture:
    """Mock the saving of control file."""
    return mocker.patch(
        ("spotify_manager.processors.control_file_processors.save_control_file"),
        return_value=None,
    )


@pytest.fixture
def mock_save_total_albums_file(mocker: MockerFixture) -> MockerFixture:
    """Mock the saving of total albums file."""
    return mocker.patch(
        ("spotify_manager.processors.total_albums_processor.save_total_albums_file"),
        return_value=None,
    )


@pytest.fixture
def mock_save_stats_file(mocker: MockerFixture) -> MockerFixture:
    """Mock the saving of total albums file."""
    return mocker.patch(
        ("spotify_manager.processors.stats_processors.save_stats_file"),
        return_value=None,
    )


@pytest.fixture
def mock_create_playlist_file(mocker: MockerFixture) -> MockerFixture:
    """Mock the saving of total albums file."""
    return mocker.patch(
        ("spotipy.Spotify.user_playlist_create"),
        return_value={"id": "valid_id"},
    )


@pytest.fixture
def mock_get_album_results_from_library(mocker: MockerFixture) -> MockerFixture:
    """Mock the return of albums results from library."""
    return mocker.patch(
        (
            "spotify_manager.processors.control_file_processors."
            "get_album_results_from_library"
        ),
        return_value=[],
    )
