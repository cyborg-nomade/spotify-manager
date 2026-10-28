"""Stable entry point for the original ordered monthly routine."""

from spotipy import Spotify as LegacySpotify
from spotipy.client import Spotify

from spotify_manager.loaders_savers import load_control_file as load_control_file
from spotify_manager.loaders_savers import (
    load_total_albums_file as load_total_albums_file,
)
from spotify_manager.processors.control_file_processors import (
    get_starting_index as get_starting_index,
)
from spotify_manager.processors.stats_processors import update_stats as update_stats


async def async_run_monthly_routines(sp: Spotify) -> None:
    """Run original monthly stages, retaining legacy false-result handling.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.interfaces.operations.legacy_library import (
        run_monthly_routines as operation,
    )

    return await operation(sp)


def run_monthly_routines(sp: LegacySpotify) -> None:
    """Run original monthly stages, retaining legacy false-result handling.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_run_monthly_routines(legacy_spotify(sp)))
