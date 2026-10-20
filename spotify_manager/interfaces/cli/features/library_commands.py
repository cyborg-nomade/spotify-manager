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

    def _monthly_routines(self) -> None:
        """Run monthly routines."""
        operations.compare_your_library_and_all_albums()
        operations.convert_your_library_file(self.runtime.client())
        operations.run_monthly_routines(self.runtime.client())

    def _update_total_albums(self, just_update: bool) -> None:
        """Update total album list, optional flag to just add the remaining pages.

        Args:
            just_update: Just update supplied by the caller.
        """
        operations.update_total_album_list(self.runtime.client(), just_update)

    def _restore_your_library(self) -> None:
        operations.restore_your_library_from_file(self.runtime.client())

    def _compare_lib_files(self) -> None:
        operations.compare_your_library_and_all_albums()

    def _analyse_comp(self) -> None:
        operations.analyse_comparison(self.runtime.client())

    def _convert_lib(self) -> None:
        operations.convert_your_library_file(self.runtime.client())

    def _count_artists(self) -> None:
        """Print the number of artists in the YourLibrary file."""
        print(operations.count_artists_in_library())
