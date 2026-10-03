"""Explicit found art CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Never

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class FoundArtCLI:
    """Execute and present found art through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        create_lastfm: Factory for lastfm instances.
        configuration: Original settings factory supplied by the facade.
        create_table: Factory for table instances.
        create_text: Factory for text instances.
        client: Client supplied by the caller.
        print_found_art_table: Original print found art table boundary supplied by the
            facade.
    """

    create_console: type[Console]
    create_lastfm: type[LastFmClient]
    configuration: type[Settings]
    create_table: type[Table]
    create_text: type[Text]
    client: Callable[..., Spotify]
    print_found_art_table: Callable[..., None]

    def _render_found_art_table(
        self, console: Console, results: tuple[found_art.FoundArtResult, ...]
    ) -> None:
        """Print ranked Last.fm candidates and their Spotify outcomes.

        Args:
            console: Rich console receiving this command's output.
            results: Results supplied by the caller.
        """
        table = self.create_table(title="Found Art")
        table.add_column("#", justify="right")
        table.add_column("Last.fm candidate")
        table.add_column("Recommendation")
        table.add_column("Spotify match")
        table.add_column("Result")
        action_styles = {
            "added": "bold green",
            "would add": "bold cyan",
            "already present": "yellow",
            "artist already selected": "yellow",
            "duplicate": "yellow",
            "liked": "magenta",
            "no Spotify match": "bold red",
        }
        for number, result in enumerate(results, start=1):
            candidate = result.candidate
            support_count = len(candidate.supporting_seeds)
            support_text = (
                "base #"
                f"{candidate.base_rank}"
                "; weekly "
                f"{candidate.weekly_rank:.3f}"
                "; score "
                f"{candidate.score:.3f}"
                "; best "
                f"{candidate.best_match:.0%}"
                "; "
                f"{support_count}"
                " seed"
                f"{('s' if support_count != 1 else '')}"
            )
            if result.action == "artist already selected":
                match_text = self.create_text(
                    "Skipped after this artist was selected", style="yellow"
                )
            elif result.match is None:
                match_text = self.create_text(
                    "No unliked qualifying match", style="red"
                )
            else:
                match_text = self.create_text(
                    f"{', '.join(result.match.artists)}"
                    " - "
                    f"{result.match.track}"
                    "\n"
                    f"{result.match.album or '(no album)'}"
                    "; track "
                    f"{result.match.track_similarity:.0%}"
                )
            table.add_row(
                str(number),
                (f"{candidate.artist} - {candidate.track}"),
                support_text,
                match_text,
                self.create_text(result.action, style=action_styles[result.action]),
            )
        console.print(table)

    def _run_found_art(
        self,
        count: int | None,
        max_playlist_length: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> None:
        """Build Last.fm-style unheard recommendations for Found Art.

        Args:
            count: Count supplied by the caller.
            max_playlist_length: Max playlist length supplied by the caller.
            seed_count: Seed count supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._found_art_console = self.create_console()
        if count is not None and max_playlist_length is not None:
            raise typer.BadParameter(
                "use either --count or --max-playlist-length, not both"
            )
        configuration = self.configuration()
        try:
            playlist_id = found_art.parse_found_art_playlist_id(
                configuration.found_art_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except found_art.FoundArtConfigError as exc:
            self._report_found_art_configuration_failure(exc)
        effective_count = (
            found_art.DEFAULT_COUNT
            if count is None and max_playlist_length is None
            else count
        )
        lastfm_client = self.create_lastfm(
            api_key, username, event_callback=self._found_art_log
        )
        try:
            with self._found_art_console.status(
                "Preparing Found Art recommendations"
            ) as status:
                summary = found_art.run_found_art(
                    self.client(),
                    lastfm_client,
                    playlist_id,
                    count=effective_count,
                    max_playlist_length=max_playlist_length,
                    seed_count=seed_count,
                    dry_run=dry_run,
                    progress_callback=status.update,
                )
        except (found_art.FoundArtError, LastFmError) as exc:
            self._report_found_art_found_art_failure(exc)
        except SpotifyException as exc:
            self._report_found_art_spotify_spotify_failure(exc)
        self.print_found_art_table(self._found_art_console, summary.results)
        self._found_art_console.print(
            (
                "Listening week: "
                f"{summary.week_start.isoformat()}"
                " through "
                f"{(summary.week_start + timedelta(days=6)).isoformat()}"
            ),
            style="bold cyan",
        )
        self._found_art_console.print(
            (
                "History: "
                f"{summary.history_scrobbles:,}"
                " scrobbles across "
                f"{summary.history_tracks:,}"
                " tracks; "
                f"{summary.live_scrobbles_added:,}"
                " new live scrobbles."
            ),
            style="dim",
        )
        self._found_art_console.print(
            (
                "Recommendations: "
                f"{summary.seed_count}"
                " seeds produced "
                f"{summary.candidate_count:,}"
                " unheard candidates."
            ),
            style="dim",
        )
        if summary.dry_run:
            self._found_art_console.print(
                (
                    "Dry run: selected "
                    f"{summary.selected}"
                    " of "
                    f"{summary.requested_count}"
                    " requested tracks; Spotify was unchanged."
                ),
                style="bold cyan",
            )
        else:
            self._found_art_console.print(
                (
                    "Playlist: "
                    f"{summary.playlist_length_before}"
                    " -> "
                    f"{summary.playlist_length_after}"
                    " items; added "
                    f"{summary.added}"
                    " of "
                    f"{summary.requested_count}"
                    " requested tracks."
                ),
                style="bold",
            )

    def _found_art_log(self, message: str) -> None:
        return self._found_art_console.print(message, style="yellow")

    def _report_found_art_configuration_failure(
        self, exc: found_art.FoundArtConfigError
    ) -> Never:
        self._found_art_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_found_art_found_art_failure(
        self, exc: found_art.FoundArtError | LastFmError
    ) -> Never:
        self._found_art_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_found_art_spotify_spotify_failure(self, exc: SpotifyException) -> Never:
        self._found_art_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc
