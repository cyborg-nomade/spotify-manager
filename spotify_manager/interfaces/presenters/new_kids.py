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

    def marker_added(self, name: str, dry_run: bool) -> None:
        """Show a secured review marker.

        Args:
            name: Replacement track name.
            dry_run: Whether to use preview wording.
        """
        self.echo(f"{'Would add' if dry_run else 'Added'}: {name}")

    def marker_removed(self, name: str, dry_run: bool) -> None:
        """Show removal of an existing review marker.

        Args:
            name: Original track name.
            dry_run: Whether to use preview wording.
        """
        self.echo(f"{'Would remove' if dry_run else 'Removed'}: {name}")

    def artist_added(self, name: str, label: str, dry_run: bool) -> None:
        """Show an artist marker added to an existing destination.

        Args:
            name: Logical artist display name.
            label: Destination display label.
            dry_run: Whether to use preview wording.
        """
        self.echo(f"{'Would add' if dry_run else 'Added'} {name} to {label}.")

    def future_artist_added(self, name: str, label: str, track: str) -> None:
        """Preview an artist marker for a destination awaiting creation.

        Args:
            name: Logical artist display name.
            label: Future destination label.
            track: Selected promotion marker name.
        """
        self.echo(f"Would add {name} to {label}: {track}")

    def artist_unfollowed(self, name: str, dry_run: bool) -> None:
        """Show unfollowing after any required mirror removal succeeds.

        Args:
            name: Logical artist display name.
            dry_run: Whether to use preview wording.
        """
        self.echo(f"{'Would unfollow' if dry_run else 'Unfollowed'} {name}.")
