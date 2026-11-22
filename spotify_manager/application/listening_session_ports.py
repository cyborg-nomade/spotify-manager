"""The immutable history operations needed by session exploration."""

from collections.abc import Hashable
from typing import Protocol

from spotify_manager.domain.listening_session_values import SessionWindow
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningRecords
from spotify_manager.domain.listening_values import RecordOptions


class ListeningSessionReads(Hashable, Protocol):
    """Read one immutable generation, using its identity for bounded result caches."""

    def artist_plays(self, query: ListeningQuery) -> tuple[ArtistPlay, ...]:
        """Read compact chronological observations with stable source-order ties.

        Args:
            query: Exact shared date and artist/rhythm selection.

        Returns:
            Selected rows without deduplication or external enrichment.
        """
        ...

    def session_records(
        self, query: ListeningQuery, window: SessionWindow, options: RecordOptions
    ) -> ListeningRecords:
        """Read a bounded chronological page within one selected-record group.

        Args:
            query: Shared filters used for grouping.
            window: Group's inclusive first and last recorded timestamps.
            options: One-based chronological page and maximum rows.

        Returns:
            Original source records and the complete matching row count.
        """
        ...
