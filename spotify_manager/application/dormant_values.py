"""Stable dormant-artist recovery errors and original completed summary."""

from dataclasses import dataclass

from spotify_manager.application.historical_values import BlastFromPastError
from spotify_manager.domain.dormant_artists import DormantArtistResult


class BlastFromPastArtistsError(BlastFromPastError):
    """Original dormant-artist recovery failure."""


@dataclass(frozen=True)
class DormantArtistSummary:
    """Completed original dormant-artist recovery update.

    Args:
        current_year: Effective original local year.
        history_years: Prior-year intersection window.
        candidate_count: Original full eligible history count.
        represented_count: Original represented candidate count before selection.
        playlist_length_before: Initial destination length.
        playlist_length_after: Initial length plus accepted real additions.
        requested_count: Original requested additions.
        results: Original ordered selected and skipped outcomes.
    """

    current_year: int
    history_years: tuple[int, ...]
    candidate_count: int
    represented_count: int
    playlist_length_before: int
    playlist_length_after: int
    requested_count: int
    results: tuple[DormantArtistResult, ...]

    @property
    def added(self) -> int:
        """Count original added outcomes, including preview proposals.

        Returns:
            Number of selected originally live-liked markers.
        """
        return sum(result.action == "added" for result in self.results)
