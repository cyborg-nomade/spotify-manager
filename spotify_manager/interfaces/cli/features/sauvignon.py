"""Explicit sauvignon CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Never

import typer
from rich.console import Console
from rich.progress import BarColumn
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
from spotify_manager.interfaces import sauvignon_operations as sauvignon
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class SauvignonCLI:
    """Execute and present sauvignon through explicit facade dependencies.

    Args:
        bar_column: Rich bar column constructor.
        create_console: Factory for console instances.
        create_lastfm: Factory for lastfm instances.
        create_progress: Factory for progress instances.
        prompt: Rich prompt implementation supplied by the facade.
        configuration: Original settings factory supplied by the facade.
        spinner_column: Rich spinner column constructor.
        create_table: Factory for table instances.
        create_text: Factory for text instances.
        text_column: Rich text column constructor.
        time_column: Rich time column constructor.
        ask_sauvignon_album: Original ask sauvignon album boundary supplied by the
            facade.
        print_sauvignon_table: Original print sauvignon table boundary supplied by the
            facade.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    bar_column: type[BarColumn]
    create_console: type[Console]
    create_lastfm: type[LastFmClient]
    create_progress: type[Progress]
    prompt: type[Prompt]
    configuration: type[Settings]
    spinner_column: type[SpinnerColumn]
    create_table: type[Table]
    create_text: type[Text]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    ask_sauvignon_album: Callable[..., str]
    print_sauvignon_table: Callable[..., None]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _render_sauvignon_table(
        self, console: Console, results: tuple[sauvignon.SauvignonResult, ...]
    ) -> None:
        """Render album-level Last.fm recommendations for Sauvignon.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        table = self.create_table(title="Fill Sauvignon Terre-Neuve from Last.fm")
        table.add_column("#", justify="right")
        table.add_column("Album")
        table.add_column("Recommendation")
        table.add_column("First track")
        table.add_column("Result")
        styles = {
            "added": "bold green",
            "would add": "bold cyan",
            "already represented": "yellow",
            "artist already selected": "yellow",
            "skipped": "yellow",
            "quit": "bold yellow",
        }
        for index, result in enumerate(results, start=1):
            recommendation = result.recommendation
            support_count = len(recommendation.supporting_tracks)
            recommendation_text = (
                "base #"
                f"{recommendation.base_rank}"
                "; weekly "
                f"{recommendation.weekly_rank:.3f}"
                "; score "
                f"{recommendation.score:.3f}"
                "; "
                f"{support_count}"
                " supporting track"
                f"{('s' if support_count != 1 else '')}"
            )
            if result.album is None:
                album_text = f"{recommendation.artist} - {recommendation.album}"
            else:
                album_text = (
                    f"{result.album.artist}"
                    " - "
                    f"{result.album.album}"
                    "\n"
                    f"{result.album.release_type}"
                    "; "
                    f"{result.album.release_date}"
                    "; "
                    f"{result.album.total_tracks}"
                    " tracks"
                )
            first_track = result.first_track.name if result.first_track else "-"
            table.add_row(
                str(index),
                album_text,
                recommendation_text,
                first_track,
                self.create_text(result.action, style=styles[result.action]),
            )
        console.print(table)

    def _prompt_sauvignon_album(
        self,
        console: Console,
        recommendation: sauvignon.AlbumRecommendation,
        options: tuple[sauvignon.SpotifyAlbumOption, ...],
        progress: Progress,
    ) -> str:
        """Prompt only when Spotify exposes materially different album editions.

        Args:
            console: Rich console receiving this command's output.
            recommendation: Recommendation supplied by the caller.
            options: Options supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        progress.stop()
        try:
            table = self.create_table(
                title=(
                    "Choose Sauvignon edition: "
                    f"{recommendation.artist}"
                    " - "
                    f"{recommendation.album}"
                )
            )
            table.add_column("#", justify="right")
            table.add_column("Release")
            table.add_column("Type")
            table.add_column("Date")
            table.add_column("Tracks", justify="right")
            table.add_column("Evidence track")
            table.add_column("Spotify id")
            for index, option in enumerate(options, start=1):
                table.add_row(
                    str(index),
                    option.album,
                    option.release_type,
                    option.release_date,
                    str(option.total_tracks),
                    option.source_track,
                    option.spotify_id,
                )
            console.print(table)
            response = self.prompt.ask(
                "Release number / [s]kip this run / [q]uit",
                choices=[
                    *(str(index) for index in range(1, len(options) + 1)),
                    "s",
                    "q",
                ],
                default="s",
                console=console,
            )
            if response == "s":
                return sauvignon.CHOICE_SKIP
            if response == "q":
                return sauvignon.CHOICE_QUIT
            return options[int(response) - 1].spotify_id
        finally:
            progress.start()

    def _run_fill_sauvignon_from_lastfm(
        self,
        count: int | None,
        max_playlist_length: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> None:
        """Recommend unheard albums from Last.fm and add them to Sauvignon.

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
        self._fill_sauvignon_from_lastfm_console = self.create_console()
        configuration = self.configuration()
        try:
            playlist_id = sauvignon.parse_playlist_id(
                configuration.sauvignon_terre_neuve_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (sauvignon.SauvignonConfigError, found_art.FoundArtConfigError) as exc:
            self._report_fill_sauvignon_from_lastfm_configuration_failure(exc)
        effective_maximum = (
            sauvignon.DEFAULT_MAX_PLAYLIST_LENGTH
            if count is None and max_playlist_length is None
            else max_playlist_length
        )
        lastfm_client = self.create_lastfm(
            api_key, username, event_callback=self._fill_sauvignon_from_lastfm_log
        )
        summary = self._execute_fill_sauvignon_from_lastfm(
            count, dry_run, effective_maximum, lastfm_client, playlist_id, seed_count
        )
        self._show_fill_sauvignon_from_lastfm(summary)

    def _fill_sauvignon_from_lastfm_echo(self, line: str = "") -> None:
        style = "bold green" if line.startswith("Added") else None
        self._fill_sauvignon_from_lastfm_console.print(line, style=style, markup=False)

    def _fill_sauvignon_from_lastfm_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._fill_sauvignon_from_lastfm_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _fill_sauvignon_from_lastfm_update_progress(self, status: str) -> None:
        self._fill_sauvignon_from_lastfm_progress.update(
            self._fill_sauvignon_from_lastfm_task_id, description=status
        )

    def _fill_sauvignon_from_lastfm_log(self, message: str) -> None:
        return self._fill_sauvignon_from_lastfm_console.print(message, style="yellow")

    def _fill_sauvignon_from_lastfm_ask_sauvignon_album(
        self,
        recommendation: sauvignon.AlbumRecommendation,
        options: tuple[sauvignon.SpotifyAlbumOption, ...],
    ) -> str:
        return self.ask_sauvignon_album(
            self._fill_sauvignon_from_lastfm_console,
            recommendation,
            options,
            self._fill_sauvignon_from_lastfm_progress,
        )

    def _report_fill_sauvignon_from_lastfm_configuration_failure(
        self, exc: sauvignon.SauvignonConfigError | found_art.FoundArtConfigError
    ) -> Never:
        self._fill_sauvignon_from_lastfm_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_sauvignon_from_lastfm_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._fill_sauvignon_from_lastfm_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_fill_sauvignon_from_lastfm_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._fill_sauvignon_from_lastfm_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_fill_sauvignon_from_lastfm_sauvignon_failure(
        self, exc: sauvignon.SauvignonError | found_art.FoundArtError | LastFmError
    ) -> Never:
        self._fill_sauvignon_from_lastfm_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_sauvignon_from_lastfm_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._fill_sauvignon_from_lastfm_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_sauvignon_from_lastfm_interrupted_interrupted(
        self, exc: KeyboardInterrupt
    ) -> Never:
        self._fill_sauvignon_from_lastfm_console.print(
            "Sauvignon fill stopped safely. Cached Last.fm calls remain saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _show_fill_sauvignon_from_lastfm(
        self, summary: sauvignon.SauvignonSummary
    ) -> None:
        self.print_sauvignon_table(
            self._fill_sauvignon_from_lastfm_console, summary.results
        )
        self._fill_sauvignon_from_lastfm_console.print(
            (
                "Listening week: "
                f"{summary.week_start.isoformat()}"
                " through "
                f"{(summary.week_start + timedelta(days=6)).isoformat()}"
            ),
            style="bold cyan",
        )
        prefix = "Dry run" if summary.dry_run else "Fill"
        self._fill_sauvignon_from_lastfm_console.print(
            (
                f"{prefix}"
                ": "
                f"{summary.history_scrobbles:,}"
                " scrobbles across "
                f"{summary.history_albums:,}"
                " albums; "
                f"{summary.seed_count}"
                " seeds, "
                f"{summary.track_candidate_count:,}"
                " track candidates, "
                f"{summary.album_candidate_count:,}"
                " eligible albums; Sauvignon "
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
            self._fill_sauvignon_from_lastfm_console.print(
                "Sauvignon fill paused; rerun to continue.", style="bold yellow"
            )

    def _execute_fill_sauvignon_from_lastfm(
        self,
        count: int | None,
        dry_run: bool,
        effective_maximum: int | None,
        lastfm_client: LastFmClient,
        playlist_id: str,
        seed_count: int,
    ) -> sauvignon.SauvignonSummary:
        """Execute fill sauvignon from lastfm.

        Args:
            count: Count supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
            effective_maximum: Effective maximum supplied by the caller.
            lastfm_client: Lastfm client supplied by the caller.
            playlist_id: Playlist id supplied by the caller.
            seed_count: Seed count supplied by the caller.

        Returns:
            The routine outcome.
        """
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.time_column(),
                console=self._fill_sauvignon_from_lastfm_console,
                transient=True,
            ) as self._fill_sauvignon_from_lastfm_progress:
                progress_ref = self._fill_sauvignon_from_lastfm_progress
                description = progress_description(
                    "Building Last.fm album recommendations", dry_run
                )
                self._fill_sauvignon_from_lastfm_task_id = (
                    self._fill_sauvignon_from_lastfm_progress.add_task(
                        description, total=None
                    )
                )
                summary = sauvignon.fill_sauvignon_from_lastfm(
                    self.review_client(),
                    lastfm_client,
                    playlist_id,
                    choice_reader=self._fill_sauvignon_from_lastfm_ask_sauvignon_album,
                    count=count,
                    max_playlist_length=effective_maximum,
                    seed_count=seed_count,
                    dry_run=dry_run,
                    echo=self._fill_sauvignon_from_lastfm_echo,
                    progress_callback=self._fill_sauvignon_from_lastfm_update_progress,
                    retry_call=self._fill_sauvignon_from_lastfm_retry_call,
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_fill_sauvignon_from_lastfm_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_fill_sauvignon_from_lastfm_server_failure(exc)
        except (sauvignon.SauvignonError, found_art.FoundArtError, LastFmError) as exc:
            self._report_fill_sauvignon_from_lastfm_sauvignon_failure(exc)
        except SpotifyException as exc:
            self._report_fill_sauvignon_from_lastfm_spotify_spotify_failure(exc)
        except KeyboardInterrupt as exc:
            self._report_fill_sauvignon_from_lastfm_interrupted_interrupted(exc)
        finally:
            if progress_ref is not None:
                progress_ref.stop()
        return summary
