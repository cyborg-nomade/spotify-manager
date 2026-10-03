"""Explicit artist review CLI execution, prompts and presentation."""

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

from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import review_artists as artist_review
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class ArtistReviewCLI:
    """Execute and present artist review through explicit facade dependencies.

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
        ask_artist_release_choice: Original ask artist release choice boundary supplied
            by the facade.
        ask_artist_track_choice: Original ask artist track choice boundary supplied by
            the facade.
        review_client: Original Spotify client factory supplied by the facade.
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
    ask_artist_release_choice: Callable[..., str]
    ask_artist_track_choice: Callable[..., str]
    review_client: Callable[..., Spotify]

    def _prompt_artist_track_choice(
        self,
        console: Console,
        artist: object,
        candidates: tuple[artist_review.TrackCandidate, ...],
        progress: Progress | None,
    ) -> str:
        """Prompt for one ambiguous ranked track.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            table = self.create_table(
                title=(f"Choose a track for {getattr(artist, 'name', '')}")
            )
            table.add_column("#", justify="right")
            table.add_column("Track")
            table.add_column("Release")
            table.add_column("Primary artist")
            table.add_column("Rank", justify="right")
            for index, candidate in enumerate(candidates, start=1):
                table.add_row(
                    str(index),
                    candidate.name,
                    candidate.album,
                    candidate.primary_artist_name,
                    str(candidate.rank),
                )
            console.print(table)
            choices = [str(index) for index in range(1, len(candidates) + 1)]
            response = self.prompt.ask(
                "Track number / [s]kip this run / [q]uit",
                choices=[*choices, "s", "q"],
                console=console,
            )
            if response == "s":
                return artist_review.CHOICE_SKIP
            if response == "q":
                return artist_review.CHOICE_QUIT
            return candidates[int(response) - 1].spotify_id
        finally:
            if progress is not None:
                progress.start()

    def _prompt_artist_release_choice(
        self,
        console: Console,
        artist: object,
        candidates: tuple[artist_review.ReleaseCandidate, ...],
        allow_decline: bool,
        progress: Progress | None,
    ) -> str:
        """Prompt for one eligible release, with an optional permanent decline.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            allow_decline: Allow decline supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        try:
            return self._read_artist_release_choice(
                console, artist, candidates, allow_decline, progress
            )
        finally:
            if progress is not None:
                progress.start()

    def _run_review_artists(self, refresh_cache: bool, limit: int | None) -> None:
        """Review followed artists and place one track in the matching queue.

        Args:
            refresh_cache: Refresh cache supplied by the caller.
            limit: Limit supplied by the caller.
        """
        self._review_artists_console = self.create_console()
        self._review_artists_progress_ref: Progress | None = None
        configuration = self.configuration()
        try:
            playlists = artist_review.QueuePlaylists.from_references(
                configuration.the_queue_playlist,
                configuration.the_queue_2_playlist,
                configuration.the_queue_3_playlist,
            )
        except artist_review.ArtistReviewConfigError as exc:
            self._report_review_artists_configuration_failure(exc)
        try:
            with self.create_progress(
                self.spinner_column(),
                self.text_column("[progress.description]{task.description}"),
                self.bar_column(),
                self.complete_column(),
                self.time_column(),
                console=self._review_artists_console,
                transient=True,
            ) as self._review_artists_progress:
                self._review_artists_progress_ref = self._review_artists_progress
                self._review_artists_task_id = self._review_artists_progress.add_task(
                    "Reviewing artists", total=None
                )
                summary = artist_review.review_artists(
                    self.review_client(),
                    playlists,
                    track_choice_reader=self._review_artists_ask_artist_track_choice,
                    release_choice_reader=self._review_artists_ask_artist_release_choice,
                    echo=self._review_artists_echo,
                    progress_callback=self._review_artists_update_progress,
                    refresh_cache=refresh_cache,
                    limit=limit,
                )
        except artist_review.SpotifyRateLimitError as exc:
            self._report_review_artists_rate_limit(exc)
        except artist_review.SpotifyTransientServerError as exc:
            self._report_review_artists_server_failure(exc)
        except artist_review.ArtistReviewError as exc:
            self._report_review_artists_artist_review_failure(exc)
        except SpotifyException as exc:
            self._report_review_artists_spotify_spotify_failure(exc)
        self._show_review_artists(summary)

    def _review_artists_echo(self, line: str = "") -> None:
        """Review artists echo.

        Args:
            line: Line supplied by the caller.
        """
        style = None
        if line.startswith("Auto-unfollowed"):
            style = "bold red"
        elif line.startswith("Planned automatic unfollow"):
            style = "yellow"
        elif line.startswith("Queued"):
            style = "bold green"
        elif line.startswith("Moved"):
            style = "bold cyan"
        elif line.startswith("Already queued") or line.startswith("Kept"):
            style = "green"
        elif line.startswith("Declined") or line.startswith("No eligible"):
            style = "dim yellow"
        elif line.startswith("No unliked"):
            style = "dim yellow"
        self._review_artists_console.print(line, style=style, markup=False)

    def _review_artists_update_progress(
        self, position: int, total: int, artist_name: str
    ) -> None:
        self._review_artists_progress.update(
            self._review_artists_task_id,
            completed=position,
            total=total,
            description=(f"Reviewing artists: {artist_name}"),
        )

    def _review_artists_ask_artist_track_choice(
        self, artist: object, candidates: tuple[artist_review.TrackCandidate, ...]
    ) -> str:
        return self.ask_artist_track_choice(
            self._review_artists_console,
            artist,
            candidates,
            self._review_artists_progress_ref,
        )

    def _review_artists_ask_artist_release_choice(
        self,
        artist: object,
        candidates: tuple[artist_review.ReleaseCandidate, ...],
        allow_decline: bool,
    ) -> str:
        return self.ask_artist_release_choice(
            self._review_artists_console,
            artist,
            candidates,
            allow_decline,
            self._review_artists_progress_ref,
        )

    def _report_review_artists_rate_limit(
        self, exc: artist_review.SpotifyRateLimitError
    ) -> Never:
        self._review_artists_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        self._review_artists_console.print(
            "Artist review progress and pending automatic decisions were saved.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_review_artists_server_failure(
        self, exc: artist_review.SpotifyTransientServerError
    ) -> Never:
        self._review_artists_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        self._review_artists_console.print(
            "Artist review progress and pending automatic decisions were saved.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_review_artists_configuration_failure(
        self, exc: artist_review.ArtistReviewConfigError
    ) -> Never:
        self._review_artists_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc

    def _report_review_artists_artist_review_failure(
        self, exc: artist_review.ArtistReviewError
    ) -> Never:
        self._review_artists_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc

    def _report_review_artists_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._review_artists_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
        )
        raise typer.Exit(code=1) from exc

    def _show_review_artists(self, summary: artist_review.ArtistReviewSummary) -> None:
        """Show review artists.

        Args:
            summary: Completed routine outcome to render.
        """
        table = self.create_table(
            title="Artist review paused" if summary.paused else "Artist review complete"
        )
        table.add_column("Reviewed", justify="right")
        table.add_column("Unfollowed", justify="right", style="red")
        table.add_column("Queued", justify="right", style="green")
        table.add_column("Moved", justify="right", style="cyan")
        table.add_column("Already queued", justify="right")
        table.add_column("Declined", justify="right")
        table.add_column("No action", justify="right")
        table.add_column("Skipped", justify="right", style="yellow")
        table.add_row(
            str(summary.reviewed),
            str(summary.unfollowed),
            str(summary.queued),
            str(summary.moved),
            str(summary.already_queued),
            str(summary.declined),
            str(summary.no_action),
            str(summary.skipped),
        )
        self._review_artists_console.print(table)

    def _read_artist_release_choice(
        self,
        console: Console,
        artist: object,
        candidates: tuple[artist_review.ReleaseCandidate, ...],
        allow_decline: bool,
        progress: Progress | None,
    ) -> str:
        """Read artist release choice.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            allow_decline: Allow decline supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        artist_name = getattr(artist, "name", "")
        if allow_decline:
            action = self.prompt.ask(
                (f"Add {artist_name} to queue 3?"),
                choices=["y", "n", "s", "q"],
                default="n",
                console=console,
            )
            if action == "n":
                return artist_review.CHOICE_DECLINE
            if action == "s":
                return artist_review.CHOICE_SKIP
            if action == "q":
                return artist_review.CHOICE_QUIT
        eligible_indexes = self._show_eligible_releases(
            console, artist, artist_name, candidates
        )
        choices = [str(index) for index in eligible_indexes]
        response = self.prompt.ask(
            "Eligible release number / [s]kip this run / [q]uit",
            choices=[*choices, "s", "q"],
            console=console,
        )
        if response == "s":
            return artist_review.CHOICE_SKIP
        if response == "q":
            return artist_review.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id

    def _row_artist_release_choice_candidate(
        self,
        artist_id: str,
        candidate: ReleaseCandidate,
        eligible_indexes: list[int],
        index: int,
        table: Table,
    ) -> None:
        eligible = candidate.is_eligible_for(artist_id)
        if eligible:
            eligible_indexes.append(index)
        table.add_row(
            str(index),
            candidate.name,
            candidate.release_type,
            candidate.release_date,
            candidate.first_track_name or ("No track"),
            candidate.first_track_primary_artist_name or ("Unknown"),
            "yes" if eligible else "no",
            style=None if eligible else "dim",
        )

    def _show_eligible_releases(
        self,
        console: Console,
        artist: object,
        artist_name: str,
        candidates: tuple[artist_review.ReleaseCandidate, ...],
    ) -> list[int]:
        """Show eligible releases.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            artist_name: Artist name supplied by the caller.
            candidates: Ordered choices offered by the routine.

        Returns:
            The original value selected or formatted by this adapter.
        """
        table = self.create_table(title=f"Choose a release for {artist_name}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("First track")
        table.add_column("First artist")
        table.add_column("Eligible")
        eligible_indexes: list[int] = []
        artist_id = getattr(artist, "spotify_id", "")
        for index, candidate in enumerate(candidates, start=1):
            self._row_artist_release_choice_candidate(
                artist_id, candidate, eligible_indexes, index, table
            )
        console.print(table)
        return eligible_indexes
