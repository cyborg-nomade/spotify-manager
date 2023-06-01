"""Test Loaders."""

# UFI
from spotify_manager.loaders_savers import load_control_file
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.albums import SimplifiedAlbum


def test_load_control_file() -> None:
    """Test Load control file."""
    result = load_control_file()
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(r_item, ControlFileItem) for r_item in result)


def test_load_total_albums_file() -> None:
    """Test Load control file."""
    result = load_total_albums_file()
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(r_item, SimplifiedAlbum) for r_item in result)
