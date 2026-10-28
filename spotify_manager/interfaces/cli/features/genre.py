"""Explicit genre CLI execution, prompts and presentation."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from typing import Never

import typer
from rich.console import Console
from rich.table import Table
from spotipy.exceptions import SpotifyException

from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import genre_reveal as genre_reveal


@dataclass(kw_only=True)
class GenreCLI:
    """Run Genre Reveal and present source and destination results.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        create_console: Interface presentation resource.
        create_table: Interface presentation resource.
    """

    runtime: CliResources

    create_console: type[Console]
    create_table: type[Table]

    async def _run_genre_reveal(
        self,
        state_path: Annotated[
            Path,
            typer.Option(
                "--state-path",
                help="Path to the shared Genre Reveal progress file.",
            ),
        ],
        log_path: Annotated[
            Path,
            typer.Option(
                "--log-path", help="Path to the append-only Genre Reveal audit log."
            ),
        ],
        open_pages: bool,
    ) -> None:
        """Save and sample the first unchecked Every Noise genre playlist.

        Args:
            state_path: State path supplied by the caller.
            log_path: Log path supplied by the caller.
            open_pages: Open pages supplied by the caller.
        """
        console = self.create_console()
        configuration = await self.runtime.configuration()
        try:
            destination_playlist_id = genre_reveal.parse_destination_playlist_id(
                configuration.genre_reveal_playlist
            )
            async with blocking_capacity():
                reading = asyncio.create_task(
                    asyncio.to_thread(genre_reveal.load_genre_reveal_state, state_path)
                )
                state = await finish_blocking(reading)
            entry = genre_reveal.first_incomplete_genre(state)
        except (
            genre_reveal.GenreRevealConfigError,
            genre_reveal.GenreRevealStateError,
            genre_reveal.GenreRevealCompleteError,
        ) as exc:
            self._report_genre_reveal_configuration_failure(exc, console)
        try:
            with console.status(f"Processing {entry.name}"):
                result = await genre_reveal.process_next_genre(
                    (await self.runtime.client()),
                    entry.slug,
                    entry.name,
                    destination_playlist_id,
                    log_path=log_path,
                )
                await genre_reveal.mark_genre_completed(entry.slug, state_path)
        except (
            genre_reveal.GenreRevealSourceError,
            genre_reveal.GenreRevealStateError,
            genre_reveal.GenreRevealLogError,
            blast_from_past.BlastFromPastError,
        ) as exc:
            self._report_genre_reveal_genre_reveal_source_failure(exc, console)
        except SpotifyException as exc:
            self._report_genre_reveal_spotify_spotify_failure(exc, console)
        self._show_genre_reveal(console, entry, open_pages, result)

    def _report_genre_reveal_configuration_failure(
        self,
        exc: genre_reveal.GenreRevealConfigError
        | genre_reveal.GenreRevealStateError
        | genre_reveal.GenreRevealCompleteError,
        console: Console,
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_genre_reveal_genre_reveal_source_failure(
        self,
        exc: genre_reveal.GenreRevealSourceError
        | genre_reveal.GenreRevealStateError
        | genre_reveal.GenreRevealLogError
        | blast_from_past.BlastFromPastError,
        console: Console,
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_genre_reveal_spotify_spotify_failure(
        self, exc: SpotifyException, console: Console
    ) -> Never:
        console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _show_genre_reveal(
        self,
        console: Console,
        entry: genre_reveal.GenreRouteEntry,
        open_pages: bool,
        result: genre_reveal.GenreRevealRunResult,
    ) -> None:
        """Show genre reveal.

        Args:
            console: Rich console receiving this command's output.
            entry: Entry supplied by the caller.
            open_pages: Open pages supplied by the caller.
            result: Result supplied by the caller.
        """
        table = self.create_table(title="Genre reveal")
        table.add_column("#", justify="right")
        table.add_column("Genre")
        table.add_column("Source playlist")
        table.add_column("Added", justify="right")
        table.add_column("Already present", justify="right")
        table.add_row(
            str(entry.position),
            entry.name,
            result.source_playlist_id,
            str(len(result.added_track_uris)),
            str(len(result.already_present_track_uris)),
        )
        console.print(table)
        console.print(f"Every Noise: {result.every_noise_url}", markup=False)
        console.print(f"Spotify: {result.source_playlist_url}", markup=False)
        console.print(
            (f"Saved the source playlist and completed {entry.name}."),
            style="bold green",
        )
        if open_pages:
            typer.launch(result.every_noise_url)
            typer.launch(result.source_playlist_url)
