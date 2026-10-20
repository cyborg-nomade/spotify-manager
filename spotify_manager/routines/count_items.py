"""Stable legacy export-count entry point."""

from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)


def count_artists_in_library() -> int:
    """Read the original export and count every artist entry.

    Returns:
        Original raw artist-list length.
    """
    from spotify_manager.interfaces.operations.legacy_library import (
        count_artists_in_library as operation,
    )

    return operation()
