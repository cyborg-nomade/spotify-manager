"""Compose original saved-album live preflight with its application owner."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_mirror import SavedMirror
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.infrastructure.legacy.palace_mirror import LegacySavedMirror
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import palace_of_memory as legacy


def refresh_mirror(
    spotify: Spotify,
    path: Path,
    backups: Path,
    log_path: Path,
    retry_call: legacy.RetryCall | None,
    callback: legacy.ProgressCallback | None,
) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
    """Bind original canonical mirror, backup, retry, clock and audit seams.

    Args:
        spotify: Original caller-owned client.
        path: Original canonical mirror location.
        backups: Original backup directory.
        log_path: Original preflight audit location.
        retry_call: Original optional retry policy.
        callback: Original optional paging presenter.

    Returns:
        Original complete refreshed mirror and preflight result.
    """
    retry = retry_call or legacy._direct_retry
    effects = LegacySavedMirror(spotify, path, backups, log_path, retry, callback)
    return SavedMirror(effects, legacy.ALPHABETICAL_COUNT).run()
