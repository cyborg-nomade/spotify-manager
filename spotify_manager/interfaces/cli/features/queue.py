"""Explicit queue CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
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
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.routines import found_art
from spotify_manager.routines import release_check
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import the_queue
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class QueueCLI:
    """Execute and present queue through explicit facade dependencies.

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
        ask_queue_artist: Original ask queue artist boundary supplied by the facade.
        configured_queue_playlists: Configured queue playlists supplied by the caller.
        print_queue_fill_table: Original print queue fill table boundary supplied by the
            facade.
        print_queue_flush_table: Original print queue flush table boundary supplied by
            the facade.
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
    ask_queue_artist: Callable[..., str]
    configured_queue_playlists: Callable[..., the_queue.QueuePlaylists]
    print_queue_fill_table: Callable[..., None]
    print_queue_flush_table: Callable[..., None]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _render_queue_fill_table(
        self, console: Console, results: tuple[the_queue.FillResult, ...]
    ) -> None:
        """Render Last.fm artist recommendations resolved for The Queue.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        table = self.create_table(title="Fill The Queue from Last.fm")
        table.add_column("#", justify="right")
        table.add_column("Last.fm artist")
        table.add_column("Recommendation")
        table.add_column("Spotify selection")
        table.add_column("Result")
        styles = {
            "added": "bold green",
            "would add": "bold cyan",
            "already represented": "yellow",
            "no Spotify match": "bold red",
            "no unliked top track": "magenta",
            "skipped": "yellow",
        }
        for index, result in enumerate(results, start=1):
            recommendation = result.recommendation
            detail = (
                "base #"
                f"{recommendation.base_rank}"
                "; weekly "
                f"{recommendation.weekly_rank:.3f}"
                "; score "
                f"{recommendation.score:.3f}"
                "; "
                f"{len(recommendation.supporting_seeds)}"
                " seeds"
            )
            if result.spotify_artist is None:
                selection = "No Spotify mapping"
            elif result.track is None:
                selection = result.spotify_artist.name
            else:
                follow_note = " · follow" if result.followed else ""
                selection = (
                    f"{result.spotify_artist.name} - {result.track.name}{follow_note}"
                )
            table.add_row(
                str(index),
                recommendation.artist,
                detail,
                selection,
                self.create_text(result.action, style=styles[result.action]),
            )
        console.print(table)

    def _render_queue_flush_table(
        self, console: Console, results: tuple[the_queue.FlushResult, ...]
    ) -> None:
        """Render Queue top-track transitions and live-like decisions.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        table = self.create_table(title="Flush The Queue")
        table.add_column("Artist")
        table.add_column("Current")
        table.add_column("Likes", justify="right")
        table.add_column("Action")
        table.add_column("Target")
        table.add_column("Reason")
        styles = {
            "advance": "cyan",
            "promote": "bold green",
            "unlucky": "yellow",
            "unfollow": "bold red",
            "blocked": "bold magenta",
        }
        for result in results:
            target = result.target_track or "-"
            if result.target_release:
                target += f" · {result.target_release}"
            table.add_row(
                result.artist,
                result.source_track,
                (
                    "top "
                    f"{result.top_liked_tracks}"
                    "/"
                    f"{result.top_tracks}"
                    "; total "
                    f"{result.total_liked_tracks}"
                ),
                self.create_text(result.action, style=styles[result.action]),
                target,
                result.reason or ("-"),
            )
        console.print(table)

    def _prompt_queue_artist(
        self,
        console: Console,
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
        progress: Progress,
    ) -> str:
        """Prompt for an ambiguous Last.fm Queue artist mapping.

        Args:
            console: Rich console receiving this command's output.
            recommendation: Recommendation supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        progress.stop()
        try:
            return self._read_queue_artist(
                console, recommendation, candidates, progress
            )
        finally:
            progress.start()

    def _configured_queue_playlists(
        self, configuration: Settings
    ) -> the_queue.QueuePlaylists:
        """Parse every playlist used by The Queue's fill and flush commands.

        Args:
            configuration: Original settings factory supplied by the facade.

        Returns:
            The original value selected or formatted by this adapter.
        """
        return the_queue.QueuePlaylists.from_references(
            configuration.the_queue_playlist,
            configuration.the_queue_2_playlist,
            configuration.new_kids_on_the_block_playlist,
            configuration.the_queue_3_playlist,
            configuration.unlucky_ones_playlist,
        )

    def _run_fill_queue_from_lastfm(
        self,
        count: int | None,
        max_playlist_length: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> None:
        """Recommend unheard artists from Last.fm and add them to The Queue.

        Args:
            count: Count supplied by the caller.
            max_playlist_length: Max playlist length supplied by the caller.
            seed_count: Seed count supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        if count is not None and max_playlist_length is not None:
            raise typer.BadParameter(
                "use either --count or --max-playlist-length, not both"
            )
        self._fill_queue_from_lastfm_console = self.create_console()
        configuration = self.configuration()
        try:
            playlists = self.configured_queue_playlists(configuration)
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (the_queue.QueueConfigError, found_art.FoundArtConfigError) as exc:
            self._report_fill_queue_from_lastfm_configuration_failure(exc)
        effective_count = (
            the_queue.DEFAULT_COUNT
            if count is None and max_playlist_length is None
            else count
        )
        lastfm_client = self.create_lastfm(
            api_key, username, event_callback=self._fill_queue_from_lastfm_log
        )
        summary = self._execute_fill_queue_from_lastfm(
            dry_run,
            effective_count,
            lastfm_client,
            max_playlist_length,
            playlists,
            seed_count,
        )
        self._show_fill_queue_from_lastfm(summary)

    def _fill_queue_from_lastfm_echo(self, line: str = "") -> None:
        style = None
        if line.startswith(("Added", "Recorded", "Updated")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        self._fill_queue_from_lastfm_console.print(line, style=style, markup=False)

    def _fill_queue_from_lastfm_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._fill_queue_from_lastfm_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _fill_queue_from_lastfm_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._fill_queue_from_lastfm_progress.update(
            self._fill_queue_from_lastfm_task_id,
            completed=completed,
            total=max(completed, total) or None,
            description=status,
        )

    def _fill_queue_from_lastfm_log(self, message: str) -> None:
        return self._fill_queue_from_lastfm_console.print(message, style="yellow")

    def _fill_queue_from_lastfm_ask_queue_artist(
        self,
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        return self.ask_queue_artist(
            self._fill_queue_from_lastfm_console,
            recommendation,
            candidates,
            self._fill_queue_from_lastfm_progress,
        )

    def _run_flush_queue(self, dry_run: bool) -> None:
        """Advance the first ten Queue artists through Spotify's top tracks.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_queue_console = self.create_console()
        try:
            playlists = self.configured_queue_playlists(self.configuration())
        except the_queue.QueueConfigError as exc:
            self._report_flush_queue_configuration_failure(exc)
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._flush_queue_console,
                transient=True,
            ) as self._flush_queue_progress:
                progress_ref = self._flush_queue_progress
                description = progress_description("Planning The Queue flush", dry_run)
                self._flush_queue_task_id = self._flush_queue_progress.add_task(
                    description, total=None
                )
                summary = the_queue.flush_queue(
                    self.review_client(),
                    playlists,
                    dry_run=dry_run,
                    echo=self._flush_queue_echo,
                    progress_callback=self._flush_queue_update_progress,
                    retry_call=self._flush_queue_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_queue_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_queue_server_failure(exc)
        except the_queue.QueueError as exc:
            self._report_flush_queue_queue_failure(exc)
        except SpotifyException as exc:
            self._report_flush_queue_spotify_spotify_failure(exc)
        except KeyboardInterrupt as exc:
            self._report_flush_queue_interrupted_interrupted(exc)
        finally:
            if progress_ref is not None:
                progress_ref.stop()
        self._show_flush_queue(summary)

    def _flush_queue_echo(self, line: str = "") -> None:
        """Flush queue echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith(("Advanced", "Promoted", "Added")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("Unfollowed"):
            style = "bold red"
        self._flush_queue_console.print(line, style=style, markup=False)

    def _flush_queue_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._flush_queue_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _flush_queue_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._flush_queue_progress.update(
            self._flush_queue_task_id,
            completed=completed,
            total=max(completed, total),
            description=status,
        )

    def _report_flush_queue_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._flush_queue_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        self._flush_queue_console.print(
            "The active Queue flush was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._flush_queue_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._flush_queue_console.print(
            "The active Queue flush was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._flush_queue_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        self._flush_queue_console.print(
            "The active Queue flush was saved and can be resumed.", style="yellow"
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_queue_from_lastfm_configuration_failure(
        self, exc: the_queue.QueueConfigError | found_art.FoundArtConfigError
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_queue_from_lastfm_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_fill_queue_from_lastfm_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_fill_queue_from_lastfm_queue_failure(
        self, exc: the_queue.QueueError | release_check.ReleaseCheckError | LastFmError
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_queue_from_lastfm_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_queue_from_lastfm_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            (
                "Queue fill stopped safely. Cached calls and "
                "completed additions remain saved."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_queue_configuration_failure(
        self, exc: the_queue.QueueConfigError
    ) -> Never:
        self._flush_queue_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_queue_failure(self, exc: the_queue.QueueError) -> Never:
        self._flush_queue_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_flush_queue_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._flush_queue_console.print(
            "Queue flush paused. The active run was saved.", style="bold yellow"
        )
        raise typer.Exit(code=0) from exc

    def _show_fill_queue_from_lastfm(self, summary: the_queue.FillSummary) -> None:
        self.print_queue_fill_table(
            self._fill_queue_from_lastfm_console, summary.results
        )
        self._fill_queue_from_lastfm_console.print(
            (
                "Listening week: "
                f"{summary.week_start.isoformat()}"
                " through "
                f"{(summary.week_start + timedelta(days=6)).isoformat()}"
            ),
            style="bold cyan",
        )
        prefix = "Dry run" if summary.dry_run else "Fill"
        self._fill_queue_from_lastfm_console.print(
            (
                f"{prefix}"
                ": "
                f"{summary.history_scrobbles:,}"
                " scrobbles across "
                f"{summary.history_artists:,}"
                " artists; "
                f"{summary.seed_count}"
                " seeds, "
                f"{summary.candidate_count:,}"
                " candidates; Queue "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "; selected "
                f"{summary.selected}"
                "/"
                f"{summary.requested_count}"
                "."
            ),
            style="bold",
        )
        if summary.paused:
            self._fill_queue_from_lastfm_console.print(
                "Queue fill paused; rerun to continue.", style="bold yellow"
            )

    def _show_flush_queue(self, summary: the_queue.FlushSummary) -> None:
        self.print_queue_flush_table(self._flush_queue_console, summary.results)
        prefix = "Dry run" if summary.dry_run else "Flush"
        self._flush_queue_console.print(
            (
                f"{prefix}"
                ": Queue "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "; processed "
                f"{summary.processed}"
                "/"
                f"{summary.total}"
                " artists."
            ),
            style="bold",
        )
        if summary.resumed:
            self._flush_queue_console.print(
                "Resumed the previously saved Queue flush.", style="cyan"
            )

    def _execute_fill_queue_from_lastfm(
        self,
        dry_run: bool,
        effective_count: int | None,
        lastfm_client: LastFmClient,
        max_playlist_length: int | None,
        playlists: the_queue.QueuePlaylists,
        seed_count: int,
    ) -> the_queue.FillSummary:
        """Execute fill queue from lastfm.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            effective_count: Effective count supplied by the caller.
            lastfm_client: Lastfm client supplied by the caller.
            max_playlist_length: Max playlist length supplied by the caller.
            playlists: Playlists supplied by the caller.
            seed_count: Seed count supplied by the caller.

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
                console=self._fill_queue_from_lastfm_console,
                transient=True,
            ) as self._fill_queue_from_lastfm_progress:
                progress_ref = self._fill_queue_from_lastfm_progress
                description = progress_description(
                    "Building Last.fm artist recommendations", dry_run
                )
                self._fill_queue_from_lastfm_task_id = (
                    self._fill_queue_from_lastfm_progress.add_task(
                        description, total=None
                    )
                )
                summary = the_queue.fill_queue_from_lastfm(
                    self.review_client(),
                    lastfm_client,
                    playlists,
                    choice_reader=self._fill_queue_from_lastfm_ask_queue_artist,
                    count=effective_count,
                    max_playlist_length=max_playlist_length,
                    seed_count=seed_count,
                    dry_run=dry_run,
                    echo=self._fill_queue_from_lastfm_echo,
                    progress_callback=self._fill_queue_from_lastfm_update_progress,
                    retry_call=self._fill_queue_from_lastfm_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_fill_queue_from_lastfm_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_fill_queue_from_lastfm_server_failure(exc)
        except (
            the_queue.QueueError,
            release_check.ReleaseCheckError,
            LastFmError,
        ) as exc:
            self._report_fill_queue_from_lastfm_queue_failure(exc)
        except SpotifyException as exc:
            self._report_fill_queue_from_lastfm_spotify_spotify_failure(exc)
        except KeyboardInterrupt as exc:
            self._report_fill_queue_from_lastfm_interrupted_interrupted(exc)
        finally:
            if progress_ref is not None:
                progress_ref.stop()
        return summary

    def _read_queue_artist(
        self,
        console: Console,
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
        progress: Progress,
    ) -> str:
        """Read queue artist.

        Args:
            console: Rich console receiving this command's output.
            recommendation: Recommendation supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        table = self.create_table(title=f"Map Queue artist: {recommendation.artist}")
        table.add_column("#", justify="right")
        table.add_column("Spotify artist")
        table.add_column("Exact")
        table.add_column("Popularity", justify="right")
        table.add_column("Followers", justify="right")
        table.add_column("Spotify id")
        if not candidates:
            console.print(
                (f"No Spotify artists matched {recommendation.artist}."),
                style="bold yellow",
            )
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                "yes" if candidate.exact_name else "no",
                str(candidate.popularity) if candidate.popularity is not None else "?",
                (f"{candidate.followers:,}")
                if candidate.followers is not None
                else "?",
                candidate.spotify_id,
                style=None if candidate.exact_name else "dim",
            )
        console.print(table)
        response = self.prompt.ask(
            "Artist number / [n]ew search / [s]kip this run / [q]uit",
            choices=[
                *(str(index) for index in range(1, len(candidates) + 1)),
                "n",
                "s",
                "q",
            ],
            default="s",
            console=console,
        )
        if response == "n":
            return self._read_artist_search(console)
        if response == "s":
            return the_queue.CHOICE_SKIP
        if response == "q":
            return the_queue.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id

    def _read_artist_search(self, console: Console) -> str:
        while True:
            search_text = self.prompt.ask("New Spotify artist search", console=console)
            if search_text.strip():
                return f"{the_queue.CHOICE_SEARCH_PREFIX}{search_text.strip()}"
            console.print("Search text cannot be empty.", style="bold yellow")
