"""Legacy statistics use synthetic inputs, never the operator's exports."""

from unittest.mock import Mock

from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.processors.stats_processors import calculate_stats
from spotify_manager.processors.stats_processors import update_stats
from tests.processors.test_control_file_processors import album


def _inputs() -> tuple[list[ControlFileItem], list[SimplifiedAlbum]]:
    albums = [album(str(index), str(index)) for index in range(4)]
    control = [
        ControlFileItem(album=albums[0], result="keep"),
        ControlFileItem(album=albums[1], result="remove"),
    ]
    return control, albums


def test_calculate_stats() -> None:
    """Preserve exact counts, proportions, and the last listened album index."""
    result = calculate_stats(*_inputs())
    assert result.model_dump() == {
        "total_saved_albums": 4,
        "total_listened_albums": 2,
        "pct_listened_albums": 0.5,
        "total_removed_albums": 1,
        "pct_removed_albums": 0.5,
        "total_kept_albums": 1,
        "pct_kept_albums": 0.5,
        "last_listened_to_index": 1,
    }


def test_update_stats(mock_save_stats_file: Mock) -> None:
    """Persist the complete calculated statistics exactly once.

    Args:
        mock_save_stats_file: Recording replacement for the stats writer.
    """
    assert update_stats(*_inputs()) is True
    mock_save_stats_file.assert_called_once_with(calculate_stats(*_inputs()))
