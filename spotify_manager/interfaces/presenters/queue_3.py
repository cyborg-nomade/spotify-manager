"""Present Queue 3 outcomes using the existing operator messages."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Queue3Presenter:
    """Write Queue 3 messages through the caller's existing output callback.

    Args:
        echo: Existing CLI or job output sink.
    """

    echo: Callable[[str], None]

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
