"""Read a reproducible playlist proposal from pinned publications."""

from functools import lru_cache
from typing import Protocol

from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_playlist import PlaylistPreview
from spotify_manager.domain.listening_playlist import PlaylistReview
from spotify_manager.domain.listening_playlist import RecordedTrack
from spotify_manager.domain.listening_playlist import build_playlist_preview
from spotify_manager.domain.listening_values import ListeningQuery


class PlaylistReads(Protocol):
    """Read selected track groups in original recorded order."""

    def ordered_tracks(self, query: ListeningQuery) -> tuple[RecordedTrack, ...]:
        """Return track groups by their first selected timestamp and source row."""
        ...


@lru_cache(maxsize=4)
def get_playlist_preview(
    index: PlaylistReads,
    catalog: LibraryCatalog,
    query: ListeningQuery,
    reviews: tuple[PlaylistReview, ...],
) -> PlaylistPreview:
    """Assemble a private proposal with the same filters as the Listening Explorer.

    Args:
        index: Pinned recorded history resource.
        catalog: Pinned published tracks and their coverage.
        query: Shared dates, timezone, artist, and rhythm selection.
        reviews: Current browser choices submitted for source verification.

    Returns:
        Candidate tracks, repeat counts, and unresolved evidence.
    """
    return build_playlist_preview(index.ordered_tracks(query), catalog, reviews)
