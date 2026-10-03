"""Explicit requeue CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.table import Table
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.operations import (
    requeue_for_a_dream as requeue_for_a_dream,
)
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class RequeueCLI:
    """Execute and present requeue through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        configuration: Original settings factory supplied by the facade.
        create_table: Factory for table instances.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    create_console: type[Console]
    configuration: type[Settings]
    create_table: type[Table]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _run_flush_requeue_for_a_dream(self, dry_run: bool) -> None:
        """Advance the first Requeue for a Dream artist by one release.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_requeue_for_a_dream_console = self.create_console()
        configuration = self.configuration()
        try:
            playlist_id = requeue_for_a_dream.parse_playlist_id(
                configuration.reqeueue_for_a_dream_playlist
            )
        except requeue_for_a_dream.RequeueForADreamConfigError as exc:
            self._report_flush_requeue_for_a_dream_configuration_failure(exc)
        try:
            with self._flush_requeue_for_a_dream_console.status(
                "Planning Requeue for a Dream" + (" (dry run)" if dry_run else "")
            ) as status:
                summary = requeue_for_a_dream.flush_requeue_for_a_dream(
                    self.review_client(),
                    playlist_id,
                    dry_run=dry_run,
                    echo=self._flush_requeue_for_a_dream_echo,
                    progress_callback=status.update,
                    retry_call=self._flush_requeue_for_a_dream_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_requeue_for_a_dream_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_requeue_for_a_dream_server_failure(exc)
        except requeue_for_a_dream.RequeueForADreamError as exc:
            self._report_flush_requeue_for_a_dream_requeue_for_a_dream_failure(exc)
        except SpotifyException as exc:
            self._report_flush_requeue_for_a_dream_spotify_spotify_failure(exc)
        self._show_flush_requeue_for_a_dream(dry_run, summary)

    def _flush_requeue_for_a_dream_echo(self, line: str = "") -> None:
        style = "bold green" if line.startswith(("Added", "Removed")) else "cyan"
        self._flush_requeue_for_a_dream_console.print(line, style=style, markup=False)

    def _flush_requeue_for_a_dream_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_requeue_for_a_dream_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _report_flush_requeue_for_a_dream_configuration_failure(
        self, exc: requeue_for_a_dream.RequeueForADreamConfigError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_requeue_for_a_dream_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_requeue_for_a_dream_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_requeue_for_a_dream_requeue_for_a_dream_failure(
        self, exc: requeue_for_a_dream.RequeueForADreamError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_requeue_for_a_dream_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _show_flush_requeue_for_a_dream(
        self, dry_run: bool, summary: requeue_for_a_dream.RequeueForADreamSummary
    ) -> None:
        """Show flush requeue for a dream.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            summary: Completed routine outcome to render.
        """
        table = self.create_table(title="Requeue for a Dream")
        table.add_column("Artist")
        table.add_column("Current release")
        table.add_column("Action")
        table.add_column("Next release")
        table.add_column("First track")
        action = {
            "advance": "would advance" if dry_run else "advanced",
            "drop": "would drop" if dry_run else "dropped",
            "empty": "empty",
            "skip": "skipped",
        }[summary.action]
        if summary.target_already_present:
            action += " (already present)"
        if summary.reason:
            action += f" ({summary.reason})"
        table.add_row(
            summary.artist or ("-"),
            summary.source_release or ("-"),
            action,
            summary.target_release or ("-"),
            summary.target_track or ("-"),
        )
        self._flush_requeue_for_a_dream_console.print(table)
        self._flush_requeue_for_a_dream_console.print(
            (
                "Playlist: "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                " tracks"
            )
            + (" (preview only)." if dry_run else "."),
            style="bold cyan" if dry_run else "bold green",
        )
