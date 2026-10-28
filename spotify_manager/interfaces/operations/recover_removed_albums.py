"""Invoke recover removed albums use cases for CLI and HTTP features."""

import asyncio
from dataclasses import dataclass
from datetime import date as date
from functools import partial as partial
from pathlib import Path as Path

from spotify_manager.application.album_recovery import recover_albums as recover_albums
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.recovery_values import (
    RecoverySummary as RecoverySummary,
)
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.infrastructure.legacy.album_recovery import (
    LegacyAlbumRecovery as LegacyAlbumRecovery,
)
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_MAX_ATTEMPTS as TRANSIENT_MAX_ATTEMPTS,
)
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_RETRY_DELAY_SECONDS as TRANSIENT_RETRY_DELAY_SECONDS,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyRateLimitError as SpotifyRateLimitError,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyTransientServerError as SpotifyTransientServerError,
)
from spotify_manager.interfaces.presenters.album_recovery import (
    RecoveryPresenter as RecoveryPresenter,
)
from spotify_manager.routines.recover_removed_albums import _CLOCK_RESOURCE
from spotify_manager.routines.recover_removed_albums import (
    RECOVERY_LOG_PATH as RECOVERY_LOG_PATH,
)
from spotify_manager.routines.recover_removed_albums import Echo as Echo
from spotify_manager.routines.recover_removed_albums import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.recover_removed_albums import Sleep as Sleep
from spotify_manager.routines.recover_removed_albums import _clock as _clock
from spotify_manager.routines.recover_removed_albums import (
    _default_state as _default_state,
)
from spotify_manager.routines.recover_removed_albums import _today as _today
from spotify_manager.routines.recover_removed_albums import (
    validate_state as validate_state,
)


async def recover_removed_albums(
    sp: Spotify,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    removal_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    recovery_log_path: Path = RECOVERY_LOG_PATH,
    dry_run: bool = False,
    limit: int | None = None,
    today: date | None = None,
    sleep: Sleep = asyncio,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
    state_service: StateService | None = None,
) -> RecoverySummary:
    """Recover artists and future albums through explicit application dependencies.

    Args:
        sp: Caller-owned synchronous client.
        echo: Existing output sink.
        progress_callback: Optional completion and cancellation callback.
        removal_log_path: Original removal history.
        recovery_log_path: Recovery audit destination.
        dry_run: Preview without remote or durable writes.
        limit: Original pending-record slice limit.
        today: Optional fixed comparison date.
        sleep: Existing retry wait callback.
        transient_retry_delay_seconds: Existing retry delay.
        transient_max_attempts: Existing retry limit.
        state_service: Optional shared-state service.

    Returns:
        Original immutable recovery summary.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyTransientServerError: The existing retry policy is exhausted.
        RuntimeError: A response is malformed or a caller interrupts execution.
    """
    library = LegacyAlbumRecovery(
        sp,
        echo,
        removal_log_path,
        recovery_log_path,
        state_service,
        sleep,
        transient_retry_delay_seconds,
        transient_max_attempts,
    )
    return await recover_albums(
        library,
        RecoveryPresenter(echo),
        _CLOCK_RESOURCE,
        RecoveryDate(today),
        dry_run=dry_run,
        limit=limit,
        progress=progress_callback,
    )


@dataclass(frozen=True)
class RecoveryDate:
    """Retain the optional effective calendar value.

    Args:
        override: Original caller-selected date or instant.
    """

    override: date | None

    def today(self) -> date:
        """Observe the original effective date at its existing boundary.

        Returns:
            Original normalized date or instant.
        """
        return _today(self.override)
