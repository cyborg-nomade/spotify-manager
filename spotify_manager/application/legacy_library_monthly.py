"""Original ordered monthly routine and raw export count."""

from collections.abc import Callable

from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.application.legacy_library_effects import MonthlyActions
from spotify_manager.models.your_library import YourLibraryFile


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
    actions.evaluate(control, albums)
    actions.statistics(control, albums)
    index = actions.starting_index(control, albums)
    echo(f"Starting index: {index}")
    actions.append(control, albums, index)
    echo("Monthly routine complete.")


def count_artists(load: Callable[[], YourLibraryFile]) -> int:
    """Return the original raw artist count, including duplicate entries.

    Args:
        load: Original export read.

    Returns:
        Original artist-list length.
    """
    return len(load().artists)
