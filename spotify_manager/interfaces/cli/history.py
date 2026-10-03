"""Synchronous history command execution and unchanged terminal presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never
from typing import Protocol

import typer
from rich.console import Console
from rich.table import Table

from spotify_manager.client.lastfm import LastFmError
from spotify_manager.routines import found_art
from spotify_manager.routines import scrobble_history as history
from spotify_manager.settings import Settings


class LastFmFactory(Protocol):
    """Construct the existing caller-owned history reader with its event sink."""

    def __call__(
        self, api_key: str, username: str, *, event_callback: Callable[[str], None]
    ) -> history.LastFmReader:
        """Bind validated credentials to the original reader implementation.

        Args:
            api_key: Validated read-only credential.
            username: Validated history owner.
            event_callback: Command-owned terminal event sink.

        Returns:
            The original synchronous history reader.

        Raises:
            ValueError: Original client construction rejects its configuration.
        """
        ...


class HistoryRefresh(Protocol):
    """Call the existing history facade with its original keyword-only options."""

    def __call__(
        self,
        lastfm: history.LastFmReader,
        *,
        expected_username: str,
        dry_run: bool,
        full_rebuild: bool,
        progress_callback: Callable[[str], None],
    ) -> history.ScrobbleHistorySummary:
        """Run the original merge or rebuild and return its accepted outcome.

        Args:
            lastfm: Existing reader owned by this command.
            expected_username: Original export ownership constraint.
            dry_run: Original persistence preview flag.
            full_rebuild: Original complete replacement flag.
            progress_callback: Command-owned Rich status sink.

        Returns:
            Original accepted history summary.

        Raises:
            history.ScrobbleHistoryError: Original refresh cannot publish safely.
            LastFmError: Original Last.fm reads fail.
        """
        ...


@dataclass
class HistoryCommand:
    """Own a console and explicit history dependencies for one command invocation.

    Args:
        console: Caller-created Rich console, retaining original creation order.
        configuration: Caller-created settings, retaining facade override seams.
        validate: Original configuration validator and error ordering.
        create_client: Original Last.fm reader constructor.
        refresh: Original routine entry point, retaining all persistence defaults.
        present: Original summary presenter, also available through the facade.
    """

    console: Console
    configuration: Settings
    validate: Callable[[str | None, str | None], tuple[str, str]]
    create_client: LastFmFactory
    refresh: HistoryRefresh
    present: Callable[[Console, history.ScrobbleHistorySummary], None]

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
                summary = self.refresh(
                    lastfm,
                    expected_username=username,
                    dry_run=dry_run,
                    full_rebuild=full_rebuild,
                    progress_callback=status.update,
                )
        except (history.ScrobbleHistoryError, LastFmError) as error:
            self._fail(error)
        self.present(self.console, summary)

    def echo(self, message: str) -> None:
        """Present the original yellow Last.fm event text without a closure.

        Args:
            message: Original client event text, including existing Rich markup.
        """
        self.console.print(message, style="yellow")

    def _client(self) -> tuple[history.LastFmReader, str]:
        try:
            key, username = self.validate(
                self.configuration.lastfm_api_key,
                self.configuration.lastfm_username,
            )
        except found_art.FoundArtConfigError as error:
            self._fail(error)
        return self.create_client(key, username, event_callback=self.echo), username

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
