"""Original library commands HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.interfaces.http.models.common import CommandResult
from spotify_manager.interfaces.http.models.common import CountResult
from spotify_manager.models.albums import SimplifiedAlbum


@dataclass(kw_only=True)
class LibraryCommandsHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        analyse_comparison: Existing overridable feature dependency.
        compare_your_library_and_all_albums: Existing overridable feature dependency.
        convert_your_library_file: Existing overridable feature dependency.
        count_artists_in_library: Existing overridable feature dependency.
        restore_your_library_from_file: Existing overridable feature dependency.
        run_monthly_routines: Existing overridable feature dependency.
        update_total_album_list: Existing overridable feature dependency.
    """

    analyse_comparison: Callable[..., None]
    compare_your_library_and_all_albums: Callable[..., None]
    convert_your_library_file: Callable[..., None]
    count_artists_in_library: Callable[..., int]
    restore_your_library_from_file: Callable[..., None]
    run_monthly_routines: Callable[..., None]
    update_total_album_list: Callable[..., list[SimplifiedAlbum]]

    def cmd_monthly_routines(self, client: Spotify) -> CommandResult:
        """Run the full monthly routine (compare, convert, monthly).

        Args:
            client: Original validated client value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        self.compare_your_library_and_all_albums()
        self.convert_your_library_file(client)
        self.run_monthly_routines(client)
        return CommandResult(command="monthly_routines")

    def cmd_update_total_albums(
        self, client: Spotify, just_update: bool
    ) -> CommandResult:
        """Update the total album list.

        Args:
            client: Original validated client value.
            just_update: Original validated just update value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        albums = self.update_total_album_list(client, just_update)
        return CommandResult(
            command=("update_total_albums"), detail=(f"{len(albums)} albums in list")
        )

    def cmd_restore_your_library(self, client: Spotify) -> CommandResult:
        """Restore artists and tracks from the YourLibrary file.

        Args:
            client: Original validated client value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        self.restore_your_library_from_file(client)
        return CommandResult(command="restore_your_library")

    def cmd_compare_lib_files(self) -> CommandResult:
        """Create the comparison between YourLibrary and the total-albums file.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        self.compare_your_library_and_all_albums()
        return CommandResult(command="compare_lib_files")

    def cmd_analyse_comp(self, client: Spotify) -> CommandResult:
        """Analyse the saved comparison file against the live library.

        Args:
            client: Original validated client value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        self.analyse_comparison(client)
        return CommandResult(command="analyse_comp")

    def cmd_convert_lib(self, client: Spotify) -> CommandResult:
        """Convert the YourLibrary file into the total-albums file.

        Args:
            client: Original validated client value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        self.convert_your_library_file(client)
        return CommandResult(command="convert_lib")

    def cmd_count_artists(self) -> CountResult:
        """Count the artists in the YourLibrary file.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return CountResult(count=self.count_artists_in_library())
