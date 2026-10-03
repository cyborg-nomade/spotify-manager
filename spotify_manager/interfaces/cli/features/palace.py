"""Explicit palace CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.domain.palace_values import PalaceAlbumResult
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import review_album_limits
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class PalaceCLI:
    """Execute and present palace through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        configuration: Original settings factory supplied by the facade.
        create_table: Factory for table instances.
        create_text: Factory for text instances.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    create_console: type[Console]
    configuration: type[Settings]
    create_table: type[Table]
    create_text: type[Text]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _run_fill_palace_of_memory(
        self,
        dry_run: bool,
        alphabetical_start: str | None,
        set_alphabetical_cursor: int | None,
    ) -> None:
        """Add five alphabetical and five historical album first tracks.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            alphabetical_start: Alphabetical start supplied by the caller.
            set_alphabetical_cursor: Set alphabetical cursor supplied by the caller.
        """
        self._fill_palace_of_memory_console = self.create_console()
        if set_alphabetical_cursor is not None and dry_run:
            raise typer.BadParameter(
                "--set-alphabetical-cursor persists immediately "
                "and cannot use --dry-run"
            )
        if set_alphabetical_cursor is not None and alphabetical_start is not None:
            raise typer.BadParameter(
                "use either --set-alphabetical-cursor or --alphabetical-start, not both"
            )
        cursor_update: palace_of_memory.AlphabeticalCursorUpdate | None = None
        summary: palace_of_memory.PalaceOfMemorySummary | None = None
        try:
            if set_alphabetical_cursor is not None:
                cursor_update = self._execute_cursor_update(set_alphabetical_cursor)
            else:
                summary = self._execute_palace_fill(dry_run, alphabetical_start)
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_fill_palace_of_memory_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_fill_palace_of_memory_server_failure(exc)
        except palace_of_memory.PalaceOfMemoryError as exc:
            self._report_fill_palace_of_memory_palace_of_memory_failure(exc)
        except SpotifyException as exc:
            self._report_fill_palace_of_memory_spotify_spotify_failure(exc)
        self._show_fill_palace_of_memory(cursor_update, dry_run, summary)

    def _fill_palace_of_memory_echo(self, line: str = "") -> None:
        style = "bold green" if line.startswith("Added") else "cyan"
        self._fill_palace_of_memory_console.print(line, style=style, markup=False)

    def _fill_palace_of_memory_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._fill_palace_of_memory_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _report_fill_palace_of_memory_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._fill_palace_of_memory_console.print(
            (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_fill_palace_of_memory_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._fill_palace_of_memory_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_fill_palace_of_memory_palace_of_memory_failure(
        self, exc: palace_of_memory.PalaceOfMemoryError
    ) -> Never:
        self._fill_palace_of_memory_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_fill_palace_of_memory_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._fill_palace_of_memory_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _show_fill_palace_of_memory(
        self,
        cursor_update: palace_of_memory.AlphabeticalCursorUpdate | None,
        dry_run: bool,
        summary: palace_of_memory.PalaceOfMemorySummary | None,
    ) -> None:
        """Show fill palace of memory.

        Args:
            cursor_update: Cursor update supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
            summary: Completed routine outcome to render.
        """
        if cursor_update is not None:
            refresh = cursor_update.album_refresh
        elif summary is not None:
            refresh = summary.album_refresh
        else:
            raise AssertionError("Palace command completed without a result")
        self._show_album_refresh(refresh)
        if cursor_update is not None:
            self._fill_palace_of_memory_console.print(
                (
                    "Alphabetical cursor set to "
                    f"{cursor_update.next_index + 1}"
                    ": "
                    f"{cursor_update.next_album.artist}"
                    " - "
                    f"{cursor_update.next_album.album}"
                    ". The playlist was not changed."
                ),
                style="bold green",
            )
            return
        assert summary is not None
        table = self.create_table(title="Palace of Memory")
        table.add_column("Source")
        table.add_column("Date / position")
        table.add_column("Artist")
        table.add_column("Album")
        table.add_column("First track")
        table.add_column("Action")
        action_styles = {
            "added": "bold green",
            "already present": "cyan",
            "duplicate selection": "yellow",
            "no match": "bold red",
        }
        for result in summary.results:
            self._row_fill_palace_of_memory_result(
                action_styles, dry_run, result, table
            )
        self._fill_palace_of_memory_console.print(table)
        self._fill_palace_of_memory_console.print(
            (
                "Random.org timestamp: "
                f"{summary.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                " · cutoff "
                f"{summary.cutoff_date.isoformat()}"
                " · "
                f"{summary.available_dates}"
                " eligible dates."
            ),
            style="cyan",
        )
        self._fill_palace_of_memory_console.print(
            "Alphabetical cursor"
            + (" (manual)" if summary.alphabetical_cursor_overridden else "")
            + (
                ": "
                f"{summary.alphabetical_start_index + 1}"
                " -> "
                f"{summary.alphabetical_next_index + 1}"
                ". Playlist: "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                " tracks"
            )
            + (" (preview only)." if dry_run else "."),
            style="bold cyan" if dry_run else "bold green",
        )

    def _row_fill_palace_of_memory_result(
        self,
        action_styles: dict[str, str],
        dry_run: bool,
        result: PalaceAlbumResult,
        table: Table,
    ) -> None:
        if result.selected_date is None:
            location = "saved albums"
        else:
            location = (
                f"{result.selected_date.isoformat()}"
                " · "
                f"{result.history_position}"
                "/"
                f"{result.albums_on_date}"
            )
        resolved_album = (
            result.spotify_album.album
            if result.spotify_album is not None
            else result.album
        )
        action = "would add" if dry_run and result.action == "added" else result.action
        table.add_row(
            result.source,
            location,
            result.artist,
            resolved_album,
            result.first_track.name if result.first_track is not None else "-",
            self.create_text(action, style=action_styles[result.action]),
        )

    def _show_album_refresh(self, refresh: palace_of_memory.SavedAlbumRefresh) -> None:
        refresh_action = "updated" if refresh.persisted else "already current"
        self._fill_palace_of_memory_console.print(
            (
                "Saved albums "
                f"{refresh_action}"
                ": "
                f"{refresh.previous}"
                " -> "
                f"{refresh.current}"
                " ("
                f"{refresh.added}"
                " added, "
                f"{refresh.removed}"
                " removed, "
                f"{refresh.skipped}"
                " skipped)."
            ),
            style="bold cyan",
        )
        if refresh.backup_path:
            self._fill_palace_of_memory_console.print(
                (f"Album mirror backup: {refresh.backup_path}"), style="dim"
            )

    def _execute_cursor_update(
        self, position: int
    ) -> palace_of_memory.AlphabeticalCursorUpdate:
        with self._fill_palace_of_memory_console.status(
            "Setting the Palace alphabetical cursor"
        ) as status:
            return palace_of_memory.set_alphabetical_cursor(
                self.review_client(),
                position,
                progress_callback=status.update,
                retry_call=self._fill_palace_of_memory_retry_call,
            )

    def _execute_palace_fill(
        self, dry_run: bool, alphabetical_start: str | None
    ) -> palace_of_memory.PalaceOfMemorySummary:
        configuration = self.configuration()
        playlist_id = palace_of_memory.parse_playlist_id(
            configuration.palace_of_memory_playlist
        )
        with self._fill_palace_of_memory_console.status(
            "Planning Palace of Memory" + (" (dry run)" if dry_run else "")
        ) as status:
            return palace_of_memory.fill_palace_of_memory(
                self.review_client(),
                playlist_id,
                dry_run=dry_run,
                alphabetical_start=alphabetical_start,
                echo=self._fill_palace_of_memory_echo,
                progress_callback=status.update,
                retry_call=self._fill_palace_of_memory_retry_call,
            )
