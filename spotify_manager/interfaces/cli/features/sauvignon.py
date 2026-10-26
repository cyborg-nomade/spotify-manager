"""Explicit sauvignon CLI execution, prompts and presentation."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from typing import Never

import typer
from rich.console import Console
from rich.progress import Progress
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.runtime import Wait
from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client as create_lastfm_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces import sauvignon_operations as sauvignon
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.display import ProgressDisplay
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.requests.sauvignon import SauvignonCallbacks
from spotify_manager.interfaces.requests.sauvignon import SauvignonOptions
from spotify_manager.interfaces.requests.sauvignon import SauvignonResources


@dataclass(kw_only=True)
class SauvignonCLI:
    """Run Sauvignon recommendations with album choices and progress.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        progress_display: Rich console, table and live-status constructors.
        display: Rich console, table and live-status constructors.
        sleep: Bounded retry wait supplied by the interface.
    """

    runtime: CliResources

    progress_display: ProgressDisplay
    display: ConsoleDisplay
    sleep: Wait

    def _render_sauvignon_table(
        self, console: Console, results: tuple[sauvignon.SauvignonResult, ...]
    ) -> None:
        """Render album-level Last.fm recommendations for Sauvignon.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        table = self.display.create_table(
            title="Fill Sauvignon Terre-Neuve from Last.fm"
        )
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
                f"base #{recommendation.base_rank}; weekly "
                f"{recommendation.weekly_rank:.3f}; score "
                f"{recommendation.score:.3f}; {support_count} supporting track"
                f"{('s' if support_count != 1 else '')}"
            )
            if result.album is None:
                album_text = f"{recommendation.artist} - {recommendation.album}"
            else:
                album_text = (
                    f"{result.album.artist} - {result.album.album}\n"
                    f"{result.album.release_type}; {result.album.release_date}; "
                    f"{result.album.total_tracks} tracks"
                )
            first_track = result.first_track.name if result.first_track else "-"
            table.add_row(
                str(index),
                album_text,
                recommendation_text,
                first_track,
                self.display.create_text(result.action, style=styles[result.action]),
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
            table = self.display.create_table(
                title=(
                    f"Choose Sauvignon edition: {recommendation.artist} - "
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
            response = self.display.prompt.ask(
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
        self._fill_sauvignon_from_lastfm_console = self.display.create_console()
        configuration = self.runtime.configuration()
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
        lastfm_client = create_lastfm_client(
            LastFmCredentials(api_key, username),
            FillSauvignonFromLastfmDiagnostics(self),
        )
        summary = self._execute_fill_sauvignon_from_lastfm(
            count, dry_run, effective_maximum, lastfm_client, playlist_id, seed_count
        )
        self._show_fill_sauvignon_from_lastfm(summary)

    def _fill_sauvignon_from_lastfm_echo(self, line: str = "") -> None:
        style = "bold green" if line.startswith("Added") else None
        self._fill_sauvignon_from_lastfm_console.print(line, style=style, markup=False)

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
        return self._prompt_sauvignon_album(
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
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
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
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
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
        self._render_sauvignon_table(
            self._fill_sauvignon_from_lastfm_console, summary.results
        )
        self._fill_sauvignon_from_lastfm_console.print(
            (
                f"Listening week: {summary.week_start.isoformat()} through "
                f"{(summary.week_start + timedelta(days=6)).isoformat()}"
            ),
            style="bold cyan",
        )
        prefix = "Dry run" if summary.dry_run else "Fill"
        self._fill_sauvignon_from_lastfm_console.print(
            (
                f"{prefix}: {summary.history_scrobbles:,} scrobbles across "
                f"{summary.history_albums:,} albums; {summary.seed_count} seeds, "
                f"{summary.track_candidate_count:,} track candidates, "
                f"{summary.album_candidate_count:,} eligible albums; Sauvignon "
                f"{summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}; selected {summary.selected}/"
                f"{summary.requested_count}."
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
            with self.progress_display.create_progress(
                self.progress_display.spinner_column(),
                self.progress_display.text_column(
                    "[progress.description]{task.description}"
                ),
                self.progress_display.bar_column(),
                self.progress_display.time_column(),
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
                    self.runtime.review_client(),
                    lastfm_client,
                    SauvignonOptions(
                        playlist_id=playlist_id,
                        count=count,
                        max_playlist_length=effective_maximum,
                        seed_count=seed_count,
                        dry_run=dry_run,
                    ),
                    SauvignonCallbacks(
                        choice_reader=FillSauvignonFromLastfmInteraction(self),
                        output=FillSauvignonFromLastfmInteraction(self),
                        progress_callback=FillSauvignonFromLastfmInteraction(self),
                        retry_call=FillSauvignonFromLastfmInteraction(self),
                    ),
                    SauvignonResources(),
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


@dataclass(frozen=True)
class FillSauvignonFromLastfmInteraction:
    """Own the original terminal interaction resources.

    Args:
        owner: Command instance owning its console, progress and wait state.
    """

    owner: SauvignonCLI

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        return SpotifyRetries(self, self.owner.sleep, 10, 3).attempts(description)

    def echo(self, message: str) -> None:
        """Present the command's original message.

        Args:
            message: Complete original text.
        """
        self.owner._fill_sauvignon_from_lastfm_echo(message)

    def progress(self, status: str) -> None:
        """Present the command's original progress.

        Args:
            status: Original status.
        """
        self.owner._fill_sauvignon_from_lastfm_update_progress(status)

    def choose_album(
        self,
        recommendation: sauvignon.AlbumRecommendation,
        options: tuple[sauvignon.SpotifyAlbumOption, ...],
    ) -> str:
        """Use this command's fixed choose album prompt.

        Args:
            recommendation: Original operator prompt value.
            options: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return self.owner._fill_sauvignon_from_lastfm_ask_sauvignon_album(
            recommendation, options
        )


@dataclass(frozen=True)
class FillSauvignonFromLastfmDiagnostics:
    """Own the command's original presentation state.

    Args:
        owner: Existing command instance and its display resources.
    """

    owner: SauvignonCLI

    def echo(self, message: str) -> None:
        """Present the command's original diagnostic.

        Args:
            message: Original message.
        """
        self.owner._fill_sauvignon_from_lastfm_log(message)
