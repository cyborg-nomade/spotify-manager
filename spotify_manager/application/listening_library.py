"""Named current-library comparison use case with explicit immutable resources."""

from functools import lru_cache

from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_library import compare_library
from spotify_manager.domain.listening_library import review_library_candidates
from spotify_manager.domain.listening_library_values import LibraryCandidateOptions
from spotify_manager.domain.listening_library_values import LibraryCandidatePage
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


def get_library_candidates(
    index: ListeningReads,
    catalog: LibraryCatalog,
    query: ListeningQuery,
    options: LibraryCandidateOptions,
) -> LibraryCandidatePage:
    """Look up one recorded identity and review the pinned collection's candidates.

    Args:
        index: Pinned published listening generation.
        catalog: Pinned published Spotify collections.
        query: Current listening selection and cutoff.
        options: Original identity and bounded candidate search.

    Returns:
        The original name and a page of published candidate identities.
    """
    history = index.entity_lifetime(query, options.selection)
    return review_library_candidates(history, catalog, options)
