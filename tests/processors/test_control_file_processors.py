"""Data processors for control file items."""

# Standard Library
from unittest.mock import Mock

# UFI
from spotify_manager.loaders_savers import load_control_file
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.processors.control_file_processors import check_album_results
from spotify_manager.processors.control_file_processors import (
    get_album_results_from_library,
)
from spotify_manager.processors.control_file_processors import (
    get_index_for_first_unevaluated_album,
)
from spotify_manager.processors.control_file_processors import get_starting_index
from spotify_manager.processors.control_file_processors import get_unevaluated_albums


def test_get_index_for_first_unevaluated_album() -> None:
    """Test get index for first unevaluated album in control file."""
    control_file = load_control_file()
    result = get_index_for_first_unevaluated_album(control_file)
    print(result)
    print(control_file[result])
    assert isinstance(result, int)
    assert result >= 0


def test_get_unevaluated_albums() -> None:
    """Test get list of unevaluated albums from control file."""
    control_file = load_control_file()
    result = get_unevaluated_albums(control_file)
    print(len(result))
    print(result[0].result)
    assert len(result) >= 200
    assert all(item.result == "" for item in result)


def test_get_album_results_from_library() -> None:
    """Test check against spotify library if albums have been removed or kept."""
    control_file = load_control_file()
    unevaluated_albums = get_unevaluated_albums(control_file)
    result = get_album_results_from_library(unevaluated_albums)
    print(result)
    assert len(result) == len(unevaluated_albums)
    assert all(item.result != "" for item in result)


def test_check_album_results(
    mock_save_control_file: Mock, mock_get_album_results_from_library: Mock
) -> None:
    """Test check if non evaluated albums in control file are saved in library."""
    control_file = load_control_file()
    result = check_album_results(control_file)
    mock_get_album_results_from_library.assert_called_once()
    mock_save_control_file.assert_called_once()
    print(result)


def test_get_starting_index() -> None:
    """Test get starting index in total album list from last listened in control."""
    control_file = load_control_file()
    total_albums_file = load_total_albums_file()
    result = get_starting_index(control_file, total_albums_file)
    print(result)
