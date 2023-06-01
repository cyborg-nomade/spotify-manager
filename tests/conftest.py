"""Test configuration."""
# pytest
import pytest

from pytest_mock import MockerFixture


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
