"""Explicit releases CLI execution, prompts and presentation."""

from dataclasses import dataclass
from typing import Never

import typer
from requests.exceptions import RequestException
from rich.console import Console
from rich.progress import Progress
from rich.table import Table
from spotipy.exceptions import SpotifyException

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client as create_lastfm_client
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import ReleaseCheckResult
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.display import ProgressDisplay
from spotify_manager.interfaces.cli.history import present_history_summary
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.interfaces.requests.release_check import ReleaseCheckCallbacks
from spotify_manager.interfaces.requests.release_check import ReleaseCheckOptions
from spotify_manager.interfaces.requests.release_check import ReleaseCheckResources


@dataclass(kw_only=True)
class ReleasesCLI:
    """Run release checking with artist and release choices.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        progress_display: Rich console, table and live-status constructors.
        display: Rich console, table and live-status constructors.
    """

    runtime: CliResources

    progress_display: ProgressDisplay
    display: ConsoleDisplay

    def _prompt_release_check_artist(
        self,
        console: Console,
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
        progress: Progress,
    ) -> str:
        """Prompt for one ambiguous Last.fm-to-Spotify artist mapping.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        progress.stop()
        try:
            return self._read_release_check_artist(
                console, artist, candidates, progress
            )
        finally:
            progress.start()

    def _prompt_release_check_release(
        self,
        console: Console,
        artist: release_check.RankedArtist,
        release: release_check.ReleaseCandidate,
        track: release_check.ReleaseTrack,
        destinations: tuple[str, ...],
        unattached_single: bool,
        progress: Progress,
    ) -> str:
        """Prompt immediately before adding one eligible release.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            release: Release supplied by the caller.
            track: Track supplied by the caller.
            destinations: Destinations supplied by the caller.
            unattached_single: Unattached single supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        progress.stop()
        try:
            tags = release_check.release_tags(release)
            table = self.display.create_table(
                title=f"Review release from #{artist.rank} {artist.name}"
            )
            table.add_column("Release")
            table.add_column("Type")
            table.add_column("Date")
            table.add_column("First track")
            table.add_column("Destinations")
            table.add_row(
                release.name,
                " / ".join((release.release_type, *tags)),
                release.release_date,
                track.name,
                ", ".join(destinations),
                style="bold yellow" if tags else None,
            )
            console.print(table)
            prompt = "[a]dd / [s]kip permanently / [q]uit and resume later"
            choices = ["a", "s", "q"]
            default = "a"
            if unattached_single:
                prompt = (
                    "[a]dd to Wine Cellar / keep [p]ending / [s]kip p"
                    "ermanently / [q]uit and resume later"
                )
                choices.insert(1, "p")
                default = "p"
            response = self.display.prompt.ask(
                prompt, choices=choices, default=default, console=console
            )
            return {
                "a": release_check.CHOICE_ADD,
                "p": release_check.CHOICE_PENDING,
                "s": release_check.CHOICE_SKIP,
                "q": release_check.CHOICE_QUIT,
            }[response]
        finally:
            progress.start()

    def _render_release_check_summary(
        self, console: Console, summary: release_check.ReleaseCheckSummary
    ) -> None:
        """Render the release window and every discovered release decision.

        Args:
            console: Rich console receiving this command's output.
            summary: Completed routine outcome to render.
        """
        if summary.history_refresh is not None:
            present_history_summary(console, summary.history_refresh)
        self._show_release_decisions(console, summary)
        mode = "Dry run" if summary.dry_run else "Release check"
        resumed = " · resumed" if summary.resumed else ""
        console.print(
            (
                f"{mode}{resumed}: {summary.artists_processed}/"
                f"{summary.artists_total} artists complete; {len(summary.results)}"
                f" release decision(s)."
            ),
            style="bold cyan" if summary.dry_run else "bold green",
        )
        cleanup_verb = "Would remove" if summary.dry_run else "Removed"
        console.print(
            (
                f"{cleanup_verb} {summary.wine_cellar_duplicates_removed}"
                f" duplicate Wine Cellar track(s), keeping each artist's "
                f"first occurrence."
            ),
            style="cyan" if summary.dry_run else "green",
        )
        if summary.dry_run:
            console.print(
                (
                    "Spotify, release decisions, and the audit log we"
                    "re unchanged. Last.fm history, artist mappings, "
                    "and permanent artist skips were persisted."
                ),
                style="cyan",
            )
        else:
            console.print(
                (
                    f"Added {summary.wine_cellar_added}"
                    f" track(s) to Wine Cellar and {summary.new_vintage_added}"
                    f" to New Vintage."
                ),
                style="green",
            )
        if summary.paused:
            message = (
                "Dry run stopped; release decisions were not saved."
                if summary.dry_run
                else "Release check paused. Rerun the command to resume here."
            )
            console.print(message, style="bold yellow")

    def _run_check_new_releases(self, dry_run: bool) -> None:
        """Check Last.fm's most-played artists for newly released music.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._check_new_releases_console = self.display.create_console()
        configuration = self.runtime.configuration()
        try:
            playlists = release_check.ReleaseCheckPlaylists.from_references(
                configuration.wine_cellar_playlist, configuration.new_vintage_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (
            release_check.ReleaseCheckConfigError,
            found_art.FoundArtConfigError,
        ) as exc:
            self._report_check_new_releases_configuration_failure(exc)
        lastfm_client = create_lastfm_client(
            LastFmCredentials(api_key, username), CheckNewReleasesDiagnostics(self)
        )
        try:
            with self.progress_display.create_progress(
                self.progress_display.spinner_column(),
                self.progress_display.text_column(
                    "[progress.description]{task.description}"
                ),
                self.progress_display.bar_column(),
                self.progress_display.complete_column(),
                self.progress_display.time_column(),
                console=self._check_new_releases_console,
                transient=True,
            ) as self._check_new_releases_progress:
                progress_ref = self._check_new_releases_progress
                self._check_new_releases_task = (
                    self._check_new_releases_progress.add_task(
                        "Preparing release check", total=None
                    )
                )
                summary = release_check.run_release_check(
                    self.runtime.client(),
                    lastfm_client,
                    ReleaseCheckOptions(
                        playlists=playlists, expected_username=username, dry_run=dry_run
                    ),
                    ReleaseCheckCallbacks(
                        artist_choice_reader=CheckNewReleasesInteraction(self),
                        release_choice_reader=CheckNewReleasesInteraction(self),
                        progress_callback=CheckNewReleasesInteraction(self),
                    ),
                    ReleaseCheckResources(),
                )
        except KeyboardInterrupt as exc:
            self._report_check_new_releases_interrupted_interrupted(exc, dry_run)
        except (
            release_check.ReleaseCheckError,
            scrobble_history.ScrobbleHistoryError,
            LastFmError,
        ) as exc:
            self._report_check_new_releases_release_check_failure(exc, dry_run)
        except SpotifyException as exc:
            self._report_check_new_releases_spotify_spotify_failure(exc, dry_run)
        except RequestException as exc:
            self._report_check_new_releases_connection_request_exception(exc, dry_run)
        finally:
            if progress_ref is not None:
                progress_ref.stop()
        self._render_release_check_summary(self._check_new_releases_console, summary)

    def _check_new_releases_update_progress(
        self, completed: int, total: int, status: str
    ) -> None:
        self._check_new_releases_progress.update(
            self._check_new_releases_task,
            completed=completed,
            total=total or None,
            description=status,
        )

    def _check_new_releases_choose_release(
        self,
        artist: release_check.RankedArtist,
        release: release_check.ReleaseCandidate,
        track: release_check.ReleaseTrack,
        destinations: tuple[str, ...],
        unattached: bool,
    ) -> str:
        return self._prompt_release_check_release(
            self._check_new_releases_console,
            artist,
            release,
            track,
            destinations,
            unattached,
            self._check_new_releases_progress,
        )

    def _check_new_releases_log(self, message: str) -> None:
        return self._check_new_releases_console.print(message, style="yellow")

    def _check_new_releases_ask_release_check_artist(
        self,
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        return self._prompt_release_check_artist(
            self._check_new_releases_console,
            artist,
            candidates,
            self._check_new_releases_progress,
        )

    def _report_check_new_releases_release_check_failure(
        self,
        exc: release_check.ReleaseCheckError
        | scrobble_history.ScrobbleHistoryError
        | LastFmError,
        dry_run: bool,
    ) -> Never:
        self._check_new_releases_console.print(str(exc), style="bold red", markup=False)
        if not dry_run:
            self._check_new_releases_console.print(
                "Completed artist and release boundaries remain saved.", style="yellow"
            )
        raise typer.Exit(code=1) from exc

    def _report_check_new_releases_spotify_spotify_failure(
        self, exc: SpotifyException, dry_run: bool
    ) -> Never:
        self._check_new_releases_console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        if not dry_run:
            self._check_new_releases_console.print(
                "Release-check progress was saved; rerun to resume.", style="yellow"
            )
        raise typer.Exit(code=1) from exc

    def _report_check_new_releases_connection_request_exception(
        self, exc: RequestException, dry_run: bool
    ) -> Never:
        self._check_new_releases_console.print(
            f"Spotify connection failed: {exc}", style="bold red", markup=False
        )
        if not dry_run:
            self._check_new_releases_console.print(
                "Release-check progress was saved; rerun to resume.", style="yellow"
            )
        raise typer.Exit(code=1) from exc

    def _report_check_new_releases_configuration_failure(
        self, exc: release_check.ReleaseCheckConfigError | found_art.FoundArtConfigError
    ) -> Never:
        self._check_new_releases_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_check_new_releases_interrupted_interrupted(
        self, exc: KeyboardInterrupt, dry_run: bool
    ) -> Never:
        if dry_run:
            self._check_new_releases_console.print(
                "Dry run cancelled; nothing was changed.", style="yellow"
            )
        else:
            self._check_new_releases_console.print(
                "Release check paused. Progress was saved; rerun to resume.",
                style="bold yellow",
            )
        raise typer.Exit(code=0) from exc

    def _read_release_check_artist(
        self,
        console: Console,
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
        progress: Progress,
    ) -> str:
        """Read release check artist.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        self._show_artist_options(console, artist, candidates)
        response = self.display.prompt.ask(
            (
                "Artist number / [n]ew search / [s]kip this run /"
                " [p]ermanently skip / [q]uit and resume later"
            ),
            choices=[
                *(str(index) for index in range(1, len(candidates) + 1)),
                "n",
                "s",
                "p",
                "q",
            ],
            default="s",
            console=console,
        )
        if response == "n":
            return self._read_artist_search(console)
        if response == "s":
            return release_check.CHOICE_SKIP
        if response == "p":
            return release_check.CHOICE_SKIP_ARTIST
        if response == "q":
            return release_check.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id

    def _row_print_release_check_summary_result(
        self, action_styles: dict[str, str], result: ReleaseCheckResult, table: Table
    ) -> None:
        note = result.reason or (
            f"part of upcoming {result.linked_future_release}"
            if result.linked_future_release
            else ""
        )
        table.add_row(
            f"#{result.artist_rank} {result.artist}\n{result.artist_scrobbles:,} plays",
            f"{result.release}\n{result.release_type}",
            result.release_date,
            result.first_track or "-",
            self.display.create_text(
                result.wine_cellar_action,
                style=action_styles[result.wine_cellar_action],
            ),
            self.display.create_text(
                result.new_vintage_action,
                style=action_styles[result.new_vintage_action],
            ),
            note,
        )

    def _row_release_check_artist_candidate(
        self, candidate: SpotifyArtistCandidate, index: int, table: Table
    ) -> None:
        table.add_row(
            str(index),
            candidate.name,
            "yes" if candidate.exact_name else "no",
            str(candidate.popularity) if candidate.popularity is not None else "?",
            f"{candidate.followers:,}" if candidate.followers is not None else "?",
            candidate.spotify_id,
            style=None if candidate.exact_name else "dim",
        )

    def _show_release_decisions(
        self, console: Console, summary: release_check.ReleaseCheckSummary
    ) -> None:
        """Show release decisions.

        Args:
            console: Rich console receiving this command's output.
            summary: Completed routine outcome to render.
        """
        table = self.display.create_table(
            title=(
                f"Release check · {summary.checked_from.isoformat()} through "
                f"{summary.checked_through.isoformat()}"
            )
        )
        table.add_column("Artist")
        table.add_column("Release")
        table.add_column("Date")
        table.add_column("First track")
        table.add_column("Wine Cellar")
        table.add_column("New Vintage")
        table.add_column("Note")
        action_styles = {
            "added": "bold green",
            "would add": "bold cyan",
            "already present": "yellow",
            "artist already present": "yellow",
            "duplicate selection": "yellow",
            "not applicable": "dim",
        }
        for result in summary.results:
            self._row_print_release_check_summary_result(action_styles, result, table)
        console.print(table)

    def _show_artist_options(
        self,
        console: Console,
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> None:
        """Show artist options.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
        """
        table = self.display.create_table(
            title=(
                f"Map Last.fm artist #{artist.rank}: {artist.name} ("
                f"{artist.scrobbles:,} scrobbles)"
            )
        )
        table.add_column("#", justify="right")
        table.add_column("Spotify artist")
        table.add_column("Exact")
        table.add_column("Popularity", justify="right")
        table.add_column("Followers", justify="right")
        table.add_column("Spotify id")
        if not candidates:
            console.print(
                f"No Spotify artists matched the current search for {artist.name}.",
                style="bold yellow",
            )
        for index, candidate in enumerate(candidates, start=1):
            self._row_release_check_artist_candidate(candidate, index, table)
        console.print(table)

    def _read_artist_search(self, console: Console) -> str:
        while True:
            search_text = self.display.prompt.ask(
                "New Spotify artist search", console=console
            ).strip()
            if search_text:
                return f"{release_check.CHOICE_SEARCH_PREFIX}{search_text}"
            console.print("Search text cannot be empty.", style="bold yellow")


@dataclass(frozen=True)
class CheckNewReleasesDiagnostics:
    """Own the command's original presentation state.

    Args:
        owner: Existing command instance and its display resources.
    """

    owner: ReleasesCLI

    def echo(self, message: str) -> None:
        """Present the command's original diagnostic.

        Args:
            message: Original message.
        """
        self.owner._check_new_releases_log(message)


@dataclass(frozen=True)
class CheckNewReleasesInteraction:
    """Own the command's original presentation state.

    Args:
        owner: Existing command instance and its display resources.
    """

    owner: ReleasesCLI

    def progress(self, completed: int, total: int, status: str) -> None:
        """Present the command's original progress.

        Args:
            completed: Original completed.
            total: Original total.
            status: Original status.
        """
        self.owner._check_new_releases_update_progress(completed, total, status)

    def choose_artist(
        self,
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        """Use this command's fixed choose artist prompt.

        Args:
            artist: Original operator prompt value.
            candidates: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return self.owner._check_new_releases_ask_release_check_artist(
            artist, candidates
        )

    def choose_release(
        self,
        artist: release_check.RankedArtist,
        release: release_check.ReleaseCandidate,
        track: release_check.ReleaseTrack,
        destinations: tuple[str, ...],
        unattached: bool,
    ) -> str:
        """Use this command's fixed choose release prompt.

        Args:
            artist: Original operator prompt value.
            release: Original operator prompt value.
            track: Original operator prompt value.
            destinations: Original operator prompt value.
            unattached: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return self.owner._check_new_releases_choose_release(
            artist, release, track, destinations, unattached
        )
