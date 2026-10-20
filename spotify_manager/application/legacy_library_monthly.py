"""Original ordered monthly routine and raw export count."""

from spotify_manager.application import legacy_library_control as control_stages
from spotify_manager.application import legacy_library_refresh as playlist_stages
from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.application.legacy_library_effects import MonthlyActions


def run(files: LegacyFiles, actions: MonthlyActions, echo: Echo) -> None:
    """Execute the original monthly stages, retaining ignored false results.

    Args:
        files: Original file reads.
        actions: Original independent public stages.
        echo: Original presenter.
    """
    echo("Running monthly routines...")
    control = files.control()
    albums = files.albums()
    control_stages.check(control, albums, actions.catalog, files, echo)
    control_stages.update_statistics(control, albums, files, echo)
    index = control_stages.starting_index(control, albums, echo)
    echo(f"Starting index: {index}")
    playlist_stages.add_monthly(actions.playlist, control, albums, index, echo)
    echo("Monthly routine complete.")


def count_artists(files: LegacyFiles) -> int:
    """Return the original raw artist count, including duplicate entries.

    Args:
        files: Export storage owner.

    Returns:
        Original artist-list length.
    """
    return len(files.export().artists)
