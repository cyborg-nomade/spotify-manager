"""Test data processors for stats."""

# Standard Library
from unittest.mock import Mock

# UFI
from spotify_manager.loaders_savers import load_control_file
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.processors.stats_processors import calculate_stats
from spotify_manager.processors.stats_processors import update_stats


def test_calculate_stats() -> None:
    """Test calculate stats."""
    control_file = load_control_file()
    total_albums_file = load_total_albums_file()
    result = calculate_stats(control_file, total_albums_file)
    print(result)
    assert isinstance(result, StatsFileItem)


def test_update_stats(mock_save_stats_file: Mock) -> None:
    """Test calculate stats."""
    control_file = load_control_file()
    total_albums_file = load_total_albums_file()
    result = update_stats(control_file, total_albums_file)
    mock_save_stats_file.assert_called_once()
    assert result
