"""Original Slow Listening progress messages at explicit effect boundaries."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.slow_listening_values import FlushResult
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


@dataclass(frozen=True)
class SlowListeningPresenter:
    """Render established CLI/job text without owning workflow decisions.

    Args:
        echo: Caller-owned message sink.
    """

    echo: Callable[[str], None]

    def skipped(self, source: PlaylistTrack, result: FlushResult) -> None:
        """Show why a source was skipped.

        Args:
            source: Original playlist marker.
            result: Skip reason and result fields.
        """
        self.echo(
            f"Skipped {source.primary_artist_name} - {source.name}: {result.reason}."
        )

    def added(self, target: ReleaseTrack, release_name: str, dry_run: bool) -> None:
        """Show a newly appended or previewed replacement.

        Args:
            target: Replacement track.
            release_name: Selected release title or unknown marker.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would add' if dry_run else 'Added'} next track: "
            f"{target.name} ({release_name})"
        )

    def removed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show removal of the previous marker.

        Args:
            source: Original playlist marker.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would remove' if dry_run else 'Removed'} previous track: {source.name}"
        )

    def completed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show completion of an artist's final studio track.

        Args:
            source: Original final marker.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would complete' if dry_run else 'Completed'} "
            f"{source.primary_artist_name}: {source.name} was the final track."
        )

    def resumed(self, source: PlaylistTrack) -> None:
        """Show that a saved source was already removed.

        Args:
            source: Original saved marker.
        """
        self.echo(f"Source already removed; completing saved plan for {source.name}.")
