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
