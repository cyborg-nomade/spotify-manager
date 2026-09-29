"""Present Queue 3 outcomes using the existing operator messages."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Queue3Presenter:
    """Write Queue 3 messages through the caller's existing output callback.

    Args:
        echo: Existing CLI or job output sink.
        progress: Optional standalone import progress sink.
    """

    echo: Callable[[str], None]
    progress: Callable[[int, int, str], None] | None = None

    def imported(
        self, year: int, additions: int, considered: int, dry_run: bool
    ) -> None:
        """Explain annual import after its accepted effects and checkpoint.

        Args:
            year: Previous-year source playlist year.
            additions: New artists selected for import.
            considered: Unique source artists considered.
            dry_run: Whether this was a preview.
        """
        self.echo(
            f"{'Would import' if dry_run else 'Imported'} {additions} artists "
            f"from Great Discoveries {year}; "
            f"{considered - additions} were already present."
        )

    def loading(self, year: int) -> None:
        """Report initial progress before reading owned playlists.

        Args:
            year: Previous-year source year.
        """
        if self.progress is not None:
            self.progress(0, 1, f"Loading Great Discoveries {year}")

    def already_imported(self, year: int) -> None:
        """Explain why a stored checkpoint suppresses this import.

        Args:
            year: Previous-year source year.
        """
        self.echo(f"Great Discoveries {year} was already imported into Queue 3.")

    def checked(self, year: int, already_completed: bool) -> None:
        """Report final progress with the original completion label.

        Args:
            year: Previous-year source year.
            already_completed: Whether a stored checkpoint suppressed import.
        """
        if self.progress is None:
            return
        message = (
            f"Great Discoveries {year} already imported"
            if already_completed
            else f"Checked Great Discoveries {year}"
        )
        self.progress(1, 1, message)

    def added(self, name: str, dry_run: bool) -> None:
        """Report an accepted or projected target addition.

        Args:
            name: Target marker title.
            dry_run: Whether this is a preview.
        """
        self.echo(f"{'Would add' if dry_run else 'Added'}: {name}")

    def removed(self, name: str, dry_run: bool) -> None:
        """Report an accepted or projected previous-marker removal.

        Args:
            name: Original source title.
            dry_run: Whether this is a preview.
        """
        self.echo(f"{'Would remove' if dry_run else 'Removed'} previous track: {name}")

    def completed(self, artist: str, dry_run: bool) -> None:
        """Report completion after any final marker cleanup.

        Args:
            artist: Logical artist name.
            dry_run: Whether this is a preview.
        """
        self.echo(
            f"{'Would complete' if dry_run else 'Completed'} "
            f"{artist}; removed the final Queue 3 marker."
        )

    def skipped(self, artist: str, reason: object) -> None:
        """Report an unmapped source using the original reason representation.

        Args:
            artist: Logical artist name.
            reason: Original durable plan reason.
        """
        self.echo(f"Skipped {artist}: {reason}.")

    def started(self, index: int, total: int, artist: str, track: str) -> None:
        """Report entry progress before observing or reusing its plan.

        Args:
            index: One-based snapshot entry position.
            total: Complete snapshot size.
            artist: Logical artist name.
            track: Original source title.
        """
        if self.progress is not None:
            self.progress(index - 1, total, f"{artist} - {track}")

    def finished(self, index: int, total: int, artist: str) -> None:
        """Report progress after the entry's audit and acknowledgment.

        Args:
            index: One-based snapshot entry position.
            total: Complete snapshot size.
            artist: Logical artist name.
        """
        if self.progress is not None:
            self.progress(index, total, f"Completed {artist}")

    def stale(self, artist: str) -> None:
        """Report discarded stale composer plans before their checkpoint.

        Args:
            artist: Logical artist name.
        """
        self.echo(f"Discarded a stale composer-playlist plan for {artist}.")
