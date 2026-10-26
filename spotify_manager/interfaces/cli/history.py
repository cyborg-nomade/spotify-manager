"""Synchronous history command execution and unchanged terminal presentation."""

from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.table import Table

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.cli.output import StatusOutput
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import scrobble_history as history
from spotify_manager.settings import Settings


@dataclass
class HistoryCommand:
    """Refresh history with named validation, execution and presentation steps.

    Args:
        console: Operator-facing Rich console.
        configuration: Settings observed at the original command boundary.
    """

    console: Console
    configuration: Settings

    def run(self, full_rebuild: bool, dry_run: bool) -> None:
        """Run the original configuration, refresh and rendering sequence.

        Args:
            full_rebuild: Original complete-history replacement flag.
            dry_run: Original persistence preview flag.

        Raises:
            typer.Exit: Configuration or anticipated refresh failure exits with 1.
        """
        lastfm, username = self._client()
        try:
            with self.console.status("Refreshing Last.fm scrobble history") as status:
                summary = history.refresh_scrobble_history(
                    lastfm,
                    expected_username=username,
                    dry_run=dry_run,
                    full_rebuild=full_rebuild,
                    progress_callback=StatusOutput(status),
                )
        except (history.ScrobbleHistoryError, LastFmError) as error:
            self._fail(error)
        present_history_summary(self.console, summary)

    def echo(self, message: str) -> None:
        """Present the original yellow Last.fm event text without a closure.

        Args:
            message: Original client event text, including existing Rich markup.
        """
        self.console.print(message, style="yellow")

    def _client(self) -> tuple[history.LastFmReader, str]:
        try:
            key, username = found_art.validate_lastfm_configuration(
                self.configuration.lastfm_api_key,
                self.configuration.lastfm_username,
            )
        except found_art.FoundArtConfigError as error:
            self._fail(error)
        return lastfm_client(LastFmCredentials(key, username), self), username

    def _fail(
        self,
        error: found_art.FoundArtConfigError
        | history.ScrobbleHistoryError
        | LastFmError,
    ) -> Never:
        self.console.print(str(error), style="bold red", markup=False)
        raise typer.Exit(code=1) from error


def present_history_summary(
    console: Console, summary: history.ScrobbleHistorySummary
) -> None:
    """Render the unchanged history counts and accepted persistence outcome.

    Args:
        console: Original command-owned Rich console.
        summary: Accepted history result, without modifying its values.
    """
    table = Table(title="Last.fm scrobble history")
    table.add_column("Source")
    table.add_column("Scrobbles", justify="right")
    table.add_row("Existing export", f"{summary.export_scrobbles:,}")
    table.add_row("Legacy Found Art delta", f"+{summary.legacy_scrobbles_added:,}")
    table.add_row("Live Last.fm API", f"+{summary.live_scrobbles_added:,}")
    table.add_row("Merged total", f"{summary.total_scrobbles:,}", style="bold")
    console.print(table)
    if summary.dry_run:
        console.print("Dry run: the canonical history was not changed.", style="cyan")
        return
    if summary.persisted:
        console.print(
            f"Saved atomically after backup: {summary.backup_path}",
            style="bold green",
            markup=False,
        )
        return
    console.print("The canonical history was already current.", style="green")
