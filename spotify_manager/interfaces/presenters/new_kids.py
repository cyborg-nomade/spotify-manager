"""Original discovery-review messages at application-selected boundaries."""

from collections.abc import Callable
from dataclasses import dataclass


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
