"""Original release-check errors and complete or paused workflow outcomes."""

from dataclasses import dataclass
from datetime import date

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.domain.release_check_values import ReleaseCheckResult


class ReleaseCheckError(RuntimeError):
    """Base error for a release-check run."""


class ReleaseCheckConfigError(ReleaseCheckError):
    """Raised when either destination playlist is not configured."""


class ReleaseCheckStateError(ReleaseCheckError):
    """Raised when restart state or the audit log cannot be maintained."""


class ReleaseCheckSpotifyError(ReleaseCheckError):
    """Raised when Spotify returns incomplete release data."""


@dataclass(frozen=True)
class ReleaseCheckSummary:
    """Outcome of one complete or paused original release check.

    Args:
        run_id: Original durable run identity.
        checked_from: Inclusive original window start.
        checked_through: Inclusive original window end.
        artists_total: Original ranked candidate count.
        artists_processed: Original completed artist count.
        dry_run: Original preview mode.
        resumed: Whether the original active run was resumed.
        paused: Original quit outcome.
        wine_cellar_duplicates_removed: Original planned or accepted cleanup count.
        history_refresh: Original refresh outcome, absent on resumed runs.
        results: Original ordered release outcomes.
    """

    run_id: str
    checked_from: date
    checked_through: date
    artists_total: int
    artists_processed: int
    dry_run: bool
    resumed: bool
    paused: bool
    wine_cellar_duplicates_removed: int
    history_refresh: ScrobbleHistorySummary | None
    results: tuple[ReleaseCheckResult, ...]

    @property
    def wine_cellar_added(self) -> int:
        """Count original planned or completed Wine Cellar additions.

        Returns:
            Number of original added or would-add Wine Cellar outcomes.
        """
        return sum(
            result.wine_cellar_action in {"added", "would add"}
            for result in self.results
        )

    @property
    def new_vintage_added(self) -> int:
        """Count original planned or completed New Vintage additions.

        Returns:
            Number of original added or would-add New Vintage outcomes.
        """
        return sum(
            result.new_vintage_action in {"added", "would add"}
            for result in self.results
        )
