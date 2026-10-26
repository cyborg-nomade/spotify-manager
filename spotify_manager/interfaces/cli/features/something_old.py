"""Explicit something old CLI execution, prompts and presentation."""

from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.status import Status
from rich.table import Table
from spotipy.exceptions import SpotifyException

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client as create_lastfm_client
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.formatting import scrobble_date
from spotify_manager.interfaces.cli.history import present_history_summary
from spotify_manager.interfaces.cli.output import StatusOutput
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.interfaces.operations import slow_listening as slow_listening
from spotify_manager.interfaces.operations import something_old as something_old
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldResources


@dataclass(kw_only=True)
class SomethingOldCLI:
    """Run Golden Oldies selection with artist and track choices.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        display: Rich console, table and live-status constructors.
    """

    runtime: CliResources

    display: ConsoleDisplay

    def ask_artist(
        self,
        console: Console,
        artist_name: str,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
        status: Status,
    ) -> str:
        """Prompt when Spotify has several exact-name artist matches.

        Args:
            console: Rich console receiving this command's output.
            artist_name: Artist name supplied by the caller.
            candidates: Ordered choices offered by the routine.
            status: Status supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        status.stop()
        try:
            table = self.display.create_table(
                title=f"Choose the Spotify artist for {artist_name}"
            )
            table.add_column("#", justify="right")
            table.add_column("Artist")
            table.add_column("Popularity", justify="right")
            table.add_column("Followers", justify="right")
            table.add_column("Spotify id")
            for index, candidate in enumerate(candidates, start=1):
                table.add_row(
                    str(index),
                    candidate.name,
                    str(candidate.popularity)
                    if candidate.popularity is not None
                    else "?",
                    f"{candidate.followers:,}"
                    if candidate.followers is not None
                    else "?",
                    candidate.spotify_id,
                )
            console.print(table)
            response = self.display.prompt.ask(
                "Artist number or (q)uit",
                choices=[*(str(index) for index in range(1, len(candidates) + 1)), "q"],
                default="q",
                console=console,
            )
            return (
                "quit" if response == "q" else candidates[int(response) - 1].spotify_id
            )
        finally:
            status.start()

    def _prompt_something_old_mode(
        self,
        console: Console,
        artist: something_old.GoldenOldieArtist,
        spotify_artist: something_old.SpotifyArtistCandidate,
        status: Status,
    ) -> str:
        """Prompt for Last.fm tracks, Spotify tracks, or one album/EP.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            spotify_artist: Spotify artist supplied by the caller.
            status: Status supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        status.stop()
        try:
            console.print(
                f"[bold]{artist.artist}[/bold] · {artist.scrobbles:,}"
                f" scrobbles · average "
                f"{scrobble_date(artist.average_scrobble_ms)} · Spotify: "
                f"{spotify_artist.name}"
            )
            table = self.display.create_table(title="Something Old selection")
            table.add_column("#", justify="right")
            table.add_column("Source")
            table.add_column("What will be added")
            table.add_row("1", "Last.fm", "Up to 10 most-scrobbled tracks")
            table.add_row("2", "Spotify", "Up to 10 current popular tracks")
            table.add_row("3", "Catalog", "One complete studio album or EP")
            console.print(table)
            response = self.display.prompt.ask(
                "Selection or (q)uit",
                choices=["1", "2", "3", "q"],
                default="1",
                console=console,
            )
            return {
                "1": "lastfm_top_tracks",
                "2": "spotify_top_tracks",
                "3": "album",
                "q": "quit",
            }[response]
        finally:
            status.start()

    def _prompt_something_old_album(
        self,
        console: Console,
        artist: something_old.GoldenOldieArtist,
        releases: tuple[slow_listening.DiscographyRelease, ...],
        status: Status,
    ) -> str:
        """Prompt for one chronologically displayed studio album or EP.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            releases: Releases supplied by the caller.
            status: Status supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        status.stop()
        try:
            table = self.display.create_table(
                title=f"Albums and EPs by {artist.artist}"
            )
            table.add_column("#", justify="right")
            table.add_column("Date")
            table.add_column("Type")
            table.add_column("Release")
            table.add_column("Tracks", justify="right")
            table.add_column("Edition")
            for index, release in enumerate(releases, start=1):
                edition = (
                    "saved" if release.saved else "plain" if release.plain else "other"
                )
                table.add_row(
                    str(index),
                    release.chronology_date,
                    release.release_type,
                    release.name,
                    str(release.total_tracks),
                    edition,
                )
            console.print(table)
            response = self.display.prompt.ask(
                "Release number or (q)uit",
                choices=[*(str(index) for index in range(1, len(releases) + 1)), "q"],
                default="q",
                console=console,
            )
            return "quit" if response == "q" else releases[int(response) - 1].spotify_id
        finally:
            status.start()

    def _render_something_old_summary(
        self, console: Console, summary: something_old.SomethingOldSummary
    ) -> None:
        """Render Golden Oldies context and the selected Spotify tracks.

        Args:
            console: Rich console receiving this command's output.
            summary: Completed routine outcome to render.
        """
        if summary.action == "playlist not empty":
            console.print(
                (
                    f"Something Old already contains "
                    f"{summary.playlist_length_before}"
                    f" item(s); nothing was changed."
                ),
                style="yellow",
            )
            return
        if summary.history_refresh is not None:
            present_history_summary(console, summary.history_refresh)
        if summary.ranking_preview:
            self._show_golden_ranking(console, summary)
        if summary.action == "cancelled":
            console.print(
                "Something Old was cancelled; Spotify was unchanged.", style="yellow"
            )
            return
        self._show_selected_tracks(console, summary)
        if summary.dry_run:
            console.print(
                (
                    f"Dry run: would add {len(summary.tracks)}"
                    f" track(s); Spotify and local files were unchanged."
                ),
                style="bold cyan",
            )
        else:
            console.print(
                (
                    f"Something Old: {summary.playlist_length_before} -> "
                    f"{summary.playlist_length_after}; added {len(summary.tracks)}"
                    f" track(s)."
                ),
                style="bold green",
            )

    def _run_something_old(self, dry_run: bool) -> None:
        """Fill an empty Something Old slot from Last.fm Golden Oldies.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._something_old_console = self.display.create_console()
        configuration = self.runtime.configuration()
        try:
            playlist_id = something_old.parse_playlist_id(
                configuration.something_old_new_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (
            something_old.SomethingOldConfigError,
            found_art.FoundArtConfigError,
        ) as exc:
            self._report_something_old_configuration_failure(exc)
        lastfm_client = create_lastfm_client(
            LastFmCredentials(api_key, username), SomethingOldDiagnostics(self)
        )
        try:
            with self._something_old_console.status(
                "Preparing Something Old"
            ) as self._something_old_status:
                summary = something_old.run_something_old(
                    self.runtime.client(),
                    lastfm_client,
                    SomethingOldOptions(
                        playlist_id=playlist_id,
                        expected_username=username,
                        dry_run=dry_run,
                    ),
                    SomethingOldCallbacks(
                        mode_reader=SomethingOldInteraction(self),
                        album_choice_reader=SomethingOldInteraction(self),
                        artist_choice_reader=SomethingOldInteraction(self),
                        progress_callback=StatusOutput(self._something_old_status),
                    ),
                    SomethingOldResources(),
                )
        except (
            something_old.SomethingOldError,
            scrobble_history.ScrobbleHistoryError,
            LastFmError,
        ) as exc:
            self._report_something_old_something_old_failure(exc)
        except SpotifyException as exc:
            self._report_something_old_spotify_spotify_failure(exc)
        self._render_something_old_summary(self._something_old_console, summary)

    def _something_old_log(self, message: str) -> None:
        return self._something_old_console.print(message, style="yellow")

    def _something_old_ask_something_old_artist(
        self,
        artist: something_old.GoldenOldieArtist,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        return self.ask_artist(
            self._something_old_console,
            artist.artist,
            candidates,
            self._something_old_status,
        )

    def _something_old_ask_something_old_mode(
        self,
        artist: something_old.GoldenOldieArtist,
        spotify_artist: something_old.SpotifyArtistCandidate,
    ) -> str:
        return self._prompt_something_old_mode(
            self._something_old_console,
            artist,
            spotify_artist,
            self._something_old_status,
        )

    def _something_old_ask_something_old_album(
        self,
        artist: something_old.GoldenOldieArtist,
        releases: tuple[slow_listening.DiscographyRelease, ...],
    ) -> str:
        return self._prompt_something_old_album(
            self._something_old_console, artist, releases, self._something_old_status
        )

    def _report_something_old_configuration_failure(
        self, exc: something_old.SomethingOldConfigError | found_art.FoundArtConfigError
    ) -> Never:
        self._something_old_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_something_old_something_old_failure(
        self,
        exc: something_old.SomethingOldError
        | scrobble_history.ScrobbleHistoryError
        | LastFmError,
    ) -> Never:
        self._something_old_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_something_old_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._something_old_console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _row_print_something_old_summary_artist(
        self, artist: GoldenOldieArtist, index: int, ranking: Table
    ) -> None:
        ranking.add_row(
            str(index),
            artist.artist,
            f"{artist.scrobbles:,}",
            scrobble_date(artist.average_scrobble_ms),
        )

    def _row_print_something_old_summary_track(
        self, index: int, selection: Table, track: SelectedTrack
    ) -> None:
        selection.add_row(
            str(index),
            f"{', '.join(track.artists)} - {track.track}",
            track.album or "(no album)",
            track.source,
            str(track.lastfm_scrobbles) if track.lastfm_scrobbles is not None else "",
        )

    def _show_golden_ranking(
        self, console: Console, summary: something_old.SomethingOldSummary
    ) -> None:
        """Show golden ranking.

        Args:
            console: Rich console receiving this command's output.
            summary: Completed routine outcome to render.
        """
        ranking = self.display.create_table(
            title="Golden Oldies · oldest average scrobble dates"
        )
        ranking.add_column("#", justify="right")
        ranking.add_column("Artist")
        ranking.add_column("Scrobbles", justify="right")
        ranking.add_column("Average date")
        for index, artist in enumerate(summary.ranking_preview, start=1):
            self._row_print_something_old_summary_artist(artist, index, ranking)
        console.print(ranking)

    def _show_selected_tracks(
        self, console: Console, summary: something_old.SomethingOldSummary
    ) -> None:
        """Show selected tracks.

        Args:
            console: Rich console receiving this command's output.
            summary: Completed routine outcome to render.
        """
        selection = self.display.create_table(title="Something Old playlist selection")
        selection.add_column("#", justify="right")
        selection.add_column("Track")
        selection.add_column("Release")
        selection.add_column("Source")
        selection.add_column("Last.fm", justify="right")
        for index, track in enumerate(summary.tracks, start=1):
            self._row_print_something_old_summary_track(index, selection, track)
        console.print(selection)


@dataclass(frozen=True)
class SomethingOldDiagnostics:
    """Own the command's original presentation state.

    Args:
        owner: Existing command instance and its display resources.
    """

    owner: SomethingOldCLI

    def echo(self, message: str) -> None:
        """Present the command's original diagnostic.

        Args:
            message: Original message.
        """
        self.owner._something_old_log(message)


@dataclass(frozen=True)
class SomethingOldInteraction:
    """Own the command's terminal interaction state.

    Args:
        owner: Command owning the active console and progress display.
    """

    owner: SomethingOldCLI

    def choose_mode(
        self,
        artist: something_old.GoldenOldieArtist,
        spotify_artist: something_old.SpotifyArtistCandidate,
    ) -> str:
        """Use this command's fixed choose mode prompt.

        Args:
            artist: Original operator prompt value.
            spotify_artist: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return self.owner._something_old_ask_something_old_mode(artist, spotify_artist)

    def choose_album(
        self,
        artist: something_old.GoldenOldieArtist,
        releases: tuple[slow_listening.DiscographyRelease, ...],
    ) -> str:
        """Use this command's fixed choose album prompt.

        Args:
            artist: Original operator prompt value.
            releases: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return self.owner._something_old_ask_something_old_album(artist, releases)

    def choose_artist(
        self,
        artist: something_old.GoldenOldieArtist,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        """Use this command's fixed choose artist prompt.

        Args:
            artist: Original operator prompt value.
            candidates: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return self.owner._something_old_ask_something_old_artist(artist, candidates)
