"""Compose release checking with the original caller-owned boundary dependencies."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.release_check_values import ReleaseCheckSummary
from spotify_manager.application.release_opening import OpenedReleaseRun
from spotify_manager.application.release_progress import ReleaseProgress
from spotify_manager.application.release_run import ReleaseRun
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.infrastructure.legacy.release_run import LegacyReleaseRun
from spotify_manager.routines import release_check as legacy


def run_release_review(
    opening: OpenedReleaseRun,
    state: RoutineState,
    spotify: Spotify,
    playlists: legacy.ReleaseCheckPlaylists,
    log_path: Path,
    artist_reader: legacy.ArtistChoiceReader | None,
    release_reader: legacy.ReleaseChoiceReader | None,
    progress_reader: legacy.ProgressCallback | None,
    retry: legacy.RetryCall,
    preview: bool,
) -> ReleaseCheckSummary:
    """Bind original synchronous seams to the independent business workflow.

    Args:
        opening: Original loaded and copied run observations.
        state: Original acquired state handle.
        spotify: Caller-owned client.
        playlists: Original destinations.
        log_path: Original audit location.
        artist_reader: Original optional mapping interaction.
        release_reader: Original optional release interaction.
        progress_reader: Original optional progress observer.
        retry: Original retry policy.
        preview: Original release preview mode.

    Returns:
        Original complete or paused release-check outcome.
    """
    effects = LegacyReleaseRun(
        spotify, playlists, state, log_path, artist_reader, progress_reader, retry
    )
    progress = ReleaseProgress(
        opening, effects, preview, legacy.ARTIST_PROGRESS_CHECKPOINT_INTERVAL
    )
    return ReleaseRun(
        progress, playlists.wine_cellar, playlists.new_vintage, release_reader
    ).run()
