"""Explicit library commands CLI execution, prompts and presentation."""

from dataclasses import dataclass

from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.operations import legacy_library as operations


@dataclass(kw_only=True)
class LibraryCommandsCLI:
    """Run the original ordered library maintenance commands.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
    """

    runtime: CliResources

    async def _monthly_routines(self) -> None:
        """Run monthly routines."""
        await operations.compare_your_library_and_all_albums()
        await operations.convert_your_library_file(await self.runtime.client())
        await operations.run_monthly_routines(await self.runtime.client())

    async def _update_total_albums(self, just_update: bool) -> None:
        """Update total album list, optional flag to just add the remaining pages.

        Args:
            just_update: Just update supplied by the caller.
        """
        await operations.update_total_album_list(
            (await self.runtime.client()), just_update
        )

    async def _restore_your_library(self) -> None:
        await operations.restore_your_library_from_file(await self.runtime.client())

    async def _compare_lib_files(self) -> None:
        await operations.compare_your_library_and_all_albums()

    async def _analyse_comp(self) -> None:
        await operations.analyse_comparison(await self.runtime.client())

    async def _convert_lib(self) -> None:
        await operations.convert_your_library_file(await self.runtime.client())

    async def _count_artists(self) -> None:
        """Print the number of artists in the YourLibrary file."""
        print(await operations.count_artists_in_library())
