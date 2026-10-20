"""Validate and present library commands HTTP requests."""

from spotipy import Spotify

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.common import CommandResult
from spotify_manager.interfaces.http.models.common import CountResult


def cmd_monthly_routines(client: Spotify) -> CommandResult:
    """Run the full monthly routine (compare, convert, monthly).

    Args:
        client: Original validated client value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    jobs.compare_your_library_and_all_albums()
    jobs.convert_your_library_file(client)
    jobs.run_monthly_routines(client)
    return CommandResult(command="monthly_routines")


def cmd_update_total_albums(client: Spotify, just_update: bool) -> CommandResult:
    """Update the total album list.

    Args:
        client: Original validated client value.
        just_update: Original validated just update value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    albums = jobs.update_total_album_list(client, just_update)
    return CommandResult(
        command="update_total_albums", detail=f"{len(albums)} albums in list"
    )


def cmd_restore_your_library(client: Spotify) -> CommandResult:
    """Restore artists and tracks from the YourLibrary file.

    Args:
        client: Original validated client value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    jobs.restore_your_library_from_file(client)
    return CommandResult(command="restore_your_library")


def cmd_compare_lib_files() -> CommandResult:
    """Create the comparison between YourLibrary and the total-albums file.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    jobs.compare_your_library_and_all_albums()
    return CommandResult(command="compare_lib_files")


def cmd_analyse_comp(client: Spotify) -> CommandResult:
    """Analyse the saved comparison file against the live library.

    Args:
        client: Original validated client value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    jobs.analyse_comparison(client)
    return CommandResult(command="analyse_comp")


def cmd_convert_lib(client: Spotify) -> CommandResult:
    """Convert the YourLibrary file into the total-albums file.

    Args:
        client: Original validated client value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    jobs.convert_your_library_file(client)
    return CommandResult(command="convert_lib")


def cmd_count_artists() -> CountResult:
    """Count the artists in the YourLibrary file.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return CountResult(count=jobs.count_artists_in_library())
