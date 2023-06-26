"""Test data processors for total albums list."""

# Standard Library
from unittest.mock import Mock

# UFI
from spotify_manager.loaders_savers import load_control_file
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.processors.control_file_processors import get_starting_index
from spotify_manager.processors.total_albums_processor import create_playlist
from spotify_manager.processors.total_albums_processor import get_months_items
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.settings import Settings


settings = Settings()


def test_update_total_album_list(mock_save_total_albums_file: Mock) -> None:
    """Test get, update, save and return all saved albums."""
    result = update_total_album_list(just_update=True)
    print(result)
    mock_save_total_albums_file.assert_called_once()
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(item, SimplifiedAlbum) for item in result)


def test_get_months_items() -> None:
    """Test get this months albums from all albums, starting from initial index."""
    control_file = load_control_file()
    all_albums = load_total_albums_file()
    initial_index = get_starting_index(control_file, all_albums)
    result = get_months_items(all_albums, initial_index)
    print(result)
    assert isinstance(result, list)
    assert len(result) == settings.albums_to_add
    assert result[0].spotify_id != control_file[-1].album.spotify_id


def test_create_playlist(mock_create_playlist_file: Mock) -> None:
    """Test create a playlist and return id."""
    result = create_playlist()
    mock_create_playlist_file.assert_called_once()
    print(result)
