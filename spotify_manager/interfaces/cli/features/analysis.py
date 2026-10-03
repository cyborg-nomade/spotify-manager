"""Explicit analysis CLI execution, prompts and presentation."""

import select
import sys
import termios
import tty
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Never

import typer
from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TaskID
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.table import Table
from rich.text import Text
from spotipy import Spotify

from spotify_manager.interfaces.operations import analyse_library as library_sync
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class AnalysisCLI:
    """Execute and present analysis through explicit facade dependencies.

    Args:
        bar_column: Rich bar column constructor.
        create_console: Factory for console instances.
        create_live: Factory for live instances.
        complete_column: Rich complete column constructor.
        create_progress: Factory for progress instances.
        spinner_column: Rich spinner column constructor.
        create_table: Factory for table instances.
        create_text: Factory for text instances.
        text_column: Rich text column constructor.
        time_column: Rich time column constructor.
        monotonic: Monotonic supplied by the caller.
        print_library_analysis_summary: Original print library analysis summary boundary
            supplied by the facade.
        review_client: Original Spotify client factory supplied by the facade.
        run_library_analysis: Original run library analysis boundary supplied by the
            facade.
        sleep: Original retry delay boundary supplied by the facade.
        wait_for_library_retry: Original wait for library retry boundary supplied by the
            facade.
    """

    bar_column: type[BarColumn]
    create_console: type[Console]
    create_live: type[Live]
    complete_column: type[MofNCompleteColumn]
    create_progress: type[Progress]
    spinner_column: type[SpinnerColumn]
    create_table: type[Table]
    create_text: type[Text]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    monotonic: Callable[[], float]
    print_library_analysis_summary: Callable[..., None]
    review_client: Callable[..., Spotify]
    run_library_analysis: Callable[..., None]
    sleep: Callable[[float], None]
    wait_for_library_retry: Callable[..., bool]

    def _wait_for_library_retry(
        self,
        console: Console,
        notice: library_sync.RetryNotice,
        spotify: Spotify,
        progress: Progress | None,
    ) -> bool:
        """Wait for a retry while accepting rotate or quit without Enter.

        Args:
            console: Rich console receiving this command's output.
            notice: Notice supplied by the caller.
            spotify: Spotify supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        self._show_retry_notice(console, notice)
        try:
            if not sys.stdin.isatty():
                self.sleep(notice.delay_seconds)
                return True
            return self._wait_terminal_retry(console, spotify, notice.delay_seconds)
        finally:
            if progress is not None:
                progress.start()

    def _render_library_analysis_summary(
        self, console: Console, summary: library_sync.LibrarySyncSummary
    ) -> None:
        """Render the common completion table for either analysis mode.

        Args:
            console: Rich console receiving this command's output.
            summary: Completed routine outcome to render.
        """
        labels = {
            "albums": "Saved albums",
            "tracks": "Liked tracks",
            "artists": "Followed artists",
        }
        title = (
            "Export library mirror updated"
            if summary.mode == "async"
            else "Live library mirror updated"
        )
        table = self.create_table(title=title)
        table.add_column("Resource")
        table.add_column("Source")
        table.add_column("Previous", justify="right")
        table.add_column("Current", justify="right")
        table.add_column("Added", justify="right", style="green")
        table.add_column("Removed", justify="right", style="red")
        table.add_column("Skipped", justify="right", style="yellow")
        for resource in summary.resources:
            table.add_row(
                labels[resource.resource],
                resource.source,
                str(resource.previous),
                str(resource.current),
                str(resource.added),
                str(resource.removed),
                str(resource.skipped),
            )
        console.print(table)
        console.print(f"Run: {summary.run_id}", style="bold")
        console.print(f"Undo backup: {summary.backup_dir}", style="dim")
        console.print(
            (f"Audit manifest: {summary.backup_dir}/manifest.json"), style="dim"
        )

    def _run_library_analysis(self, mode: library_sync.AnalysisMode) -> None:
        """Run one analysis mode with shared Rich progress and error handling.

        Args:
            mode: Mode supplied by the caller.
        """
        self._run_library_analysis_console = self.create_console()
        self._run_library_analysis_labels = {
            "albums": "Saved albums",
            "tracks": "Liked tracks",
            "artists": "Followed artists",
        }
        self._run_library_analysis_progress_ref: Progress | None = None
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._run_library_analysis_console,
                transient=True,
            ) as self._run_library_analysis_progress:
                self._run_library_analysis_progress_ref = (
                    self._run_library_analysis_progress
                )
                self._run_library_analysis_tasks = self._create_analysis_tasks()
                summary = self._execute_analysis_mode(mode)
        except library_sync.LibraryAnalysisCancelledError as exc:
            self._report_run_library_analysis_cancelled(exc)
        except library_sync.SpotifyRateLimitError as exc:
            self._report_run_library_analysis_rate_limit(exc)
        except KeyboardInterrupt as exc:
            self._report_run_library_analysis_interrupted_interrupted(exc)
        except library_sync.LibrarySyncError as exc:
            self._report_run_library_analysis_library_sync_failure(exc)
        self.print_library_analysis_summary(self._run_library_analysis_console, summary)

    def _run_library_analysis_update_progress(
        self, resource: str, completed: int, total: int | None, status: str
    ) -> None:
        display_total = max(completed, total) if total is not None else None
        self._run_library_analysis_progress.update(
            self._run_library_analysis_tasks[resource],
            completed=completed,
            total=display_total,
            description=(f"{self._run_library_analysis_labels[resource]}: {status}"),
        )

    def _run_library_analysis_log(self, line: str) -> None:
        return self._run_library_analysis_console.print(
            line, style="yellow", markup=False
        )

    def _run_library_analysis_wait_for_library_retry(
        self, notice: library_sync.RetryNotice
    ) -> bool:
        return self.wait_for_library_retry(
            self._run_library_analysis_console,
            notice,
            self._run_library_analysis_spotify,
            self._run_library_analysis_progress_ref,
        )

    def _analyse_library_async(self) -> None:
        """Build suffixed mirrors exclusively from YourLibrary.json."""
        self.run_library_analysis("async")

    def _analyse_library_sync(self) -> None:
        """Build suffixed mirrors exclusively from the live Spotify API."""
        self.run_library_analysis("sync")

    def _run_restore_library_sync(self, run_id: str, yes: bool) -> None:
        """Restore generated library files from an async or sync backup.

        Args:
            run_id: Original run id boundary supplied by the facade.
            yes: Yes supplied by the caller.
        """
        if not yes and (
            not typer.confirm(
                f"Restore generated library files from analysis {run_id}?"
            )
        ):
            raise typer.Abort()
        try:
            restored = library_sync.restore_library_sync(run_id)
        except library_sync.LibrarySyncRestoreError as exc:
            self._report_restore_library_sync_library_sync_restore_failure(exc)
        typer.echo(f"Restored: {', '.join(restored)}")

    def _report_run_library_analysis_cancelled(
        self, exc: library_sync.LibraryAnalysisCancelledError
    ) -> Never:
        self._run_library_analysis_console.print(str(exc), style="bold yellow")
        self._run_library_analysis_console.print(
            "Progress was saved; rerun the same command to resume.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_run_library_analysis_rate_limit(
        self, exc: library_sync.SpotifyRateLimitError
    ) -> Never:
        self._run_library_analysis_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        self._run_library_analysis_console.print(
            "Library sync progress was saved; rerun the same command to resume.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_run_library_analysis_library_sync_failure(
        self, exc: library_sync.LibrarySyncError
    ) -> Never:
        self._run_library_analysis_console.print(str(exc), style="bold red")
        self._run_library_analysis_console.print(
            (
                "No partial staging data was published. Rerun to "
                "resume after fixing the underlying issue."
            ),
            style="yellow",
        )
        raise typer.Exit(code=1) from exc

    def _report_run_library_analysis_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._run_library_analysis_console.print(
            "Analysis paused. Progress was saved.", style="bold yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_restore_library_sync_library_sync_restore_failure(
        self, exc: library_sync.LibrarySyncRestoreError
    ) -> Never:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    def _show_retry_notice(
        self, console: Console, notice: library_sync.RetryNotice
    ) -> None:
        retry_at = datetime.now().astimezone() + timedelta(seconds=notice.delay_seconds)
        failure = (
            (f"Spotify HTTP {notice.http_status}")
            if notice.http_status is not None
            else "Spotify connection interrupted"
        )
        console.print(f"{failure} while {notice.operation}.", style="bold yellow")
        console.print(
            (
                "Retry "
                f"{notice.attempt}"
                " at "
                f"{retry_at.isoformat(timespec='seconds')}"
                ". Press r to rotate credentials and retry now, "
                "or q to save and quit."
            ),
            style="yellow",
        )

    def _wait_terminal_retry(
        self, console: Console, spotify: Spotify, delay: float
    ) -> bool:
        """Wait terminal retry.

        Args:
            console: Rich console receiving this command's output.
            spotify: Spotify supplied by the caller.
            delay: Delay supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        descriptor = sys.stdin.fileno()
        old_settings = termios.tcgetattr(descriptor)
        deadline = self.monotonic() + delay
        try:
            tty.setcbreak(descriptor)
            with self.create_live(
                console=console, refresh_per_second=2, transient=True
            ) as live:
                return self._read_retry_keys(console, spotify, deadline, live)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, old_settings)

    def _read_retry_keys(
        self, console: Console, spotify: Spotify, deadline: float, live: Live
    ) -> bool:
        """Read retry keys.

        Args:
            console: Rich console receiving this command's output.
            spotify: Spotify supplied by the caller.
            deadline: Deadline supplied by the caller.
            live: Live supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        while True:
            remaining = max(0, int(deadline - self.monotonic() + 0.999))
            if remaining == 0:
                return True
            live.update(
                self.create_text(
                    (
                        "Retrying in "
                        f"{remaining}"
                        " seconds. Press r to rotate or q to quit."
                    ),
                    style="yellow",
                )
            )
            readable, _, _ = select.select([sys.stdin], [], [], min(1.0, remaining))
            if not readable:
                continue
            action = sys.stdin.read(1).lower()
            if action == "q":
                return False
            if action == "r" and self._rotate_retry_credentials(console, spotify):
                return True

    def _rotate_retry_credentials(self, console: Console, spotify: Spotify) -> bool:
        """Rotate retry credentials.

        Args:
            console: Rich console receiving this command's output.
            spotify: Spotify supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        rotate = getattr(spotify, "rotate_credentials", None)
        if not callable(rotate):
            console.print(
                (
                    "This Spotify client cannot rotate credentials; "
                    "continuing the retry wait."
                ),
                style="bold yellow",
            )
            return False
        try:
            label = rotate()
        except Exception as exc:
            console.print(
                (f"Could not rotate credentials: {exc} Continuing the retry wait."),
                style="bold yellow",
            )
            return False
        console.print(f"Rotated to {label}; retrying now.", style="bold green")
        return True

    def _create_analysis_tasks(self) -> dict[str, TaskID]:
        tasks = {}
        for resource, label in self._run_library_analysis_labels.items():
            tasks[resource] = self._run_library_analysis_progress.add_task(
                label, total=None
            )
        return tasks

    def _execute_analysis_mode(
        self, mode: library_sync.AnalysisMode
    ) -> library_sync.LibrarySyncSummary:
        if mode == "async":
            return library_sync.analyse_library_async_routine(
                echo=self._run_library_analysis_log,
                progress_callback=self._run_library_analysis_update_progress,
            )
        self._run_library_analysis_spotify = self.review_client()
        return library_sync.analyse_library_sync_routine(
            self._run_library_analysis_spotify,
            echo=self._run_library_analysis_log,
            progress_callback=self._run_library_analysis_update_progress,
            retry_wait=self._run_library_analysis_wait_for_library_retry,
        )
