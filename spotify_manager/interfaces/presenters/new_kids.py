"""Original discovery-review messages at application-selected boundaries."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation


@dataclass(frozen=True)
class NewKidsPresenter:
    """Render unchanged review messages through the caller-owned sink.

    Args:
        echo: Existing CLI or job message sink.
    """

    echo: Callable[[str], None]

    def release_progress(self, artist: str, completed: int, year: int) -> None:
        """Show the historical completion observation before its audit record.

        Args:
            artist: Logical artist display name.
            completed: Number of completed catalog entries.
            year: Existing invocation year.
        """
        self.echo(
            f"{artist}: {completed} release(s) completed from {year} Last.fm scrobbles."
        )

    def reconciled(
        self,
        release: RankedRelease,
        evaluation: AlbumEvaluation,
        action: str,
        dry_run: bool,
    ) -> None:
        """Show reconciliation after the original routine audit.

        Args:
            release: Completed release.
            evaluation: Accepted live decision and track counts.
            action: Original persisted or preview outcome.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would reconcile' if dry_run else 'Reconciled'} {release.name}: "
            f"{evaluation.liked_tracks}/{evaluation.total_tracks} liked, {action}."
        )
