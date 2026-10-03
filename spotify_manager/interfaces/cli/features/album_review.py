"""Explicit album review CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.prompt import Prompt
from spotipy import Spotify

from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class AlbumReviewCLI:
    """Execute and present album review through explicit facade dependencies.

    Args:
        bar_column: Rich bar column constructor.
        create_console: Factory for console instances.
        complete_column: Rich complete column constructor.
        create_progress: Factory for progress instances.
        prompt: Rich prompt implementation supplied by the facade.
        REVIEW_ACTION_CHOICES: Review action choices supplied by the caller.
        spinner_column: Rich spinner column constructor.
        text_column: Rich text column constructor.
        time_column: Rich time column constructor.
        ask_review_action: Original ask review action boundary supplied by the facade.
        review_client: Original Spotify client factory supplied by the facade.
    """

    bar_column: type[BarColumn]
    create_console: type[Console]
    complete_column: type[MofNCompleteColumn]
    create_progress: type[Progress]
    prompt: type[Prompt]
    REVIEW_ACTION_CHOICES: list[str]
    spinner_column: type[SpinnerColumn]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    ask_review_action: Callable[..., str]
    review_client: Callable[..., Spotify]

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
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
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
                    self.review_client(),
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
        return self.ask_review_action(
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
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
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
