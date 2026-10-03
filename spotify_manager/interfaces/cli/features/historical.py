"""Explicit historical CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Never

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import (
    blast_from_past_artists as blast_from_past_artists,
)
from spotify_manager.interfaces.operations import daily_mind_radio as daily_mind_radio
from spotify_manager.interfaces.operations import new_kids as new_kids
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class HistoricalCLI:
    """Execute and present historical through explicit facade dependencies.

    Args:
        create_text: Rich text constructor for historical result cells.
        create_console: Factory for console instances.
        configuration: Original settings factory supplied by the facade.
        create_table: Factory for table instances.
        client: Client supplied by the caller.
        print_scrobble_selection_table: Original print scrobble selection table boundary
            supplied by the facade.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    create_text: type[Text]
    create_console: type[Console]
    configuration: type[Settings]
    create_table: type[Table]
    client: Callable[..., Spotify]
    print_scrobble_selection_table: Callable[..., None]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _scrobble_date(self, timestamp_ms: int) -> str:
        """Format one Last.fm timestamp in the listening timezone.

        Args:
            timestamp_ms: Timestamp ms supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        return datetime.fromtimestamp(
            timestamp_ms / 1000, blast_from_past.SCROBBLE_TIMEZONE
        ).strftime("%Y-%m-%d")

    def _run_blast_from_the_past(
        self, count: int | None, max_playlist_length: int | None, dry_run: bool
    ) -> None:
        """Select past scrobbles and add their Spotify matches to the playlist.

        Args:
            count: Count supplied by the caller.
            max_playlist_length: Max playlist length supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        console = self.create_console()
        if count is not None and max_playlist_length is not None:
            raise typer.BadParameter(
                "use either --count or --max-playlist-length, not both"
            )
        configuration = self.configuration()
        try:
            playlist_id = blast_from_past.parse_playlist_id(
                configuration.blast_from_the_past_playlist
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            self._report_blast_from_the_past_configuration_failure(exc, console)
        effective_count = 10 if count is None and max_playlist_length is None else count
        status_text = "Preparing Last.fm scrobbles"
        if dry_run:
            status_text += " (dry run)"
        try:
            with console.status(status_text) as status:
                summary = blast_from_past.add_blast_from_past_to_spotify(
                    self.client(),
                    playlist_id,
                    count=effective_count,
                    max_playlist_length=max_playlist_length,
                    progress_callback=status.update,
                    dry_run=dry_run,
                )
        except blast_from_past.BlastFromPastError as exc:
            self._report_blast_from_the_past_blast_from_past_failure(exc, console)
        except SpotifyException as exc:
            self._report_blast_from_the_past_spotify_spotify_failure(exc, console)
        if summary.batch is None:
            console.print(
                (
                    "Playlist already contains "
                    f"{summary.playlist_length_before}"
                    " items; nothing was added."
                ),
                style="bold green",
            )
            return
        console.print(
            (
                "Random.org timestamp: "
                f"{summary.batch.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            ),
            style="bold cyan",
        )
        console.print(
            (
                "Eligible dates: "
                f"{summary.batch.available_dates}"
                " ("
                f"{blast_from_past.FIRST_ELIGIBLE_DATE.isoformat()}"
                " through "
                f"{summary.batch.cutoff_date.isoformat()}"
                ")"
            ),
            style="dim",
        )
        self.print_scrobble_selection_table(
            console, "A blast from the past", summary.results
        )
        verb = "would add" if dry_run else "added"
        console.print(
            (
                "Playlist: "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                " items; "
                f"{verb}"
                " "
                f"{summary.added}"
                " of "
                f"{summary.requested_count}"
                " selections."
            ),
            style="bold cyan" if dry_run else "bold",
        )

    def _run_blast_from_the_past_artists(self, count: int, dry_run: bool) -> None:
        """Add liked tracks from artists heard recently, but not this year.

        Args:
            count: Count supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._blast_from_the_past_artists_console = self.create_console()
        try:
            playlist_id = blast_from_past.parse_playlist_id(
                self.configuration().blast_from_the_past_playlist
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            self._report_blast_from_the_past_artists_configuration_failure(exc)
        try:
            with self._blast_from_the_past_artists_console.status(
                "Reading dormant artists"
            ) as self._blast_from_the_past_artists_status:
                summary = (
                    blast_from_past_artists.add_dormant_artists_to_blast_from_past(
                        self.review_client(),
                        playlist_id,
                        count=count,
                        echo=self._blast_from_the_past_artists_echo,
                        progress_callback=self._blast_from_the_past_artists_log,
                        retry_call=self._blast_from_the_past_artists_retry_call,
                        dry_run=dry_run,
                    )
                )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_blast_from_the_past_artists_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_blast_from_the_past_artists_server_failure(exc)
        except (blast_from_past.BlastFromPastError, new_kids.NewKidsError) as exc:
            self._report_blast_from_the_past_artists_blast_from_past_failure(exc)
        except SpotifyException as exc:
            self._report_blast_from_the_past_artists_spotify_spotify_failure(exc)
        table = self.create_table(title="A blast from the past · dormant artists")
        table.add_column("Last.fm artist", style="bold")
        table.add_column("Scrobbles", justify="right")
        table.add_column("Spotify artist")
        table.add_column("Liked track")
        table.add_column("Popularity", justify="right")
        table.add_column("Action")
        for result in summary.results:
            table.add_row(
                result.artist,
                str(result.scrobbles),
                result.spotify_artist or ("-"),
                result.track or ("-"),
                str(result.popularity) if result.popularity is not None else "-",
                "would add" if dry_run and result.action == "added" else result.action,
            )
        self._blast_from_the_past_artists_console.print(table)
        verb = "would add" if dry_run else "added"
        self._blast_from_the_past_artists_console.print(
            (
                "History years: "
                f"{summary.history_years[0]}"
                "-"
                f"{summary.history_years[-1]}"
                "; excluded "
                f"{summary.current_year}"
                ". Candidates: "
                f"{summary.candidate_count}"
                "; playlist "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "; "
                f"{verb}"
                " "
                f"{summary.added}"
                " of "
                f"{summary.requested_count}"
                "."
            ),
            style="bold cyan" if dry_run else "bold",
        )

    def _blast_from_the_past_artists_echo(self, message: str) -> None:
        self._blast_from_the_past_artists_console.print(
            message, style="yellow", markup=False
        )

    def _blast_from_the_past_artists_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._blast_from_the_past_artists_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _blast_from_the_past_artists_log(
        self, _done: int, _total: int, message: str
    ) -> None:
        return self._blast_from_the_past_artists_status.update(message)

    def _run_daily_mind_radio(self, dry_run: bool) -> None:
        """Add tracks from today's Last.fm anniversaries to Daily Mind Radio.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        console = self.create_console()
        configuration = self.configuration()
        try:
            playlist_id = blast_from_past.parse_playlist_id(
                configuration.daily_mind_radio_playlist,
                setting_name="DAILY_MIND_RADIO_PLAYLIST",
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            self._report_daily_mind_radio_configuration_failure(exc, console)
        try:
            with console.status("Preparing anniversary scrobbles") as status:
                summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
                    self.client(),
                    playlist_id,
                    progress_callback=status.update,
                    dry_run=dry_run,
                )
        except blast_from_past.BlastFromPastError as exc:
            self._report_daily_mind_radio_blast_from_past_failure(exc, console)
        except SpotifyException as exc:
            self._report_daily_mind_radio_spotify_spotify_failure(exc, console)
        self._show_daily_mind_radio(console, dry_run, summary)

    def _report_blast_from_the_past_configuration_failure(
        self, exc: blast_from_past.BlastFromPastConfigError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_blast_from_the_past_blast_from_past_failure(
        self, exc: blast_from_past.BlastFromPastError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_blast_from_the_past_spotify_spotify_failure(
        self, exc: SpotifyException, console: Console
    ) -> Never:
        console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_blast_from_the_past_artists_configuration_failure(
        self, exc: blast_from_past.BlastFromPastConfigError
    ) -> Never:
        self._blast_from_the_past_artists_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_blast_from_the_past_artists_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._blast_from_the_past_artists_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_blast_from_the_past_artists_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._blast_from_the_past_artists_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_blast_from_the_past_artists_blast_from_past_failure(
        self, exc: blast_from_past.BlastFromPastError | new_kids.NewKidsError
    ) -> Never:
        self._blast_from_the_past_artists_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_blast_from_the_past_artists_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._blast_from_the_past_artists_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_daily_mind_radio_configuration_failure(
        self, exc: blast_from_past.BlastFromPastConfigError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_daily_mind_radio_blast_from_past_failure(
        self, exc: blast_from_past.BlastFromPastError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_daily_mind_radio_spotify_spotify_failure(
        self, exc: SpotifyException, console: Console
    ) -> Never:
        console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _show_daily_mind_radio(
        self,
        console: Console,
        dry_run: bool,
        summary: daily_mind_radio.DailyMindRadioSpotifySummary,
    ) -> None:
        """Show daily mind radio.

        Args:
            console: Rich console receiving this command's output.
            dry_run: Whether to preview changes using the original routine behavior.
            summary: Completed routine outcome to render.
        """
        target_dates = self._format_missing_dates(summary.batch.target_dates)
        console.print(f"Anniversary dates: {target_dates}", style="dim")
        if summary.batch.missing_dates:
            missing_dates = self._format_missing_dates(summary.batch.missing_dates)
            console.print(f"No scrobbles, skipped: {missing_dates}", style="yellow")
        if not summary.batch.selections:
            console.print(
                "None of today's anniversary dates had scrobbles; nothing was added.",
                style="bold green",
            )
            return
        generated_at = summary.batch.generated_at
        if generated_at is None:
            raise RuntimeError("A populated Daily Mind Radio batch has no timestamp.")
        console.print(
            (f"Random.org timestamp: {generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"),
            style="bold cyan",
        )
        self.print_scrobble_selection_table(
            console, "Daily mind radio", summary.results
        )
        verb = "would add" if dry_run else "added"
        console.print(
            (
                "Playlist: "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                " items; "
                f"{verb}"
                " "
                f"{summary.added}"
                " of "
                f"{len(summary.batch.selections)}"
                " populated anniversary dates."
            ),
            style="bold cyan" if dry_run else "bold",
        )

    def _format_missing_dates(self, dates: tuple[date, ...]) -> str:
        formatted = []
        for missing_date in dates:
            formatted.append(missing_date.isoformat())
        return ", ".join(formatted)

    def _render_scrobble_selection_table(
        self,
        console: Console,
        title: str,
        results: tuple[blast_from_past.SpotifySelectionResult, ...],
    ) -> None:
        """Print Last.fm selections and their Spotify outcomes.

        Args:
            console: Rich console receiving this command's output.
            title: Title supplied by the caller.
            results: Results supplied by the caller.
        """
        table = self.create_table(title=title)
        table.add_column("#", justify="right")
        table.add_column("Date")
        table.add_column("Rule")
        table.add_column("Last.fm scrobble")
        table.add_column("Spotify match")
        table.add_column("Result")
        action_styles = {
            "added": "bold green",
            "already present": "green",
            "duplicate selection": "yellow",
            "no match": "bold red",
        }
        for number, result in enumerate(results, start=1):
            selection = result.selection
            album = selection.scrobble.album or "(no album)"
            scrobble_text = (
                f"{selection.scrobble.artist} - {selection.scrobble.track} - {album}"
            )
            if result.match is None:
                match_text = self.create_text("No qualifying result", style="red")
            else:
                match_album = result.match.album or "(no album)"
                liked = "liked" if result.match.liked else "unliked"
                album_score = (
                    "n/a"
                    if result.match.album_similarity is None
                    else (f"{result.match.album_similarity:.0%}")
                )
                match_text = self.create_text(
                    f"{', '.join(result.match.artists)}"
                    " - "
                    f"{result.match.track}"
                    " - "
                    f"{match_album}"
                    "\n"
                    f"{liked}"
                    "; track "
                    f"{result.match.track_similarity:.0%}"
                    ", album "
                    f"{album_score}"
                    "; "
                    f"{result.qualifying_matches}"
                    " qualified"
                )
            table.add_row(
                str(number),
                selection.selected_date.isoformat(),
                (
                    "page "
                    f"{selection.page}"
                    "/"
                    f"{selection.total_pages}"
                    ", "
                    f"{selection.direction}"
                    ", #"
                    f"{selection.position}"
                ),
                self.create_text(scrobble_text),
                match_text,
                self.create_text(result.action, style=action_styles[result.action]),
            )
        console.print(table)
