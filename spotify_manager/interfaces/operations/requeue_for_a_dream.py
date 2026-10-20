"""Invoke requeue for a dream use cases for CLI and HTTP features."""

from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.requeue import flush_requeue as flush_requeue
from spotify_manager.application.requeue_result import (
    RequeueForADreamConfigError as RequeueForADreamConfigError,
)
from spotify_manager.application.requeue_result import (
    RequeueForADreamError as RequeueForADreamError,
)
from spotify_manager.application.requeue_result import (
    RequeueForADreamSummary as RequeueForADreamSummary,
)
from spotify_manager.routines.requeue_for_a_dream import (
    DEFAULT_LOG_PATH as DEFAULT_LOG_PATH,
)
from spotify_manager.routines.requeue_for_a_dream import Echo as Echo
from spotify_manager.routines.requeue_for_a_dream import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.requeue_for_a_dream import RetryCall as RetryCall
from spotify_manager.routines.requeue_for_a_dream import _clock as _clock
from spotify_manager.routines.requeue_for_a_dream import _direct_retry as _direct_retry
from spotify_manager.routines.requeue_for_a_dream import (
    parse_playlist_id as parse_playlist_id,
)


def flush_requeue_for_a_dream(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> RequeueForADreamSummary:
    """Advance the playlist through the application use case.

    Args:
        spotify: Existing synchronous client.
        playlist_id: Already-parsed playlist identifier.
        dry_run: Preview without mutation, final recheck, or audit.
        echo: Mutation message sink.
        progress_callback: Optional progress and cancellation boundary.
        retry_call: Existing interface retry policy, or direct execution.
        log_path: Original JSONL audit destination.

    Returns:
        The original summary, consumed unchanged by CLI and HTTP presenters.

    Raises:
        RequeueForADreamError: A read, head check, or audit fails.
        RuntimeError: The caller interrupts execution through its retry callback.
    """
    from spotify_manager.bootstrap.requeue import requeue_dependencies

    dependencies = requeue_dependencies(
        spotify, retry_call or _direct_retry, echo, progress_callback, log_path, _clock
    )
    return flush_requeue(dependencies, playlist_id, dry_run=dry_run)
