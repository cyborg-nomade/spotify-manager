"""Explicit recovery CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from spotipy import Spotify

from spotify_manager.interfaces.cli.display import ProgressDisplay
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.interfaces.operations import (
    recover_removed_albums as recover_removed_albums,
)
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class RecoveryCLI:
    """Run one CLI feature with explicit interaction and presentation resources.

    Args:
        progress_display: Caller-owned progress display.
        create_console: Caller-owned create console.
        review_client: Caller-owned review client.
    """

    progress_display: ProgressDisplay
    create_console: type[Console]
    review_client: Callable[..., Spotify]

    def _run_recover_removed_albums(self, dry_run: bool, limit: int | None) -> None:
        """Audit removed albums, follow credited artists, and restore future releases.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            limit: Limit supplied by the caller.
        """
        self._recover_removed_albums_console = self.create_console()
        try:
            with self.progress_display.create_progress(
                self.progress_display.spinner_column(),
                self.progress_display.text_column(
                    "[progress.description]{task.description}"
                ),
                self.progress_display.bar_column(),
                self.progress_display.complete_column(),
                self.progress_display.time_column(),
                console=self._recover_removed_albums_console,
                transient=True,
            ) as self._recover_removed_albums_progress:
                description = progress_description("Auditing removed albums", dry_run)
                self._recover_removed_albums_task_id = (
                    self._recover_removed_albums_progress.add_task(
                        description, total=None
                    )
                )
                recover_removed_albums.recover_removed_albums(
                    self.review_client(),
                    echo=self._recover_removed_albums_echo,
                    progress_callback=self._recover_removed_albums_update_progress,
                    dry_run=dry_run,
                    limit=limit,
                )
        except recover_removed_albums.SpotifyRateLimitError as exc:
            self._report_recover_removed_albums_rate_limit(exc)
        except recover_removed_albums.SpotifyTransientServerError as exc:
            self._report_recover_removed_albums_server_failure(exc)

    def _recover_removed_albums_echo(self, line: str = "") -> None:
        """Recover removed albums echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith("Followed credited artist"):
            style = "cyan"
        elif line.startswith("Would follow") or line.startswith("Would restore"):
            style = "yellow"
        elif line.startswith("Multiple credited artists"):
            style = "magenta"
        elif line.startswith("Restored future release"):
            style = "bold green"
        elif line.startswith("Future release already saved"):
            style = "green"
        elif line.startswith("Album unavailable"):
            style = "yellow"
        elif line.startswith("Recovery complete") or line.startswith(
            "Dry run complete"
        ):
            style = "bold"
        self._recover_removed_albums_console.print(line, style=style, markup=False)

    def _recover_removed_albums_update_progress(
        self, position: int, total: int
    ) -> None:
        self._recover_removed_albums_progress.update(
            self._recover_removed_albums_task_id, completed=position, total=total
        )

    def _report_recover_removed_albums_rate_limit(
        self, exc: recover_removed_albums.SpotifyRateLimitError
    ) -> Never:
        self._recover_removed_albums_console.print(
            (
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
            ),
            style="bold yellow",
        )
        self._recover_removed_albums_console.print(
            "Recovery progress was saved up to the last completed album.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_recover_removed_albums_server_failure(
        self, exc: recover_removed_albums.SpotifyTransientServerError
    ) -> Never:
        self._recover_removed_albums_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._recover_removed_albums_console.print(
            "Recovery progress was saved up to the last completed album.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
