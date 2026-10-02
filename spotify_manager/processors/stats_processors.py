"""Compatibility entry points for original legacy listening statistics."""

from spotify_manager.application import legacy_library_control as workflow
from spotify_manager.loaders_savers import save_stats_file as save_stats_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem


def calculate_stats(
    control_file: list[ControlFileItem], total_album_list: list[SimplifiedAlbum]
) -> StatsFileItem:
    """Calculate original counts and ratios without zero-denominator guards.

    Args:
        control_file: Original control decisions.
        total_album_list: Original saved-album authority.

    Returns:
        Original statistics model.

    Raises:
        ZeroDivisionError: An original denominator is zero.
    """
    return workflow.calculate(control_file, total_album_list, print)


def update_stats(
    control_file: list[ControlFileItem], total_album_list: list[SimplifiedAlbum]
) -> bool:
    """Display and publish original statistics in the original order.

    Args:
        control_file: Original control decisions.
        total_album_list: Original saved-album authority.

    Returns:
        True after accepted publication.
    """
    return workflow.update_statistics(
        control_file, total_album_list, calculate_stats, save_stats_file, print
    )
