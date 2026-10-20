"""Invoke slow listening use cases for CLI and HTTP features."""

from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.slow_listening import (
    flush_slow_listening as execute_flush_slow_listening,
)
from spotify_manager.application.slow_listening_values import FlushResult as FlushResult
from spotify_manager.application.slow_listening_values import (
    FlushSummary as FlushSummary,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningCancelledError as SlowListeningCancelledError,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningConfigError as SlowListeningConfigError,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningError as SlowListeningError,
)
from spotify_manager.bootstrap.slow_listening import slow_listening_dependencies
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.domain.catalog import DiscographyRelease as DiscographyRelease
from spotify_manager.routines.slow_listening import CHOICE_ADVANCE as CHOICE_ADVANCE
from spotify_manager.routines.slow_listening import CHOICE_QUIT as CHOICE_QUIT
from spotify_manager.routines.slow_listening import CHOICE_SKIP as CHOICE_SKIP
from spotify_manager.routines.slow_listening import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.slow_listening import (
    DEFAULT_STATE_PATH as DEFAULT_STATE_PATH,
)
from spotify_manager.routines.slow_listening import (
    CompletionNotifier as CompletionNotifier,
)
from spotify_manager.routines.slow_listening import Echo as Echo
from spotify_manager.routines.slow_listening import ProgressCallback as ProgressCallback
from spotify_manager.routines.slow_listening import (
    ReleaseOrderReader as ReleaseOrderReader,
)
from spotify_manager.routines.slow_listening import RetryCall as RetryCall
from spotify_manager.routines.slow_listening import (
    TrackActionReader as TrackActionReader,
)
from spotify_manager.routines.slow_listening import _clock as _clock
from spotify_manager.routines.slow_listening import _default_state as _default_state
from spotify_manager.routines.slow_listening import (
    parse_playlist_id as parse_playlist_id,
)
from spotify_manager.routines.slow_listening import validate_state as validate_state


def flush_slow_listening(
    sp: Spotify,
    playlist_id: str,
    order_reader: ReleaseOrderReader,
    completion_notifier: CompletionNotifier,
    *,
    action_reader: TrackActionReader | None = None,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> FlushSummary:
    """Advance the first two Slow Listening entries through explicit integrations.

    Args:
        sp: Caller-owned synchronous Spotify client.
        playlist_id: Configured Slow Listening playlist.
        order_reader: Operator's equal-date release ordering callback.
        completion_notifier: Completion acknowledgement callback.
        action_reader: Optional per-track advance, skip or quit callback.
        dry_run: Preview without playlist or checkpoint writes; audits are retained.
        echo: Existing message sink.
        progress_callback: Optional progress/cancellation callback.
        retry_call: Optional original retry policy.
        state_path: Original durable namespace location.
        state_service: Optional explicit shared-state service.
        log_path: Original audit destination.

    Returns:
        Unchanged summary including pause, resume and result fields.

    Raises:
        SlowListeningError: Observations, choices or durable state are invalid.
    """
    configured = slow_listening_dependencies(
        sp,
        playlist_id,
        order_reader,
        completion_notifier,
        action_reader,
        echo,
        progress_callback,
        retry_call,
        state_path,
        state_service,
        log_path,
        _clock,
    )
    return execute_flush_slow_listening(playlist_id, configured, dry_run=dry_run)
