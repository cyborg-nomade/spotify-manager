"""Explicit new year CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from spotipy import Spotify

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.routines import found_art
from spotify_manager.routines import new_year
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class NewYearCLI:
    """Execute and present new year through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        create_lastfm: Factory for lastfm instances.
        configuration: Original settings factory supplied by the facade.
        client: Client supplied by the caller.
    """

    create_console: type[Console]
    create_lastfm: type[LastFmClient]
    configuration: type[Settings]
    client: Callable[..., Spotify]

    def _run_new_year(self, year: int | None, dry_run: bool) -> None:
        """Build the annual retrospective, or preview it without changing Spotify.

        Args:
            year: Year supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        configuration = self.configuration()
        console = self.create_console()
        key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
        new_year.run_new_year(
            self.client(),
            self.create_lastfm(key, username, event_callback=console.print),
            configuration,
            year=year,
            dry_run=dry_run,
            echo=console.print,
        )
