"""Explicit discovery CLI execution, prompts and presentation."""

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

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.routines import composer_playlists
from spotify_manager.routines import found_art
from spotify_manager.routines import new_kids
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import scrobble_history
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class DiscoveryCLI:
    """Execute and present discovery through explicit facade dependencies.

    Args:
        bar_column: Rich bar column constructor.
        create_console: Factory for console instances.
        create_lastfm: Factory for lastfm instances.
        complete_column: Rich complete column constructor.
        create_progress: Factory for progress instances.
        prompt: Rich prompt implementation supplied by the facade.
        configuration: Original settings factory supplied by the facade.
        spinner_column: Rich spinner column constructor.
        create_table: Factory for table instances.
        create_text: Factory for text instances.
        text_column: Rich text column constructor.
        time_column: Rich time column constructor.
        ask_new_kids_release_choice: Original ask new kids release choice boundary
            supplied by the facade.
        print_album_discovery_decisions: Original print album discovery decisions
            boundary supplied by the facade.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    bar_column: type[BarColumn]
    create_console: type[Console]
    create_lastfm: type[LastFmClient]
    complete_column: type[MofNCompleteColumn]
    create_progress: type[Progress]
    prompt: type[Prompt]
    configuration: type[Settings]
    spinner_column: type[SpinnerColumn]
    create_table: type[Table]
    create_text: type[Text]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    ask_new_kids_release_choice: Callable[..., str]
    print_album_discovery_decisions: Callable[..., None]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _prompt_new_kids_release_choice(
        self,
        console: Console,
        artist_name: str,
        candidates: tuple[new_kids.ChoiceCandidate, ...],
        progress: Progress | None,
    ) -> str:
        """Prompt for the next release or matching composer works playlist.

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
            return self._read_new_kids_release_choice(
                console, artist_name, candidates, progress
            )
        finally:
            if progress is not None:
                progress.start()

    def _render_album_discovery_decisions(
        self, console: Console, title: str, decisions: tuple[new_kids.FlushResult, ...]
    ) -> None:
        """Render shared New Kids and Queue 2 artist decisions.

        Args:
            console: Rich console receiving this command's output.
            title: Title supplied by the caller.
            decisions: Decisions supplied by the caller.
        """
        if not decisions:
            return
        table = self.create_table(title=title)
        table.add_column("Artist")
        table.add_column("Current")
        table.add_column("Release")
        table.add_column("Like")
        table.add_column("Streak", justify="right")
        table.add_column("Action")
        table.add_column("Next")
        action_styles = {
            "advance": "green",
            "next release": "cyan",
            "great discovery": "bold green",
            "unlucky": "yellow",
            "unfollowed": "bold red",
            "skip": "dim",
        }
        for decision in decisions:
            next_item = decision.target_track or "-"
            if (
                decision.target_release
                and decision.target_release != decision.source_release
            ):
                next_item = f"{decision.target_release} - {next_item}"
            table.add_row(
                decision.artist,
                decision.source_track,
                decision.source_release,
                "liked" if decision.current_liked else "unliked",
                str(decision.consecutive_unliked),
                self.create_text(decision.action, style=action_styles[decision.action]),
                next_item,
            )
        console.print(table)

    def _run_flush_new_kids(self, dry_run: bool) -> None:
        """Advance New Kids artists and refill the playlist from Queue 2.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_new_kids_console = self.create_console()
        self._flush_new_kids_progress_ref: Progress | None = None
        configuration = self.configuration()
        try:
            new_kids_playlist_id = new_kids.parse_playlist_id(
                configuration.new_kids_on_the_block_playlist,
                "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
            )
            queue_2_playlist_id = new_kids.parse_playlist_id(
                configuration.the_queue_2_playlist, "THE_QUEUE_2_PLAYLIST"
            )
            great_discoveries_playlist_id = new_kids.parse_playlist_id(
                configuration.great_discoveries_2026_playlist,
                "GREAT_DISCOVERIES_2026_PLAYLIST",
            )
            unlucky_ones_playlist_id = new_kids.parse_playlist_id(
                configuration.unlucky_ones_playlist, "UNLUCKY_ONES_PLAYLIST"
            )
            newfoundland_playlist_id = new_kids.parse_playlist_id(
                configuration.discography_newfoundland_playlist,
                "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
            )
            lastfm_api_key, lastfm_username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (new_kids.NewKidsConfigError, found_art.FoundArtConfigError) as exc:
            self._report_flush_new_kids_configuration_failure(exc)
        lastfm_client = self.create_lastfm(
            lastfm_api_key, lastfm_username, event_callback=self._flush_new_kids_log
        )
        summary = self._execute_flush_new_kids(
            dry_run,
            great_discoveries_playlist_id,
            lastfm_client,
            lastfm_username,
            new_kids_playlist_id,
            newfoundland_playlist_id,
            queue_2_playlist_id,
            unlucky_ones_playlist_id,
        )
        self._show_flush_new_kids(summary)

    def _flush_new_kids_echo(self, line: str = "") -> None:
        """Flush new kids echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith(("Added", "Moved", "Removed", "Saved", "Reconciled")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith(("Unfollowed", "Unsaved")):
            style = "bold red"
        elif "resum" in line.casefold():
            style = "cyan"
        self._flush_new_kids_console.print(line, style=style, markup=False)

    def _flush_new_kids_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_new_kids_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _flush_new_kids_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._flush_new_kids_progress.update(
            self._flush_new_kids_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _flush_new_kids_log(self, message: str) -> None:
        return self._flush_new_kids_console.print(message, style="yellow")

    def _flush_new_kids_ask_new_kids_release_choice(
        self, artist: str, candidates: tuple[new_kids.ChoiceCandidate, ...]
    ) -> str:
        return self.ask_new_kids_release_choice(
            self._flush_new_kids_console,
            artist,
            candidates,
            self._flush_new_kids_progress_ref,
        )

    def _run_flush_queue_2(self, dry_run: bool) -> None:
        """Fill New Kids, then advance the first ten Queue 2 artists.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_queue_2_console = self.create_console()
        self._flush_queue_2_progress_ref: Progress | None = None
        configuration = self.configuration()
        try:
            new_kids_playlist_id = new_kids.parse_playlist_id(
                configuration.new_kids_on_the_block_playlist,
                "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
            )
            queue_2_playlist_id = new_kids.parse_playlist_id(
                configuration.the_queue_2_playlist, "THE_QUEUE_2_PLAYLIST"
            )
            great_discoveries_playlist_id = new_kids.parse_playlist_id(
                configuration.great_discoveries_2026_playlist,
                "GREAT_DISCOVERIES_2026_PLAYLIST",
            )
            unlucky_ones_playlist_id = new_kids.parse_playlist_id(
                configuration.unlucky_ones_playlist, "UNLUCKY_ONES_PLAYLIST"
            )
            newfoundland_playlist_id = new_kids.parse_playlist_id(
                configuration.discography_newfoundland_playlist,
                "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
            )
            lastfm_api_key, lastfm_username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (new_kids.NewKidsConfigError, found_art.FoundArtConfigError) as exc:
            self._report_flush_queue_2_configuration_failure(exc)
        lastfm_client = self.create_lastfm(
            lastfm_api_key, lastfm_username, event_callback=self._flush_queue_2_log
        )
        summary = self._execute_flush_queue(
            dry_run,
            great_discoveries_playlist_id,
            lastfm_client,
            lastfm_username,
            new_kids_playlist_id,
            newfoundland_playlist_id,
            queue_2_playlist_id,
            unlucky_ones_playlist_id,
        )
        self._show_flush_queue(summary)

    def _flush_queue_2_echo(self, line: str = "") -> None:
        """Flush queue 2 echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith(("Added", "Moved", "Removed", "Saved", "Reconciled")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith(("Unfollowed", "Unsaved")):
            style = "bold red"
        elif "resum" in line.casefold():
            style = "cyan"
        self._flush_queue_2_console.print(line, style=style, markup=False)

    def _flush_queue_2_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_queue_2_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _flush_queue_2_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._flush_queue_2_progress.update(
            self._flush_queue_2_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _flush_queue_2_log(self, message: str) -> None:
        return self._flush_queue_2_console.print(message, style="yellow")

    def _flush_queue_2_ask_new_kids_release_choice(
        self, artist: str, candidates: tuple[new_kids.ChoiceCandidate, ...]
    ) -> str:
        return self.ask_new_kids_release_choice(
            self._flush_queue_2_console,
            artist,
            candidates,
            self._flush_queue_2_progress_ref,
        )

    def _report_flush_new_kids_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError, dry_run: bool
    ) -> Never:
        self._flush_new_kids_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        if not dry_run:
            self._flush_new_kids_console.print(
                "The active New Kids run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc

    def _report_flush_new_kids_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError, dry_run: bool
    ) -> Never:
        self._flush_new_kids_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        if not dry_run:
            self._flush_new_kids_console.print(
                "The active New Kids run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc

    def _report_flush_new_kids_spotify_spotify_failure(
        self, exc: SpotifyException, dry_run: bool
    ) -> Never:
        self._flush_new_kids_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        if not dry_run:
            self._flush_new_kids_console.print(
                "The active New Kids run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_2_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError, dry_run: bool
    ) -> Never:
        self._flush_queue_2_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        if not dry_run:
            self._flush_queue_2_console.print(
                "The active Queue 2 run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_2_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError, dry_run: bool
    ) -> Never:
        self._flush_queue_2_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        if not dry_run:
            self._flush_queue_2_console.print(
                "The active Queue 2 run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_2_spotify_spotify_failure(
        self, exc: SpotifyException, dry_run: bool
    ) -> Never:
        self._flush_queue_2_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        if not dry_run:
            self._flush_queue_2_console.print(
                "The active Queue 2 run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc

    def _report_flush_new_kids_configuration_failure(
        self, exc: new_kids.NewKidsConfigError | found_art.FoundArtConfigError
    ) -> Never:
        self._flush_new_kids_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_new_kids_history_failure(
        self, exc: scrobble_history.ScrobbleHistoryError | LastFmError
    ) -> Never:
        self._flush_new_kids_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_new_kids_new_kids_failure(
        self, exc: new_kids.NewKidsError
    ) -> Never:
        self._flush_new_kids_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_new_kids_interrupted_interrupted(
        self, exc: KeyboardInterrupt, dry_run: bool
    ) -> Never:
        if not dry_run:
            self._flush_new_kids_console.print(
                "New Kids flush paused. The active run was saved.",
                style="bold yellow",
            )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_2_configuration_failure(
        self, exc: new_kids.NewKidsConfigError | found_art.FoundArtConfigError
    ) -> Never:
        self._flush_queue_2_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_2_history_failure(
        self, exc: scrobble_history.ScrobbleHistoryError | LastFmError
    ) -> Never:
        self._flush_queue_2_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_2_new_kids_failure(
        self, exc: new_kids.NewKidsError
    ) -> Never:
        self._flush_queue_2_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_2_interrupted_interrupted(
        self, exc: KeyboardInterrupt, dry_run: bool
    ) -> Never:
        if not dry_run:
            self._flush_queue_2_console.print(
                "Queue 2 flush paused. The active run was saved.",
                style="bold yellow",
            )
        raise typer.Exit(code=0) from exc

    def _show_flush_new_kids(self, summary: new_kids.FlushSummary) -> None:
        """Show flush new kids.

        Args:
            summary: Completed routine outcome to render.
        """
        self.print_album_discovery_decisions(
            self._flush_new_kids_console, "New Kids on the Block", summary.results
        )
        transfers = self._transfer_stages(summary)
        if transfers:
            transfer_table = self.create_table(title="Queue 2 transfer")
            transfer_table.add_column("Stage")
            transfer_table.add_column("Artist")
            transfer_table.add_column("Track")
            transfer_table.add_column("Action")
            for stage, transfer in transfers:
                transfer_table.add_row(
                    stage, transfer.artist, transfer.track, transfer.action
                )
            self._flush_new_kids_console.print(transfer_table)
        prefix = "Dry run" if summary.dry_run else "Flush"
        self._flush_new_kids_console.print(
            (
                f"{prefix}"
                ": New Kids "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "; "
                f"{len(summary.results)}"
                " decisions, "
                f"{len(summary.prefill) + len(summary.postfill)}"
                " Queue 2 transfers."
            ),
            style="bold",
        )
        if summary.resumed:
            self._flush_new_kids_console.print(
                "Resumed the previously saved flush.", style="cyan"
            )
        if summary.paused:
            self._flush_new_kids_console.print(
                "Flush paused; run the command again to resume.",
                style="bold yellow",
            )

    def _show_flush_queue(self, summary: new_kids.Queue2Summary) -> None:
        """Show flush queue.

        Args:
            summary: Completed routine outcome to render.
        """
        self.print_album_discovery_decisions(
            self._flush_queue_2_console, "The Queue 2", summary.results
        )
        if summary.prefill:
            transfer_table = self.create_table(title="New Kids prefill")
            transfer_table.add_column("Artist")
            transfer_table.add_column("Track")
            transfer_table.add_column("Action")
            for transfer in summary.prefill:
                transfer_table.add_row(transfer.artist, transfer.track, transfer.action)
            self._flush_queue_2_console.print(transfer_table)
        prefix = "Dry run" if summary.dry_run else "Flush"
        self._flush_queue_2_console.print(
            (
                f"{prefix}"
                ": New Kids "
                f"{summary.new_kids_length_before}"
                " -> "
                f"{summary.new_kids_length_after}"
                "; Queue 2 "
                f"{summary.queue_length_before}"
                " -> "
                f"{summary.queue_length_after}"
                "; "
                f"{len(summary.results)}"
                " decisions, "
                f"{len(summary.prefill)}"
                " transfers."
            ),
            style="bold",
        )
        if summary.resumed:
            self._flush_queue_2_console.print(
                "Resumed the previously saved Queue 2 flush.", style="cyan"
            )
        if summary.paused:
            self._flush_queue_2_console.print(
                "Flush paused; run the command again to resume.",
                style="bold yellow",
            )

    def _execute_flush_new_kids(
        self,
        dry_run: bool,
        great_discoveries_playlist_id: str,
        lastfm_client: LastFmClient,
        lastfm_username: str,
        new_kids_playlist_id: str,
        newfoundland_playlist_id: str,
        queue_2_playlist_id: str,
        unlucky_ones_playlist_id: str,
    ) -> new_kids.FlushSummary:
        """Execute flush new kids.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            great_discoveries_playlist_id: Great discoveries playlist id supplied by the
                caller.
            lastfm_client: Lastfm client supplied by the caller.
            lastfm_username: Lastfm username supplied by the caller.
            new_kids_playlist_id: New kids playlist id supplied by the caller.
            newfoundland_playlist_id: Newfoundland playlist id supplied by the caller.
            queue_2_playlist_id: Queue 2 playlist id supplied by the caller.
            unlucky_ones_playlist_id: Unlucky ones playlist id supplied by the caller.

        Returns:
            The routine outcome.
        """
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._flush_new_kids_console,
                transient=True,
            ) as self._flush_new_kids_progress:
                self._flush_new_kids_progress_ref = self._flush_new_kids_progress
                description = progress_description("Planning New Kids flush", dry_run)
                self._flush_new_kids_task_id = self._flush_new_kids_progress.add_task(
                    description, total=None
                )
                summary = new_kids.flush_new_kids(
                    self.review_client(),
                    new_kids_playlist_id,
                    queue_2_playlist_id,
                    great_discoveries_playlist_id,
                    unlucky_ones_playlist_id,
                    newfoundland_playlist_id,
                    choice_reader=self._flush_new_kids_ask_new_kids_release_choice,
                    dry_run=dry_run,
                    echo=self._flush_new_kids_echo,
                    progress_callback=self._flush_new_kids_update_progress,
                    retry_call=self._flush_new_kids_retry_call,
                    lastfm=lastfm_client,
                    lastfm_username=lastfm_username,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_new_kids_rate_limit(exc, dry_run)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_new_kids_server_failure(exc, dry_run)
        except (scrobble_history.ScrobbleHistoryError, LastFmError) as exc:
            self._report_flush_new_kids_history_failure(exc)
        except new_kids.NewKidsError as exc:
            self._report_flush_new_kids_new_kids_failure(exc)
        except SpotifyException as exc:
            self._report_flush_new_kids_spotify_spotify_failure(exc, dry_run)
        except KeyboardInterrupt as exc:
            self._report_flush_new_kids_interrupted_interrupted(exc, dry_run)
        return summary

    def _execute_flush_queue(
        self,
        dry_run: bool,
        great_discoveries_playlist_id: str,
        lastfm_client: LastFmClient,
        lastfm_username: str,
        new_kids_playlist_id: str,
        newfoundland_playlist_id: str,
        queue_2_playlist_id: str,
        unlucky_ones_playlist_id: str,
    ) -> new_kids.Queue2Summary:
        """Execute flush queue.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            great_discoveries_playlist_id: Great discoveries playlist id supplied by the
                caller.
            lastfm_client: Lastfm client supplied by the caller.
            lastfm_username: Lastfm username supplied by the caller.
            new_kids_playlist_id: New kids playlist id supplied by the caller.
            newfoundland_playlist_id: Newfoundland playlist id supplied by the caller.
            queue_2_playlist_id: Queue 2 playlist id supplied by the caller.
            unlucky_ones_playlist_id: Unlucky ones playlist id supplied by the caller.

        Returns:
            The routine outcome.
        """
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._flush_queue_2_console,
                transient=True,
            ) as self._flush_queue_2_progress:
                self._flush_queue_2_progress_ref = self._flush_queue_2_progress
                description = progress_description("Planning Queue 2 flush", dry_run)
                self._flush_queue_2_task_id = self._flush_queue_2_progress.add_task(
                    description, total=None
                )
                summary = new_kids.flush_queue_2(
                    self.review_client(),
                    new_kids_playlist_id,
                    queue_2_playlist_id,
                    great_discoveries_playlist_id,
                    unlucky_ones_playlist_id,
                    newfoundland_playlist_id,
                    choice_reader=self._flush_queue_2_ask_new_kids_release_choice,
                    dry_run=dry_run,
                    echo=self._flush_queue_2_echo,
                    progress_callback=self._flush_queue_2_update_progress,
                    retry_call=self._flush_queue_2_retry_call,
                    lastfm=lastfm_client,
                    lastfm_username=lastfm_username,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_queue_2_rate_limit(exc, dry_run)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_queue_2_server_failure(exc, dry_run)
        except (scrobble_history.ScrobbleHistoryError, LastFmError) as exc:
            self._report_flush_queue_2_history_failure(exc)
        except new_kids.NewKidsError as exc:
            self._report_flush_queue_2_new_kids_failure(exc)
        except SpotifyException as exc:
            self._report_flush_queue_2_spotify_spotify_failure(exc, dry_run)
        except KeyboardInterrupt as exc:
            self._report_flush_queue_2_interrupted_interrupted(exc, dry_run)
        return summary

    def _read_new_kids_release_choice(
        self,
        console: Console,
        artist_name: str,
        candidates: tuple[new_kids.ChoiceCandidate, ...],
        progress: Progress | None,
    ) -> str:
        """Read new kids release choice.

        Args:
            console: Rich console receiving this command's output.
            artist_name: Artist name supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        table = self.create_table(title=f"Choose the next release for {artist_name}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_column("Popularity", justify="right")
        table.add_column("Top track", justify="right")
        table.add_column("Saved")
        for index, candidate in enumerate(candidates, start=1):
            self._row_new_kids_release_choice_candidate(candidate, index, table)
        console.print(table)
        choices = [str(index) for index in range(1, len(candidates) + 1)]
        response = self.prompt.ask(
            "Release number / [s]kip this run / [q]uit",
            choices=[*choices, "s", "q"],
            console=console,
        )
        if response == "s":
            return new_kids.CHOICE_SKIP
        if response == "q":
            return new_kids.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id

    def _row_new_kids_release_choice_candidate(
        self, candidate: RankedRelease | OwnedPlaylist, index: int, table: Table
    ) -> None:
        """Row new kids release choice candidate.

        Args:
            candidate: Candidate supplied by the caller.
            index: Index supplied by the caller.
            table: Table receiving the original row values.
        """
        if isinstance(candidate, composer_playlists.OwnedPlaylist):
            release_type = "Composer works playlist"
            release_date = "Stored order"
            popularity = "-"
            top_track = "-"
            saved = "-"
        else:
            release_type = candidate.release_type
            release_date = candidate.release_date
            popularity = (
                str(candidate.popularity) if candidate.popularity is not None else "-"
            )
            top_track = (
                (f"#{candidate.top_track_rank}")
                if candidate.top_track_rank is not None
                else "-"
            )
            saved = "yes" if candidate.saved else "-"
        table.add_row(
            str(index),
            candidate.name,
            release_type,
            release_date,
            str(candidate.total_tracks),
            popularity,
            top_track,
            saved,
        )

    def _transfer_stages(
        self, summary: new_kids.FlushSummary
    ) -> list[tuple[str, new_kids.FillResult]]:
        transfers = []
        for transfer in summary.prefill:
            transfers.append(("Before", transfer))
        for transfer in summary.postfill:
            transfers.append(("After", transfer))
        return transfers
