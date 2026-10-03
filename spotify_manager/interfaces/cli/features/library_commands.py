"""Explicit library commands CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.models.albums import SimplifiedAlbum


@dataclass(kw_only=True)
class LibraryCommandsCLI:
    """Run the supported legacy library commands through their original dependencies.

    Args:
        analyse_comparison: Original live library comparison operation.
        client: Original cached Spotify client factory.
        compare_your_library_and_all_albums: Original export comparison operation.
        convert_your_library_file: Original export conversion operation.
        count_artists_in_library: Original artist counting operation.
        restore_your_library_from_file: Original library restoration operation.
        run_monthly_routines: Original monthly workflow entry point.
        update_total_album_list: Original saved-album pagination operation.
    """

    analyse_comparison: Callable[..., None]
    client: Callable[..., Spotify]
    compare_your_library_and_all_albums: Callable[..., None]
    convert_your_library_file: Callable[..., None]
    count_artists_in_library: Callable[..., int]
    restore_your_library_from_file: Callable[..., None]
    run_monthly_routines: Callable[..., None]
    update_total_album_list: Callable[..., list[SimplifiedAlbum]]

    def _monthly_routines(self) -> None:
        """Run monthly routines."""
        self.compare_your_library_and_all_albums()
        self.convert_your_library_file(self.client())
        self.run_monthly_routines(self.client())

    def _update_total_albums(self, just_update: bool) -> None:
        """Update total album list, optional flag to just add the remaining pages.

        Args:
            just_update: Just update supplied by the caller.
        """
        self.update_total_album_list(self.client(), just_update)

    def _restore_your_library(self) -> None:
        self.restore_your_library_from_file(self.client())

    def _compare_lib_files(self) -> None:
        self.compare_your_library_and_all_albums()

    def _analyse_comp(self) -> None:
        self.analyse_comparison(self.client())

    def _convert_lib(self) -> None:
        self.convert_your_library_file(self.client())

    def _count_artists(self) -> None:
        """Print the number of artists in the YourLibrary file."""
        print(self.count_artists_in_library())
