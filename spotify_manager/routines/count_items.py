"""Stable legacy export-count entry point."""

from spotify_manager.application.legacy_library_monthly import count_artists
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)


def count_artists_in_library() -> int:
    """Read the original export and count every artist entry.

    Returns:
        Original raw artist-list length.
    """
    return count_artists(load_your_library_file)
