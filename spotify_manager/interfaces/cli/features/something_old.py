"""Explicit something old CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.interfaces.operations import slow_listening as slow_listening
from spotify_manager.interfaces.operations import something_old as something_old
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class SomethingOldCLI:
    """Execute and present something old through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        create_lastfm: Factory for lastfm instances.
        prompt: Rich prompt implementation supplied by the facade.
        configuration: Original settings factory supplied by the facade.
        create_table: Factory for table instances.
        _scrobble_date:  scrobble date supplied by the caller.
        ask_something_old_album: Original ask something old album boundary supplied by
            the facade.
        ask_something_old_artist: Original ask something old artist boundary supplied by
            the facade.
        ask_something_old_mode: Original ask something old mode boundary supplied by the
            facade.
        client: Client supplied by the caller.
        print_scrobble_history_summary: Original print scrobble history summary boundary
            supplied by the facade.
        print_something_old_summary: Original print something old summary boundary
            supplied by the facade.
    """

    create_console: type[Console]
    create_lastfm: type[LastFmClient]
    prompt: type[Prompt]
    configuration: type[Settings]
    create_table: type[Table]
    _scrobble_date: Callable[..., str]
    ask_something_old_album: Callable[..., str]
    ask_something_old_artist: Callable[..., str]
    ask_something_old_mode: Callable[..., str]
    client: Callable[..., Spotify]
    print_scrobble_history_summary: Callable[..., None]
    print_something_old_summary: Callable[..., None]

    def _prompt_something_old_artist(
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
            table = self.create_table(
                title=(f"Choose the Spotify artist for {artist_name}")
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
                    (f"{candidate.followers:,}")
                    if candidate.followers is not None
                    else "?",
                    candidate.spotify_id,
                )
            console.print(table)
            response = self.prompt.ask(
                "Artist number or (q)uit",
                choices=[
                    *(str(index) for index in range(1, len(candidates) + 1)),
                    "q",
                ],
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
                "[bold]"
                f"{artist.artist}"
                "[/bold] · "
                f"{artist.scrobbles:,}"
                " scrobbles · average "
                f"{self._scrobble_date(artist.average_scrobble_ms)}"
                " · Spotify: "
                f"{spotify_artist.name}"
            )
            table = self.create_table(title="Something Old selection")
            table.add_column("#", justify="right")
            table.add_column("Source")
            table.add_column("What will be added")
            table.add_row("1", "Last.fm", "Up to 10 most-scrobbled tracks")
            table.add_row("2", "Spotify", "Up to 10 current popular tracks")
            table.add_row("3", "Catalog", "One complete studio album or EP")
            console.print(table)
            response = self.prompt.ask(
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
            table = self.create_table(title=f"Albums and EPs by {artist.artist}")
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
            response = self.prompt.ask(
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
                    "Something Old already contains "
                    f"{summary.playlist_length_before}"
                    " item(s); nothing was changed."
                ),
                style="yellow",
            )
            return
        if summary.history_refresh is not None:
            self.print_scrobble_history_summary(console, summary.history_refresh)
        if summary.ranking_preview:
            self._show_golden_ranking(console, summary)
        if summary.action == "cancelled":
            console.print(
                "Something Old was cancelled; Spotify was unchanged.",
                style="yellow",
            )
            return
        self._show_selected_tracks(console, summary)
        if summary.dry_run:
            console.print(
                (
                    "Dry run: would add "
                    f"{len(summary.tracks)}"
                    " track(s); Spotify and local files were "
                    "unchanged."
                ),
                style="bold cyan",
            )
        else:
            console.print(
                (
                    "Something Old: "
                    f"{summary.playlist_length_before}"
                    " -> "
                    f"{summary.playlist_length_after}"
                    "; added "
                    f"{len(summary.tracks)}"
                    " track(s)."
                ),
                style="bold green",
            )

    def _run_something_old(self, dry_run: bool) -> None:
        """Fill an empty Something Old slot from Last.fm Golden Oldies.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._something_old_console = self.create_console()
        configuration = self.configuration()
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
        lastfm_client = self.create_lastfm(
            api_key, username, event_callback=self._something_old_log
        )
        try:
            with self._something_old_console.status(
                "Preparing Something Old"
            ) as self._something_old_status:
                summary = something_old.run_something_old(
                    self.client(),
                    lastfm_client,
                    playlist_id,
                    expected_username=username,
                    artist_choice_reader=self._something_old_ask_something_old_artist,
                    mode_reader=self._something_old_ask_something_old_mode,
                    album_choice_reader=self._something_old_ask_something_old_album,
                    dry_run=dry_run,
                    progress_callback=self._something_old_status.update,
                )
        except (
            something_old.SomethingOldError,
            scrobble_history.ScrobbleHistoryError,
            LastFmError,
        ) as exc:
            self._report_something_old_something_old_failure(exc)
        except SpotifyException as exc:
            self._report_something_old_spotify_spotify_failure(exc)
        self.print_something_old_summary(self._something_old_console, summary)

    def _something_old_log(self, message: str) -> None:
        return self._something_old_console.print(message, style="yellow")

    def _something_old_ask_something_old_artist(
        self,
        artist: something_old.GoldenOldieArtist,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        return self.ask_something_old_artist(
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
        return self.ask_something_old_mode(
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
        return self.ask_something_old_album(
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
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
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
            (f"{artist.scrobbles:,}"),
            self._scrobble_date(artist.average_scrobble_ms),
        )

    def _row_print_something_old_summary_track(
        self, index: int, selection: Table, track: SelectedTrack
    ) -> None:
        selection.add_row(
            str(index),
            (f"{', '.join(track.artists)} - {track.track}"),
            track.album or ("(no album)"),
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
        ranking = self.create_table(
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
        selection = self.create_table(title="Something Old playlist selection")
        selection.add_column("#", justify="right")
        selection.add_column("Track")
        selection.add_column("Release")
        selection.add_column("Source")
        selection.add_column("Last.fm", justify="right")
        for index, track in enumerate(summary.tracks, start=1):
            self._row_print_something_old_summary_track(index, selection, track)
        console.print(selection)
