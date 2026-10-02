"""Compose original manual cursor preflight with caller-owned state and retry."""

from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_cursor import PalaceCursor
from spotify_manager.application.palace_values import AlphabeticalCursorUpdate
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import palace_of_memory as legacy


def _present(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def set_cursor(
    spotify: Spotify,
    position: int,
    albums_path: Path,
    state_path: Path,
    state_service: StateService | None,
    backups: Path,
    refresh_log: Path,
    retry_call: legacy.RetryCall | None,
    callback: legacy.ProgressCallback | None,
) -> AlphabeticalCursorUpdate:
    """Bind original live refresh and complete manual cursor checkpoint behavior.

    Args:
        spotify: Original caller-owned client.
        position: Original one-based requested position.
        albums_path: Original canonical mirror location.
        state_path: Original durable cursor location.
        state_service: Original optional shared authority.
        backups: Original mirror backup directory.
        refresh_log: Original preflight audit location.
        retry_call: Original optional retry policy.
        callback: Original optional stage presenter.

    Returns:
        Original complete manual cursor update.
    """
    retry = retry_call or legacy._direct_retry
    refresh = partial(
        legacy.refresh_saved_albums,
        spotify,
        path=albums_path,
        backups_dir=backups,
        log_path=refresh_log,
        retry_call=retry,
        progress_callback=callback,
    )
    return PalaceCursor(
        partial(_present, callback),
        refresh,
        partial(legacy._state_access, state_path, state_service),
        legacy._cursor_payload,
    ).update(position)
