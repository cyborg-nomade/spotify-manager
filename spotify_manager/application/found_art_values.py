"""Public recommendation errors independent of external clients and storage."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.domain.recommendation_matching import FoundArtResult
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


class FoundArtError(RuntimeError):
    """Base error for the Found Art recommendation routine."""


class FoundArtConfigError(FoundArtError):
    """Raised when required Last.fm or Spotify settings are missing."""


class FoundArtStateError(FoundArtError):
    """Raised when a cache, delta, or audit file cannot be used safely."""


@dataclass(frozen=True)
class FoundArtSummary:
    """Completed recommendation observations and accepted destination effects.

    Args:
        generated_at: Effective UTC run timestamp.
        week_start: Effective listening week's Friday.
        playlist_id: Original destination identifier.
        requested_count: Resolved requested additions.
        seed_count: Actual selected seed count.
        history_tracks: Distinct valid canonical history identities.
        history_scrobbles: Canonical play count before identity filtering.
        live_scrobbles_added: Original refresh observation count.
        candidate_count: Ranked neighborhood candidate count.
        playlist_length_before: Original observed destination size.
        playlist_length_after: Projected size after accepted appends.
        dry_run: Original preview mode.
        seeds: Original selected recommendation seeds.
        results: Original ordered candidate outcomes.
    """

    generated_at: datetime
    week_start: date
    playlist_id: str
    requested_count: int
    seed_count: int
    history_tracks: int
    history_scrobbles: int
    live_scrobbles_added: int
    candidate_count: int
    playlist_length_before: int
    playlist_length_after: int
    dry_run: bool
    seeds: tuple[FoundArtSeed, ...]
    results: tuple[FoundArtResult, ...]

    @property
    def added(self) -> int:
        """Count actual Spotify additions recorded by the original actions.

        Returns:
            Number of results marked added.
        """
        return sum(result.action == "added" for result in self.results)

    @property
    def selected(self) -> int:
        """Count actual or proposed additions recorded by the original actions.

        Returns:
            Number of results marked added or would add.
        """
        return sum(result.action in {"added", "would add"} for result in self.results)
