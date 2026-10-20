"""Compose original saved-album live preflight with its application owner."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_mirror import SavedMirror
from spotify_manager.infrastructure.legacy.palace_mirror import LegacySavedMirror
from spotify_manager.routines import palace_of_memory as legacy


def saved_mirror(
    spotify: Spotify,
    path: Path,
    backups: Path,
    log_path: Path,
    retry_call: legacy.RetryCall | None,
    callback: legacy.ProgressCallback | None,
) -> SavedMirror:
    """Construct the invocation dependencies without executing the use case.

    Args:
        spotify: Original caller-owned client.
        path: Original canonical mirror location.
        backups: Original backup directory.
        log_path: Original preflight audit location.
        retry_call: Original optional retry policy.
        callback: Original optional paging presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.palace_of_memory import _direct_retry

    retry = retry_call or _direct_retry
    effects = LegacySavedMirror(spotify, path, backups, log_path, retry, callback)
    return SavedMirror(effects, legacy.ALPHABETICAL_COUNT)
