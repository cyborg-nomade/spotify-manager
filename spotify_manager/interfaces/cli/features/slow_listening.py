"""Explicit slow listening CLI execution, prompts and presentation."""

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
from rich.table import Table
from rich.text import Text
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.interfaces.operations import new_wine as new_wine
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import slow_listening as slow_listening
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class SlowListeningCLI:
    """Execute and present slow listening through explicit facade dependencies.

    Args:
        bar_column: Rich bar column constructor.
        create_console: Factory for console instances.
        complete_column: Rich complete column constructor.
        create_progress: Factory for progress instances.
        prompt: Rich prompt implementation supplied by the facade.
        configuration: Original settings factory supplied by the facade.
        spinner_column: Rich spinner column constructor.
        create_table: Factory for table instances.
        create_text: Factory for text instances.
        text_column: Rich text column constructor.
        time_column: Rich time column constructor.
        acknowledge_slow_listening_completion: Acknowledge slow listening completion
            supplied by the caller.
        ask_slow_listening_action: Original ask slow listening action boundary supplied
            by the facade.
        ask_slow_listening_release_order: Original ask slow listening release order
            boundary supplied by the facade.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    bar_column: type[BarColumn]
    create_console: type[Console]
    complete_column: type[MofNCompleteColumn]
    create_progress: type[Progress]
    prompt: type[Prompt]
    configuration: type[Settings]
    spinner_column: type[SpinnerColumn]
    create_table: type[Table]
    create_text: type[Text]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    acknowledge_slow_listening_completion: Callable[..., None]
    ask_slow_listening_action: Callable[..., str]
    ask_slow_listening_release_order: Callable[..., tuple[str, ...]]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _prompt_slow_listening_release_order(
        self,
        console: Console,
        release_date: str,
        candidates: tuple[slow_listening.DiscographyRelease, ...],
        progress: Progress | None,
    ) -> tuple[str, ...]:
        """Prompt for chronological order when Spotify dates are identical.

        Args:
            console: Rich console receiving this command's output.
            release_date: Release date supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            return self._read_slow_listening_release_order(
                console, release_date, candidates, progress
            )
        finally:
            if progress is not None:
                progress.start()

    def _prompt_slow_listening_action(
        self,
        console: Console,
        source: new_wine.PlaylistTrack,
        target: new_wine.ReleaseTrack,
        target_release: slow_listening.DiscographyRelease,
        progress: Progress | None,
    ) -> str:
        """Ask whether the proposed replacement should be added or skipped.

        Args:
            console: Rich console receiving this command's output.
            source: Source supplied by the caller.
            target: Target supplied by the caller.
            target_release: Target release supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            response = self.prompt.ask(
                (
                    "Next after "
                    f"{source.primary_artist_name}"
                    " - "
                    f"{source.name}"
                    ": "
                    f"{target.name}"
                    " ("
                    f"{target_release.name}"
                    "). [a]dd / [s]kip this track / [q]uit"
                ),
                choices=["a", "s", "q"],
                default="a",
                console=console,
            )
            return {
                "a": slow_listening.CHOICE_ADVANCE,
                "s": slow_listening.CHOICE_SKIP,
                "q": slow_listening.CHOICE_QUIT,
            }[response]
        finally:
            if progress is not None:
                progress.start()

    def _acknowledge_slow_listening_completion(
        self,
        console: Console,
        source: new_wine.PlaylistTrack,
        progress: Progress | None,
    ) -> None:
        """Pause after an artist leaves Slow Listening so its slot can be filled.

        Args:
            console: Rich console receiving this command's output.
            source: Source supplied by the caller.
            progress: Active progress display to suspend while prompting.
        """
        if progress is not None:
            progress.stop()
        try:
            console.print(
                (f"{source.primary_artist_name} has completed Slow Listening."),
                style="bold cyan",
            )
            console.input(
                "Add a new artist to the playlist, then press Enter to continue. "
            )
        finally:
            if progress is not None:
                progress.start()

    def _run_flush_slow_listening(self, dry_run: bool) -> None:
        """Advance the first two Slow Listening tracks through studio releases.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_slow_listening_console = self.create_console()
        self._flush_slow_listening_progress_ref: Progress | None = None
        configuration = self.configuration()
        try:
            playlist_id = slow_listening.parse_playlist_id(
                configuration.slow_listening_playlist
            )
        except slow_listening.SlowListeningConfigError as exc:
            self._report_flush_slow_listening_configuration_failure(exc)
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._flush_slow_listening_console,
                transient=True,
            ) as self._flush_slow_listening_progress:
                self._flush_slow_listening_progress_ref = (
                    self._flush_slow_listening_progress
                )
                description = progress_description(
                    "Planning Slow Listening flush", dry_run
                )
                self._flush_slow_listening_task_id = (
                    self._flush_slow_listening_progress.add_task(
                        description, total=None
                    )
                )
                summary = slow_listening.flush_slow_listening(
                    self.review_client(),
                    playlist_id,
                    order_reader=self._flush_slow_listening_ask_slow_listening_release_order,
                    completion_notifier=self._flush_slow_listening_acknowledge_slow_listening_completion,
                    action_reader=self._flush_slow_listening_ask_slow_listening_action,
                    dry_run=dry_run,
                    echo=self._flush_slow_listening_echo,
                    progress_callback=self._flush_slow_listening_update_progress,
                    retry_call=self._flush_slow_listening_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_slow_listening_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_slow_listening_server_failure(exc)
        except slow_listening.SlowListeningCancelledError as exc:
            self._report_flush_slow_listening_cancelled(exc)
        except slow_listening.SlowListeningError as exc:
            self._report_flush_slow_listening_slow_listening_failure(exc)
        except SpotifyException as exc:
            self._report_flush_slow_listening_spotify_spotify_failure(exc)
        except KeyboardInterrupt as exc:
            self._report_flush_slow_listening_interrupted_interrupted(exc)
        self._show_flush_slow_listening(summary)

    def _flush_slow_listening_echo(self, line: str = "") -> None:
        """Flush slow listening echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith("Added") or line.startswith("Removed"):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("Completed"):
            style = "bold cyan"
        elif line.startswith("Skipped"):
            style = "dim yellow"
        elif line.startswith("Source already removed"):
            style = "cyan"
        self._flush_slow_listening_console.print(line, style=style, markup=False)

    def _flush_slow_listening_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_slow_listening_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _flush_slow_listening_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._flush_slow_listening_progress.update(
            self._flush_slow_listening_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _flush_slow_listening_ask_slow_listening_release_order(
        self,
        release_date: str,
        candidates: tuple[slow_listening.DiscographyRelease, ...],
    ) -> tuple[str, ...]:
        return self.ask_slow_listening_release_order(
            self._flush_slow_listening_console,
            release_date,
            candidates,
            self._flush_slow_listening_progress_ref,
        )

    def _flush_slow_listening_acknowledge_slow_listening_completion(
        self, source: new_wine.PlaylistTrack
    ) -> None:
        return self.acknowledge_slow_listening_completion(
            self._flush_slow_listening_console,
            source,
            self._flush_slow_listening_progress_ref,
        )

    def _flush_slow_listening_ask_slow_listening_action(
        self,
        source: new_wine.PlaylistTrack,
        target: new_wine.ReleaseTrack,
        target_release: slow_listening.DiscographyRelease,
    ) -> str:
        return self.ask_slow_listening_action(
            self._flush_slow_listening_console,
            source,
            target,
            target_release,
            self._flush_slow_listening_progress_ref,
        )

    def _report_flush_slow_listening_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._flush_slow_listening_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        self._flush_slow_listening_console.print(
            "The active Slow Listening run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_slow_listening_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._flush_slow_listening_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._flush_slow_listening_console.print(
            "The active Slow Listening run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_slow_listening_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._flush_slow_listening_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        self._flush_slow_listening_console.print(
            "The active Slow Listening run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_slow_listening_configuration_failure(
        self, exc: slow_listening.SlowListeningConfigError
    ) -> Never:
        self._flush_slow_listening_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_slow_listening_cancelled(
        self, exc: slow_listening.SlowListeningCancelledError
    ) -> Never:
        self._flush_slow_listening_console.print(
            str(exc), style="bold yellow", markup=False
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_slow_listening_slow_listening_failure(
        self, exc: slow_listening.SlowListeningError
    ) -> Never:
        self._flush_slow_listening_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_slow_listening_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._flush_slow_listening_console.print(
            "Slow Listening flush paused. The active run was saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _show_flush_slow_listening(self, summary: slow_listening.FlushSummary) -> None:
        """Show flush slow listening.

        Args:
            summary: Completed routine outcome to render.
        """
        table = self.create_table(title="Slow Listening")
        table.add_column("Artist")
        table.add_column("Current")
        table.add_column("Release")
        table.add_column("Action")
        table.add_column("Next")
        action_styles = {"advance": "green", "complete": "bold cyan", "skip": "yellow"}
        for result in summary.results:
            action = str(result.action)
            if result.skipped_candidates:
                count = len(result.skipped_candidates)
                action += f" ({count} candidate{('s' if count != 1 else '')} skipped)"
            if result.reason:
                action += f" ({result.reason})"
            table.add_row(
                result.artist,
                result.source_track,
                result.source_release,
                self.create_text(action, style=action_styles[result.action]),
                (f"{result.target_track} ({result.target_release})")
                if result.target_track and result.target_release
                else "-",
            )
        self._flush_slow_listening_console.print(table)
        prefix = "Dry run" if summary.dry_run else "Flush"
        self._flush_slow_listening_console.print(
            (
                f"{prefix}"
                ": "
                f"{summary.processed}"
                "/"
                f"{summary.total}"
                " processed; "
                f"{summary.advanced}"
                " advanced, "
                f"{summary.completed_artists}"
                " artists completed, "
                f"{summary.skipped}"
                " skipped."
            ),
            style="bold",
        )
        if summary.resumed:
            self._flush_slow_listening_console.print(
                "Resumed the previously saved flush.", style="cyan"
            )
        if summary.paused:
            self._flush_slow_listening_console.print(
                "Flush paused; run the command again to resume.",
                style="bold yellow",
            )

    def _read_slow_listening_release_order(
        self,
        console: Console,
        release_date: str,
        candidates: tuple[slow_listening.DiscographyRelease, ...],
        progress: Progress | None,
    ) -> tuple[str, ...]:
        """Read slow listening release order.

        Args:
            console: Rich console receiving this command's output.
            release_date: Release date supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        table = self.create_table(title=f"Order releases dated {release_date}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Tracks", justify="right")
        table.add_column("Edition")
        table.add_column("Library")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                candidate.release_type,
                str(candidate.total_tracks),
                "plain" if candidate.plain else "decorated",
                "saved" if candidate.saved else "-",
            )
        console.print(table)
        default = ",".join(str(index) for index in range(1, len(candidates) + 1))
        while True:
            response = self.prompt.ask(
                "Order as comma-separated release numbers / [q]uit",
                default=default,
                console=console,
            ).strip()
            if response.casefold() == "q":
                raise slow_listening.SlowListeningCancelledError(
                    "Slow Listening flush paused while ordering releases."
                )
            try:
                indexes = tuple(int(value.strip()) for value in response.split(","))
            except ValueError:
                indexes = ()
            expected = set(range(1, len(candidates) + 1))
            if len(indexes) == len(candidates) and set(indexes) == expected:
                return tuple(candidates[index - 1].spotify_id for index in indexes)
            console.print(
                "Enter every release number exactly once.", style="bold yellow"
            )
