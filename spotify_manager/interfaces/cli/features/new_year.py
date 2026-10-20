"""Explicit new year CLI execution, prompts and presentation."""

from dataclasses import dataclass

from rich.console import Console

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client as create_lastfm_client
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import new_year as new_year


@dataclass(kw_only=True)
class NewYearCLI:
    """Run the annual retrospective and present its result.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        create_console: Interface presentation resource.
    """

    runtime: CliResources

    create_console: type[Console]

    def _run_new_year(self, year: int | None, dry_run: bool) -> None:
        """Build the annual retrospective, or preview it without changing Spotify.

        Args:
            year: Year supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        configuration = self.runtime.configuration()
        console = self.create_console()
        key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
        new_year.run_new_year(
            self.runtime.client(),
            create_lastfm_client(LastFmCredentials(key, username), console.print),
            configuration,
            year=year,
            dry_run=dry_run,
            echo=console.print,
        )
