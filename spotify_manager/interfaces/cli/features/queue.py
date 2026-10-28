"""Explicit queue CLI execution, prompts and presentation."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
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
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.infrastructure.cli_cancellation import CliInterruptedError
from spotify_manager.infrastructure.cli_cancellation import check_cli_interruption
from spotify_manager.infrastructure.lastfm_async import (
    AsyncLastFmClient as LastFmClient,
)
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.display import ProgressDisplay
from spotify_manager.interfaces.cli.presentation import progress_description
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.cli.terminal import TerminalPrompt
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import the_queue as the_queue
from spotify_manager.interfaces.requests.queue_fill import QueueFillCallbacks
from spotify_manager.interfaces.requests.queue_fill import QueueFillOptions
from spotify_manager.interfaces.requests.queue_fill import QueueFillResources
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class QueueCLI:
    """Run queue recommendation and review commands with terminal interaction.

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

    def _render_queue_fill_table(
        self, console: Console, results: tuple[the_queue.FillResult, ...]
    ) -> None:
        """Render Last.fm artist recommendations resolved for The Queue.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        table = self.display.create_table(title="Fill The Queue from Last.fm")
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
                f"base #{recommendation.base_rank}; weekly "
                f"{recommendation.weekly_rank:.3f}; score "
                f"{recommendation.score:.3f}; "
                f"{len(recommendation.supporting_seeds)} seeds"
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
                self.display.create_text(result.action, style=styles[result.action]),
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
        table = self.display.create_table(title="Flush The Queue")
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
                    f"top {result.top_liked_tracks}/{result.top_tracks}; total "
                    f"{result.total_liked_tracks}"
                ),
                self.display.create_text(result.action, style=styles[result.action]),
                target,
                result.reason or "-",
            )
        console.print(table)

    async def _prompt_queue_artist(
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
            return await self._read_queue_artist(
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

    async def _run_fill_queue_from_lastfm(
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
        self._fill_queue_from_lastfm_console = self.display.create_console()
        configuration = await self.runtime.configuration()
        try:
            playlists = self._configured_queue_playlists(configuration)
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
        lastfm_client = create_lastfm_client(
            LastFmCredentials(api_key, username), FillQueueFromLastfmDiagnostics(self)
        )
        summary = await self._execute_fill_queue_from_lastfm(
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

    async def _fill_queue_from_lastfm_ask_queue_artist(
        self,
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        return await self._prompt_queue_artist(
            self._fill_queue_from_lastfm_console,
            recommendation,
            candidates,
            self._fill_queue_from_lastfm_progress,
        )

    async def _run_flush_queue(self, dry_run: bool) -> None:
        """Advance the first ten Queue artists through Spotify's top tracks.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_queue_console = self.display.create_console()
        try:
            playlists = self._configured_queue_playlists(
                await self.runtime.configuration()
            )
        except the_queue.QueueConfigError as exc:
            self._report_flush_queue_configuration_failure(exc)
        try:
            with self.progress_display.create_progress(
                self.progress_display.spinner_column(),
                self.progress_display.text_column(
                    "[progress.description]{task.description}"
                ),
                self.progress_display.bar_column(),
                self.progress_display.complete_column(),
                self.progress_display.time_column(),
                console=self._flush_queue_console,
                transient=True,
            ) as self._flush_queue_progress:
                progress_ref = self._flush_queue_progress
                description = progress_description("Planning The Queue flush", dry_run)
                self._flush_queue_task_id = self._flush_queue_progress.add_task(
                    description, total=None
                )
                summary = await the_queue.flush_queue(
                    (await self.runtime.review_client()),
                    playlists,
                    dry_run=dry_run,
                    echo=FlushQueueInteraction(self),
                    progress_callback=FlushQueueInteraction(self),
                    retry_call=FlushQueueInteraction(self),
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_queue_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_queue_server_failure(exc)
        except the_queue.QueueError as exc:
            self._report_flush_queue_queue_failure(exc)
        except SpotifyException as exc:
            self._report_flush_queue_spotify_spotify_failure(exc)
        except (KeyboardInterrupt, CliInterruptedError) as exc:
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
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
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
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
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
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
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
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_queue_from_lastfm_interrupted_interrupted(
        self, exc: KeyboardInterrupt | CliInterruptedError
    ) -> Never:
        self._fill_queue_from_lastfm_console.print(
            (
                "Queue fill stopped safely. Cached calls and comp"
                "leted additions remain saved."
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
        self, exc: KeyboardInterrupt | CliInterruptedError
    ) -> Never:
        self._flush_queue_console.print(
            "Queue flush paused. The active run was saved.", style="bold yellow"
        )
        raise typer.Exit(code=0) from exc

    def _show_fill_queue_from_lastfm(self, summary: the_queue.FillSummary) -> None:
        self._render_queue_fill_table(
            self._fill_queue_from_lastfm_console, summary.results
        )
        self._fill_queue_from_lastfm_console.print(
            (
                f"Listening week: {summary.week_start.isoformat()} through "
                f"{(summary.week_start + timedelta(days=6)).isoformat()}"
            ),
            style="bold cyan",
        )
        prefix = "Dry run" if summary.dry_run else "Fill"
        self._fill_queue_from_lastfm_console.print(
            (
                f"{prefix}: {summary.history_scrobbles:,} scrobbles across "
                f"{summary.history_artists:,} artists; {summary.seed_count} seeds, "
                f"{summary.candidate_count:,} candidates; Queue "
                f"{summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}; selected {summary.selected}/"
                f"{summary.requested_count}."
            ),
            style="bold",
        )
        if summary.paused:
            self._fill_queue_from_lastfm_console.print(
                "Queue fill paused; rerun to continue.", style="bold yellow"
            )

    def _show_flush_queue(self, summary: the_queue.FlushSummary) -> None:
        self._render_queue_flush_table(self._flush_queue_console, summary.results)
        prefix = "Dry run" if summary.dry_run else "Flush"
        self._flush_queue_console.print(
            (
                f"{prefix}: Queue {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}; processed {summary.processed}/"
                f"{summary.total} artists."
            ),
            style="bold",
        )
        if summary.resumed:
            self._flush_queue_console.print(
                "Resumed the previously saved Queue flush.", style="cyan"
            )

    async def _execute_fill_queue_from_lastfm(
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
            with self.progress_display.create_progress(
                self.progress_display.spinner_column(),
                self.progress_display.text_column(
                    "[progress.description]{task.description}"
                ),
                self.progress_display.bar_column(),
                self.progress_display.complete_column(),
                self.progress_display.time_column(),
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
                summary = await the_queue.fill_queue_from_lastfm(
                    (await self.runtime.review_client()),
                    lastfm_client,
                    QueueFillOptions(
                        playlists=playlists,
                        count=effective_count,
                        max_playlist_length=max_playlist_length,
                        seed_count=seed_count,
                        dry_run=dry_run,
                    ),
                    QueueFillCallbacks(
                        choice_reader=FillQueueFromLastfmInteraction(self),
                        output=FillQueueFromLastfmInteraction(self),
                        progress_callback=FillQueueFromLastfmInteraction(self),
                        retry_call=FillQueueFromLastfmInteraction(self),
                    ),
                    QueueFillResources(),
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
        except (KeyboardInterrupt, CliInterruptedError) as exc:
            self._report_fill_queue_from_lastfm_interrupted_interrupted(exc)
        finally:
            if progress_ref is not None:
                progress_ref.stop()
        return summary

    async def _read_queue_artist(
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
        table = self.display.create_table(
            title=f"Map Queue artist: {recommendation.artist}"
        )
        table.add_column("#", justify="right")
        table.add_column("Spotify artist")
        table.add_column("Exact")
        table.add_column("Popularity", justify="right")
        table.add_column("Followers", justify="right")
        table.add_column("Spotify id")
        if not candidates:
            console.print(
                f"No Spotify artists matched {recommendation.artist}.",
                style="bold yellow",
            )
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                "yes" if candidate.exact_name else "no",
                str(candidate.popularity) if candidate.popularity is not None else "?",
                f"{candidate.followers:,}" if candidate.followers is not None else "?",
                candidate.spotify_id,
                style=None if candidate.exact_name else "dim",
            )
        console.print(table)
        response = await TerminalPrompt(self.display.prompt).ask(
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
            return await self._read_artist_search(console)
        if response == "s":
            return the_queue.CHOICE_SKIP
        if response == "q":
            return the_queue.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id

    async def _read_artist_search(self, console: Console) -> str:
        while True:
            search_text = await TerminalPrompt(self.display.prompt).ask(
                "New Spotify artist search", console=console
            )
            if search_text.strip():
                return f"{the_queue.CHOICE_SEARCH_PREFIX}{search_text.strip()}"
            console.print("Search text cannot be empty.", style="bold yellow")


@dataclass(frozen=True)
class FillQueueFromLastfmInteraction:
    """Own the original terminal interaction resources.

    Args:
        owner: Command instance owning its console, progress and wait state.
    """

    owner: QueueCLI

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
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
        self.owner._fill_queue_from_lastfm_echo(message)

    def progress(self, completed: int, total: int, status: str) -> None:
        """Present the command's original progress.

        Args:
            completed: Original completed.
            total: Original total.
            status: Original status.
        """
        check_cli_interruption()
        self.owner._fill_queue_from_lastfm_update_progress(completed, total, status)

    async def choose_artist(
        self,
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        """Use this command's fixed choose artist prompt.

        Args:
            recommendation: Original operator prompt value.
            candidates: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return await self.owner._fill_queue_from_lastfm_ask_queue_artist(
            recommendation, candidates
        )


@dataclass(frozen=True)
class FlushQueueInteraction:
    """Own the original terminal interaction resources.

    Args:
        owner: Command instance owning its console, progress and wait state.
    """

    owner: QueueCLI

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
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
        self.owner._flush_queue_echo(message)

    def progress(self, completed: int, total: int, status: str) -> None:
        """Present the command's original progress.

        Args:
            completed: Original completed.
            total: Original total.
            status: Original status.
        """
        check_cli_interruption()
        self.owner._flush_queue_update_progress(completed, total, status)


@dataclass(frozen=True)
class FillQueueFromLastfmDiagnostics:
    """Own the command's original presentation state.

    Args:
        owner: Existing command instance and its display resources.
    """

    owner: QueueCLI

    def echo(self, message: str) -> None:
        """Present the command's original diagnostic.

        Args:
            message: Original message.
        """
        self.owner._fill_queue_from_lastfm_log(message)
