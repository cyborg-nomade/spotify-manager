"""Compose stored history download resources outside application execution."""

from spotify_manager.bootstrap.library_data import get_library_data_service
from spotify_manager.infrastructure.scrobble_downloads import ScrobbleHistoryFiles


def scrobble_downloads() -> ScrobbleHistoryFiles:
    """Use the configured durable artifact service for a read-only download.

    Returns:
        A resource creating independent, verified temporary snapshots.
    """
    return ScrobbleHistoryFiles(get_library_data_service())
