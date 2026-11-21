"""Construct Listening Explorer storage outside business execution."""

import os
from tempfile import TemporaryDirectory

from spotify_manager.bootstrap.library_data import get_library_data_service
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime


def listening_explorer_runtime() -> ListeningRuntime:
    """Create a process-isolated disposable cache below an optional configured root.

    Returns:
        Runtime owning its source reads, generations, worker, and temporary directory.
    """
    directory = TemporaryDirectory(
        prefix="spotify-listening-", dir=os.environ.get("LISTENING_CACHE_DIR")
    )
    return ListeningRuntime(get_library_data_service(), directory)


def listening_library_runtime() -> LibraryRuntime:
    """Construct independent current-collection reads outside HTTP execution.

    Returns:
        Owner of immutable publication generations and its background worker.
    """
    return LibraryRuntime(get_library_data_service())
