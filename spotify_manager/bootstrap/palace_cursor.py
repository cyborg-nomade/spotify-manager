"""Compose original manual cursor preflight with caller-owned state and retry."""

from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_cursor import PalaceCursor
from spotify_manager.bootstrap.palace_mirror import saved_mirror
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import palace_of_memory as legacy


def _present(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def palace_cursor(
    spotify: Spotify,
    albums_path: Path,
    state_path: Path,
    state_service: StateService | None,
    backups: Path,
    refresh_log: Path,
    retry_call: legacy.RetryCall | None,
    callback: legacy.ProgressCallback | None,
) -> PalaceCursor:
    """Construct the invocation dependencies without executing the use case.

    Args:
        spotify: Original caller-owned client.
        albums_path: Original canonical mirror location.
        state_path: Original durable cursor location.
        state_service: Original optional shared authority.
        backups: Original mirror backup directory.
        refresh_log: Original preflight audit location.
        retry_call: Original optional retry policy.
        callback: Original optional stage presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.palace_of_memory import _cursor_payload
    from spotify_manager.routines.palace_of_memory import _direct_retry
    from spotify_manager.routines.palace_of_memory import _state_access

    retry = retry_call or _direct_retry
    refresh = saved_mirror(
        spotify,
        albums_path,
        backups,
        refresh_log,
        retry,
        callback,
    ).run
    return PalaceCursor(
        partial(_present, callback),
        refresh,
        partial(_state_access, state_path, state_service),
        _cursor_payload,
    )
