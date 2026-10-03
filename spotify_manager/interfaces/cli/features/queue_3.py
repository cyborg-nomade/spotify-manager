"""Explicit queue 3 CLI execution, prompts and presentation."""

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
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.interfaces.operations import new_wine as new_wine
from spotify_manager.interfaces.operations import queue_3 as queue_3
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import slow_listening as slow_listening
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class Queue3CLI:
    """Execute and present queue 3 through explicit facade dependencies.

    Args:
        bar_column: Rich bar column constructor.
        create_console: Factory for console instances.
        complete_column: Rich complete column constructor.
        create_progress: Factory for progress instances.
        prompt: Rich prompt implementation supplied by the facade.
        configuration: Original settings factory supplied by the facade.
        spinner_column: Rich spinner column constructor.
        create_table: Factory for table instances.
        text_column: Rich text column constructor.
        time_column: Rich time column constructor.
        _render_queue_3_annual_import:  render queue 3 annual import supplied by the
            caller.
        ask_queue_3_composer_playlist: Original ask queue 3 composer playlist boundary
            supplied by the facade.
        ask_queue_3_release_transition: Original ask queue 3 release transition boundary
            supplied by the facade.
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
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    _render_queue_3_annual_import: Callable[..., None]
    ask_queue_3_composer_playlist: Callable[..., str]
    ask_queue_3_release_transition: Callable[..., str]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _prompt_queue_3_release_transition(
        self,
        console: Console,
        source: new_wine.PlaylistTrack,
        current_release: slow_listening.DiscographyRelease,
        next_release: slow_listening.DiscographyRelease,
        progress: Progress | None,
    ) -> str:
        """Confirm the next chronological release at a Queue 3 boundary.

        Args:
            console: Rich console receiving this command's output.
            source: Source supplied by the caller.
            current_release: Current release supplied by the caller.
            next_release: Next release supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            table = self.create_table(
                title=(f"Queue 3 release boundary: {source.primary_artist_name}")
            )
            table.add_column("Position")
            table.add_column("Release")
            table.add_column("Type")
            table.add_column("Date")
            table.add_column("Tracks", justify="right")
            table.add_row(
                "Current",
                current_release.name,
                current_release.release_type,
                current_release.chronology_date,
                str(current_release.total_tracks),
            )
            table.add_row(
                "Next",
                next_release.name,
                next_release.release_type,
                next_release.chronology_date,
                str(next_release.total_tracks),
            )
            console.print(table)
            response = self.prompt.ask(
                "Advance to this release?",
                choices=["y", "q"],
                default="y",
                console=console,
            )
            return queue_3.CHOICE_ADVANCE if response == "y" else queue_3.CHOICE_QUIT
        finally:
            if progress is not None:
                progress.start()

    def _prompt_queue_3_composer_playlist(
        self,
        console: Console,
        artist_name: str,
        candidates: tuple[queue_3.OwnedPlaylist, ...],
        progress: Progress | None,
    ) -> str:
        """Choose one owned composer playlist when names are ambiguous.

        Args:
            console: Rich console receiving this command's output.
            artist_name: Artist name supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            table = self.create_table(title=f"Queue 3 composer playlist: {artist_name}")
            table.add_column("#", justify="right")
            table.add_column("Owned playlist")
            table.add_column("Tracks", justify="right")
            for index, candidate in enumerate(candidates, start=1):
                table.add_row(str(index), candidate.name, str(candidate.total_tracks))
            console.print(table)
            response = self.prompt.ask(
                "Use which composer playlist?",
                choices=[
                    *(str(index) for index in range(1, len(candidates) + 1)),
                    "q",
                ],
                default="1",
                console=console,
            )
            if response == "q":
                return queue_3.CHOICE_QUIT
            return candidates[int(response) - 1].spotify_id
        finally:
            if progress is not None:
                progress.start()

    def _show_annual_import(
        self, console: Console, results: tuple[queue_3.AnnualImportResult, ...]
    ) -> None:
        """Render previous-year Queue 3 markers consistently across commands.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        if not results:
            return
        import_table = self.create_table(title="Previous-year Great Discoveries")
        import_table.add_column("Artist")
        import_table.add_column("Track")
        import_table.add_column("Year", justify="right")
        import_table.add_column("Action")
        for seed_result in results:
            import_table.add_row(
                seed_result.artist,
                seed_result.track,
                str(seed_result.source_year),
                seed_result.action,
            )
        console.print(import_table)

    def _run_import_queue_3_previous_year(self, dry_run: bool) -> None:
        """Import last year's Great Discoveries without advancing Queue 3.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._import_queue_3_previous_year_console = self.create_console()
        configuration = self.configuration()
        try:
            playlist_id = queue_3.parse_playlist_id(configuration.the_queue_3_playlist)
        except queue_3.Queue3ConfigError as exc:
            self._report_import_queue_3_previous_year_configuration_failure(exc)
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._import_queue_3_previous_year_console,
                transient=True,
            ) as self._import_queue_3_previous_year_progress:
                self._import_queue_3_previous_year_task_id = (
                    self._import_queue_3_previous_year_progress.add_task(
                        "Loading previous-year discoveries", total=1
                    )
                )
                summary = queue_3.import_previous_year_discoveries(
                    self.review_client(),
                    playlist_id,
                    dry_run=dry_run,
                    echo=self._import_queue_3_previous_year_echo,
                    progress_callback=self._import_queue_3_previous_year_update_progress,
                    retry_call=self._import_queue_3_previous_year_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_import_queue_3_previous_year_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_import_queue_3_previous_year_server_failure(exc)
        except queue_3.Queue3Error as exc:
            self._report_import_queue_3_previous_year_queue3_failure(exc)
        except SpotifyException as exc:
            self._report_import_queue_3_previous_year_spotify_spotify_failure(exc)
        self._show_import_queue_3_previous_year(dry_run, summary)

    def _import_queue_3_previous_year_echo(self, line: str = "") -> None:
        style = "yellow" if line.startswith("Would") else "cyan"
        self._import_queue_3_previous_year_console.print(
            line, style=style, markup=False
        )

    def _import_queue_3_previous_year_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._import_queue_3_previous_year_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _import_queue_3_previous_year_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._import_queue_3_previous_year_progress.update(
            self._import_queue_3_previous_year_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _run_flush_queue_3(self, dry_run: bool) -> None:
        """Advance the first ten Queue 3 artists through studio discographies.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_queue_3_console = self.create_console()
        self._flush_queue_3_progress_ref: Progress | None = None
        configuration = self.configuration()
        try:
            playlist_id = queue_3.parse_playlist_id(configuration.the_queue_3_playlist)
        except queue_3.Queue3ConfigError as exc:
            self._report_flush_queue_3_configuration_failure(exc)
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._flush_queue_3_console,
                transient=True,
            ) as self._flush_queue_3_progress:
                self._flush_queue_3_progress_ref = self._flush_queue_3_progress
                description = progress_description("Planning Queue 3 flush", dry_run)
                self._flush_queue_3_task_id = self._flush_queue_3_progress.add_task(
                    description, total=None
                )
                summary = queue_3.flush_queue_3(
                    self.review_client(),
                    playlist_id,
                    transition_reader=self._flush_queue_3_ask_queue_3_release_transition,
                    composer_playlist_reader=self._flush_queue_3_ask_queue_3_composer_playlist,
                    dry_run=dry_run,
                    echo=self._flush_queue_3_echo,
                    progress_callback=self._flush_queue_3_update_progress,
                    retry_call=self._flush_queue_3_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_queue_3_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_queue_3_server_failure(exc)
        except queue_3.Queue3CancelledError as exc:
            self._report_flush_queue_3_cancelled(exc)
        except queue_3.Queue3Error as exc:
            self._report_flush_queue_3_queue3_failure(exc)
        except SpotifyException as exc:
            self._report_flush_queue_3_spotify_spotify_failure(exc)
        except KeyboardInterrupt as exc:
            self._report_flush_queue_3_interrupted_interrupted(exc)
        self._show_flush_queue(dry_run, summary)

    def _flush_queue_3_echo(self, line: str = "") -> None:
        """Flush queue 3 echo.

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
        elif line.startswith("Reconciled") or line.startswith("Imported"):
            style = "cyan"
        elif line.startswith("Skipped"):
            style = "dim yellow"
        self._flush_queue_3_console.print(line, style=style, markup=False)

    def _flush_queue_3_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_queue_3_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _flush_queue_3_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._flush_queue_3_progress.update(
            self._flush_queue_3_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _flush_queue_3_ask_queue_3_release_transition(
        self,
        source: new_wine.PlaylistTrack,
        current: slow_listening.DiscographyRelease,
        following: slow_listening.DiscographyRelease,
    ) -> str:
        return self.ask_queue_3_release_transition(
            self._flush_queue_3_console,
            source,
            current,
            following,
            self._flush_queue_3_progress_ref,
        )

    def _flush_queue_3_ask_queue_3_composer_playlist(
        self, artist: str, candidates: tuple[queue_3.OwnedPlaylist, ...]
    ) -> str:
        return self.ask_queue_3_composer_playlist(
            self._flush_queue_3_console,
            artist,
            candidates,
            self._flush_queue_3_progress_ref,
        )

    def _report_flush_queue_3_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._flush_queue_3_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        self._flush_queue_3_console.print(
            "The active Queue 3 run was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_3_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._flush_queue_3_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._flush_queue_3_console.print(
            "The active Queue 3 run was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_3_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._flush_queue_3_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        self._flush_queue_3_console.print(
            "The active Queue 3 run was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=1) from exc

    def _report_import_queue_3_previous_year_configuration_failure(
        self, exc: queue_3.Queue3ConfigError
    ) -> Never:
        self._import_queue_3_previous_year_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_import_queue_3_previous_year_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._import_queue_3_previous_year_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_import_queue_3_previous_year_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._import_queue_3_previous_year_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_import_queue_3_previous_year_queue3_failure(
        self, exc: queue_3.Queue3Error
    ) -> Never:
        self._import_queue_3_previous_year_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_import_queue_3_previous_year_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._import_queue_3_previous_year_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_3_configuration_failure(
        self, exc: queue_3.Queue3ConfigError
    ) -> Never:
        self._flush_queue_3_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_3_cancelled(
        self, exc: queue_3.Queue3CancelledError
    ) -> Never:
        self._flush_queue_3_console.print(str(exc), style="bold yellow", markup=False)
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_3_queue3_failure(self, exc: queue_3.Queue3Error) -> Never:
        self._flush_queue_3_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_3_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._flush_queue_3_console.print(
            "Queue 3 flush paused. The active run was saved.", style="bold yellow"
        )
        raise typer.Exit(code=0) from exc

    def _show_import_queue_3_previous_year(
        self, dry_run: bool, summary: queue_3.AnnualImportSummary
    ) -> None:
        """Show import queue 3 previous year.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            summary: Completed routine outcome to render.
        """
        self._render_queue_3_annual_import(
            self._import_queue_3_previous_year_console, summary.results
        )
        if summary.already_completed:
            self._import_queue_3_previous_year_console.print(
                (f"Great Discoveries {summary.source_year} was already imported."),
                style="cyan",
            )
            return
        action = "would be added" if dry_run else "added"
        artist_label = "artist" if summary.additions == 1 else "artists"
        self._import_queue_3_previous_year_console.print(
            (
                "Great Discoveries "
                f"{summary.source_year}"
                ": "
                f"{summary.additions}"
                " "
                f"{artist_label}"
                " "
                f"{action}"
                "; "
                f"{summary.already_present}"
                " already present."
            )
            + (" Preview only." if dry_run else ""),
            style="bold cyan" if dry_run else "bold green",
        )

    def _show_flush_queue(self, dry_run: bool, summary: queue_3.FlushSummary) -> None:
        """Show flush queue.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            summary: Completed routine outcome to render.
        """
        self._render_queue_3_annual_import(
            self._flush_queue_3_console, summary.annual_import
        )
        table = self.create_table(title="The Queue 3")
        table.add_column("Artist")
        table.add_column("Current")
        table.add_column("Release")
        table.add_column("Action")
        table.add_column("Next")
        for flush_result in summary.results:
            next_item = flush_result.target_track or "-"
            if (
                flush_result.target_release
                and flush_result.target_release != flush_result.source_release
            ):
                next_item = f"{flush_result.target_release} - {next_item}"
            if flush_result.composer_playlist:
                next_item = f"{flush_result.composer_playlist} - {next_item}"
            action_text = str(flush_result.action)
            if flush_result.album_decision is not None:
                action_text += (
                    "; "
                    f"{flush_result.album_decision}"
                    " "
                    f"{flush_result.album_liked_tracks}"
                    "/"
                    f"{flush_result.album_total_tracks}"
                )
            table.add_row(
                flush_result.artist,
                flush_result.source_track,
                flush_result.source_release,
                action_text,
                next_item,
            )
        self._flush_queue_3_console.print(table)
        self._flush_queue_3_console.print(
            (
                "Processed "
                f"{summary.processed}"
                "/"
                f"{summary.total}"
                ": "
                f"{summary.advanced}"
                " track advances, "
                f"{summary.changed_releases}"
                " release changes, "
                f"{summary.completed_artists}"
                " completed artists, "
                f"{summary.skipped}"
                " skipped."
            )
            + (" Preview only." if dry_run else ""),
            style="bold cyan" if dry_run else "bold green",
        )
        if summary.resumed:
            self._flush_queue_3_console.print(
                "Resumed the previously saved Queue 3 flush.", style="cyan"
            )
        if summary.paused:
            self._flush_queue_3_console.print(
                "Queue 3 flush paused; run the command again to resume.",
                style="bold yellow",
            )
