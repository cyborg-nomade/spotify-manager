"""Explicit wine CLI execution, prompts and presentation."""

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

from spotify_manager.application.new_wine_values import CellarRefillResult
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.routines import new_wine
from spotify_manager.routines import review_album_limits
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class WineCLI:
    """Execute and present wine through explicit facade dependencies.

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
        ask_new_wine_endpoint_choice: Original ask new wine endpoint choice boundary
            supplied by the facade.
        ask_new_wine_release_choice: Original ask new wine release choice boundary
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
    create_text: type[Text]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    ask_new_wine_endpoint_choice: Callable[..., str]
    ask_new_wine_release_choice: Callable[..., str]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _prompt_new_wine_release_choice(
        self,
        console: Console,
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
        progress: Progress | None,
    ) -> str:
        """Prompt for the release that should follow the current release.

        Args:
            console: Rich console receiving this command's output.
            source: Source supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            return self._read_new_wine_release_choice(
                console, source, candidates, progress
            )
        finally:
            if progress is not None:
                progress.start()

    def _prompt_new_wine_endpoint_choice(
        self,
        console: Console,
        source: new_wine.PlaylistTrack,
        tracks: tuple[new_wine.ReleaseTrack, ...],
        current_index: int,
        progress: Progress | None,
    ) -> str:
        """Ask whether the current track is the release's canonical endpoint.

        Args:
            console: Rich console receiving this command's output.
            source: Source supplied by the caller.
            tracks: Tracks supplied by the caller.
            current_index: Current index supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            position = current_index + 1
            response = self.prompt.ask(
                (
                    "Treat "
                    f"{source.release.name}"
                    " track "
                    f"{position}"
                    "/"
                    f"{len(tracks)}"
                    ' "'
                    f"{source.name}"
                    '" as its last canonical track? [y]es / [n]o / '
                    "[s]kip this run / [q]uit"
                ),
                choices=["y", "n", "s", "q"],
                default="n",
                console=console,
            )
            return {
                "y": new_wine.CHOICE_CUTOFF,
                "n": new_wine.CHOICE_CONTINUE,
                "s": new_wine.CHOICE_SKIP,
                "q": new_wine.CHOICE_QUIT,
            }[response]
        finally:
            if progress is not None:
                progress.start()

    def _run_flush_new_wine(
        self, dry_run: bool, no_discovery: bool, choose_album_endpoints: bool
    ) -> None:
        """Advance every New Wine track once according to its release.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            no_discovery: No discovery supplied by the caller.
            choose_album_endpoints: Choose album endpoints supplied by the caller.
        """
        choose_album_endpoints = choose_album_endpoints is True
        self._flush_new_wine_console = self.create_console()
        self._flush_new_wine_progress_ref: Progress | None = None
        configuration = self.configuration()
        try:
            new_wine_playlist_id = new_wine.parse_playlist_id(
                configuration.new_wine_from_old_bottles_playlist,
                "NEW_WINE_FROM_OLD_BOTTLES_PLAYLIST",
            )
            sauvignon_playlist_id = new_wine.parse_playlist_id(
                configuration.sauvignon_terre_neuve_playlist,
                "SAUVIGNON_TERRE_NEUVE_PLAYLIST",
            )
            wine_cellar_playlist_id = new_wine.parse_playlist_id(
                configuration.wine_cellar_playlist, "WINE_CELLAR_PLAYLIST"
            )
        except new_wine.NewWineConfigError as exc:
            self._report_flush_new_wine_configuration_failure(exc)
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._flush_new_wine_console,
                transient=True,
            ) as self._flush_new_wine_progress:
                self._flush_new_wine_progress_ref = self._flush_new_wine_progress
                description = progress_description("Planning New Wine flush", dry_run)
                self._flush_new_wine_task_id = self._flush_new_wine_progress.add_task(
                    description, total=None
                )
                summary = new_wine.flush_new_wine(
                    self.review_client(),
                    new_wine_playlist_id,
                    sauvignon_playlist_id,
                    choice_reader=self._flush_new_wine_ask_new_wine_release_choice,
                    endpoint_choice_reader=self._flush_new_wine_ask_new_wine_endpoint_choice,
                    choose_album_endpoints=choose_album_endpoints,
                    wine_cellar_playlist_id=wine_cellar_playlist_id,
                    no_discovery=no_discovery,
                    dry_run=dry_run,
                    echo=self._flush_new_wine_echo,
                    progress_callback=self._flush_new_wine_update_progress,
                    retry_call=self._flush_new_wine_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_new_wine_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_new_wine_server_failure(exc)
        except new_wine.NewWineError as exc:
            self._report_flush_new_wine_new_wine_failure(exc)
        except SpotifyException as exc:
            self._report_flush_new_wine_spotify_spotify_failure(exc)
        except KeyboardInterrupt as exc:
            self._report_flush_new_wine_interrupted_interrupted(exc)
        self._show_flush_new_wine(summary)

    def _flush_new_wine_echo(self, line: str = "") -> None:
        """Flush new wine echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if (
            line.startswith("Added")
            or line.startswith("Moved")
            or line.startswith("Removed")
        ):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("No ") or "skipping" in line.casefold():
            style = "dim yellow"
        elif line.startswith("Source already removed"):
            style = "cyan"
        self._flush_new_wine_console.print(line, style=style, markup=False)

    def _flush_new_wine_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_new_wine_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _flush_new_wine_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._flush_new_wine_progress.update(
            self._flush_new_wine_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _flush_new_wine_ask_new_wine_release_choice(
        self,
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
    ) -> str:
        return self.ask_new_wine_release_choice(
            self._flush_new_wine_console,
            source,
            candidates,
            self._flush_new_wine_progress_ref,
        )

    def _flush_new_wine_ask_new_wine_endpoint_choice(
        self,
        source: new_wine.PlaylistTrack,
        tracks: tuple[new_wine.ReleaseTrack, ...],
        current_index: int,
    ) -> str:
        return self.ask_new_wine_endpoint_choice(
            self._flush_new_wine_console,
            source,
            tracks,
            current_index,
            self._flush_new_wine_progress_ref,
        )

    def _report_flush_new_wine_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._flush_new_wine_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        self._flush_new_wine_console.print(
            "The active New Wine run was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_new_wine_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._flush_new_wine_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._flush_new_wine_console.print(
            "The active New Wine run was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_new_wine_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._flush_new_wine_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        self._flush_new_wine_console.print(
            "The active New Wine run was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_new_wine_configuration_failure(
        self, exc: new_wine.NewWineConfigError
    ) -> Never:
        self._flush_new_wine_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_new_wine_new_wine_failure(
        self, exc: new_wine.NewWineError
    ) -> Never:
        self._flush_new_wine_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_new_wine_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._flush_new_wine_console.print(
            "New Wine flush paused. The active run was saved.", style="bold yellow"
        )
        raise typer.Exit(code=0) from exc

    def _show_flush_new_wine(self, summary: new_wine.FlushSummary) -> None:
        """Show flush new wine.

        Args:
            summary: Completed routine outcome to render.
        """
        table = self.create_table(title="New Wine from Old Bottles")
        table.add_column("Artist")
        table.add_column("Current track")
        table.add_column("Release")
        table.add_column("Like")
        table.add_column("Streak", justify="right")
        table.add_column("Action")
        table.add_column("Next")
        action_styles = {
            "advance": "green",
            "drop": "bold red",
            "sauvignon": "bold cyan",
            "complete single": "cyan",
            "skip": "yellow",
        }
        for result in summary.results:
            self._row_flush_new_wine_result(action_styles, result, table)
        self._flush_new_wine_console.print(table)
        if summary.refill is not None:
            self._show_cellar_refill(summary.refill)
        prefix = "Dry run" if summary.dry_run else "Flush"
        album_action = "to unsave" if summary.dry_run else "unsaved"
        self._flush_new_wine_console.print(
            (
                f"{prefix}"
                ": "
                f"{summary.processed}"
                "/"
                f"{summary.total}"
                " processed; "
                f"{summary.advanced}"
                " advanced, "
                f"{summary.dropped}"
                " dropped, "
                f"{summary.sent_to_sauvignon}"
                " sent to Sauvignon Terre-Neuve, "
                f"{summary.completed_singles}"
                " singles completed, "
                f"{summary.albums_unsaved}"
                " albums "
                f"{album_action}"
                ", "
                f"{summary.skipped}"
                " skipped."
            ),
            style="bold",
        )
        if summary.resumed:
            self._flush_new_wine_console.print(
                "Resumed the previously saved flush.", style="cyan"
            )
        if summary.paused:
            self._flush_new_wine_console.print(
                "Flush paused; run the command again to resume.",
                style="bold yellow",
            )

    def _read_new_wine_release_choice(
        self,
        console: Console,
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
        progress: Progress | None,
    ) -> str:
        """Read new wine release choice.

        Args:
            console: Rich console receiving this command's output.
            source: Source supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        table = self.create_table(
            title=(
                f"Choose a release for {source.primary_artist_name} after {source.name}"
            )
        )
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_column("Primary artist")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                candidate.release_type,
                candidate.release_date,
                str(candidate.total_tracks),
                candidate.primary_artist_name,
            )
        console.print(table)
        choices = [str(index) for index in range(1, len(candidates) + 1)]
        at_album_endpoint = source.release.release_type in {"Album", "EP"}
        if at_album_endpoint:
            response = self.prompt.ask(
                "Release number / [f]inish / [s]kip this run / [q]uit",
                choices=[*choices, "f", "s", "q"],
                console=console,
            )
        else:
            response = self.prompt.ask(
                "Release number / [d]rop / [s]kip this run / [q]uit",
                choices=[*choices, "d", "s", "q"],
                console=console,
            )
        if response == "f":
            return new_wine.CHOICE_FINISH
        if response == "d":
            return new_wine.CHOICE_DROP
        if response == "s":
            return new_wine.CHOICE_SKIP
        if response == "q":
            return new_wine.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id

    def _row_flush_new_wine_result(
        self, action_styles: dict[str, str], result: FlushResult, table: Table
    ) -> None:
        """Row flush new wine result.

        Args:
            action_styles: Action styles supplied by the caller.
            result: Result supplied by the caller.
            table: Table receiving the original row values.
        """
        action = str(result.action)
        drop_labels = {
            "three_consecutive_unliked": "3 unliked",
            "manual_selection": "chosen",
            "only_current_year_single": "only current-year single",
        }
        if result.action == "drop" and result.drop_reason:
            action += f" ({drop_labels.get(result.drop_reason, result.drop_reason)})"
        if result.advance_reason == "next_liked_track":
            action += " (next liked)"
        if result.album_unsaved:
            action += " + unsaved"
        next_track = result.target_track or "-"
        if result.continuation_track:
            next_track = f"{result.continuation_release} - {result.continuation_track}"
        table.add_row(
            result.artist,
            result.source_track,
            (f"{result.release} ({result.release_type})"),
            "liked" if result.current_liked else "unliked",
            str(result.consecutive_unliked),
            self.create_text(action, style=action_styles[result.action]),
            next_track,
        )

    def _row_flush_new_wine_refill_result(
        self, refill_result: CellarRefillResult, refill_table: Table
    ) -> None:
        refill_table.add_row(
            refill_result.artist,
            refill_result.source_track,
            refill_result.action,
            str(refill_result.liked_tracks)
            if refill_result.liked_tracks is not None
            else "-",
            str(refill_result.saved_albums)
            if refill_result.saved_albums is not None
            else "-",
        )

    def _show_cellar_refill(self, refill: new_wine.CellarRefillSummary) -> None:
        """Show cellar refill.

        Args:
            refill: Refill supplied by the caller.
        """
        refill_table = self.create_table(title="Wine Cellar refill")
        refill_table.add_column("Artist")
        refill_table.add_column("Track")
        refill_table.add_column("Action")
        refill_table.add_column("Liked", justify="right")
        refill_table.add_column("Albums", justify="right")
        displayed_results = []
        for result in refill.results:
            if result.action != "ineligible":
                displayed_results.append(result)
        for refill_result in displayed_results:
            self._row_flush_new_wine_refill_result(refill_result, refill_table)
        if displayed_results:
            self._flush_new_wine_console.print(refill_table)
        mode = "no-discovery" if refill.no_discovery else "standard"
        self._flush_new_wine_console.print(
            (
                "Wine Cellar ("
                f"{mode}"
                "): New Wine "
                f"{refill.before}"
                " -> "
                f"{refill.after}"
                "; "
                f"{refill.added}"
                " added, "
                f"{refill.removed_from_cellar}"
                " removed from Wine Cellar, "
                f"{refill.ineligible}"
                " ineligible."
            ),
            style="bold cyan",
        )
