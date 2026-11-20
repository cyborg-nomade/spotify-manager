"""Named current-library comparison use case with explicit immutable resources."""

from functools import lru_cache

from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_library import compare_library
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryComparison
from spotify_manager.domain.listening_library_values import LibraryOptions
from spotify_manager.domain.listening_values import ListeningQuery


@lru_cache(maxsize=16)
def get_listening_library(
    index: ListeningReads,
    catalog: LibraryCatalog,
    query: ListeningQuery,
    options: LibraryOptions,
) -> LibraryComparison:
    """Compare selected listening with a separately pinned collection publication.

    Args:
        index: Complete immutable listening history generation.
        catalog: Complete mirror evidence generation, including unknown coverage.
        query: Validated date, artist and rhythm filters for listening only.
        options: Collection, evidence filter, search and pagination.

    Returns:
        Current-publication evidence for each selected historical entity.
    """
    return compare_library(index.lifetimes(query, options.kind), catalog, options)
