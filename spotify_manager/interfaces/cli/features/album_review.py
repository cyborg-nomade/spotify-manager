"""Explicit album review CLI execution, prompts and presentation."""

from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.progress import Progress
from rich.prompt import Prompt

from spotify_manager.interfaces.cli.display import ProgressDisplay
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class AlbumReviewCLI:
    """Run album-limit review with terminal choices and progress.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        progress_display: Rich console, table and live-status constructors.
        create_console: Interface presentation resource.
        prompt: Interface presentation resource.
        REVIEW_ACTION_CHOICES: Interface presentation resource.
    """

    runtime: CliResources

    progress_display: ProgressDisplay
    create_console: type[Console]
    prompt: type[Prompt]
    REVIEW_ACTION_CHOICES: list[str]

    def _prompt_review_action(
        self, console: Console, evaluation: object, progress: Progress | None
    ) -> str:
        """Ask for a review action while yielding Rich progress rendering.

        Args:
            console: Rich console receiving this command's output.
            evaluation: Evaluation supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        default = "r"
        if getattr(evaluation, "decision", None) != "remove":
            default = "s"
        if progress is not None:
            progress.stop()
        try:
            return self.prompt.ask(
                "Action [r]emove / [k]eep anyway / [s]kip / [d]etails / [q]uit",
                choices=self.REVIEW_ACTION_CHOICES,
                default=default,
                console=console,
            )
        finally:
            if progress is not None:
                progress.start()

    def _run_review_album_limits(
        self, threshold: float, no_cache: bool, refresh_cache: bool
    ) -> None:
        """Interactively remove saved albums below the liked-track threshold.

        Args:
            threshold: Threshold supplied by the caller.
            no_cache: No cache supplied by the caller.
            refresh_cache: Refresh cache supplied by the caller.
        """
        if threshold < 0 or threshold > 1:
            raise typer.BadParameter("threshold must be between 0 and 1")
        self._review_album_limits_console = self.create_console()
        self._review_album_limits_progress_ref: Progress | None = None
        try:
            with self.progress_display.create_progress(
                self.progress_display.spinner_column(),
                self.progress_display.text_column(
                    "[progress.description]{task.description}"
                ),
                self.progress_display.bar_column(),
                self.progress_display.complete_column(),
                self.progress_display.time_column(),
                console=self._review_album_limits_console,
                transient=True,
            ) as self._review_album_limits_progress:
                self._review_album_limits_progress_ref = (
                    self._review_album_limits_progress
                )
                self._review_album_limits_task_id = (
                    self._review_album_limits_progress.add_task(
                        "Reviewing albums", total=None
                    )
                )
                review_album_limits.review_album_limits(
                    self.runtime.review_client(),
                    action_reader=self._review_album_limits_read_action,
                    threshold=threshold,
                    use_cache=not no_cache,
                    refresh_cache=refresh_cache,
                    echo=self._review_album_limits_echo,
                    progress_callback=self._review_album_limits_update_progress,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_review_album_limits_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_review_album_limits_server_failure(exc)

    def _review_album_limits_echo(self, line: str = "") -> None:
        """Review album limits echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith("Followed artist") or line.startswith("Recorded artist"):
            style = "cyan"
        elif line.startswith("Updated stats_history"):
            style = "cyan dim"
        elif " keep: " in line or "previously kept" in line:
            style = "green"
        elif line.startswith("Kept anyway:"):
            style = "bold green"
        elif "remove candidate" in line:
            style = "yellow"
        elif line.startswith("Removed:") or line.startswith("Auto-removed"):
            style = "bold red"
        elif line.startswith("Live liked tracks"):
            style = "cyan"
        elif line.startswith("Skipped:"):
            style = "dim yellow"
        elif line.startswith("Review complete"):
            style = "bold"
        self._review_album_limits_console.print(line, style=style, markup=False)

    def _review_album_limits_read_action(
        self, _album: object, evaluation: object
    ) -> str:
        return self._prompt_review_action(
            self._review_album_limits_console,
            evaluation,
            self._review_album_limits_progress_ref,
        )

    def _review_album_limits_update_progress(self, position: int, total: int) -> None:
        self._review_album_limits_progress.update(
            self._review_album_limits_task_id, completed=position, total=total
        )

    def _report_review_album_limits_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._review_album_limits_console.print(
            (
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
            ),
            style="bold yellow",
        )
        self._review_album_limits_console.print(
            "Progress was saved up to the last successful removal.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_review_album_limits_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._review_album_limits_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._review_album_limits_console.print(
            "Progress was saved up to the last successful removal.", style="yellow"
        )
        raise typer.Exit(code=0) from exc
