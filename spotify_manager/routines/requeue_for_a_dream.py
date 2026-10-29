"""Advance the first Requeue for a Dream artist to their next studio release."""

import json
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.music import NamedTrack
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.requeue_result import (
    RequeueForADreamChangedError as RequeueForADreamChangedError,
)
from spotify_manager.application.requeue_result import (
    RequeueForADreamConfigError as RequeueForADreamConfigError,
)
from spotify_manager.application.requeue_result import (
    RequeueForADreamError as RequeueForADreamError,
)
from spotify_manager.application.requeue_result import (
    RequeueForADreamLogError as RequeueForADreamLogError,
)
from spotify_manager.application.requeue_result import (
    RequeueForADreamSummary as RequeueForADreamSummary,
)
from spotify_manager.domain.requeue import RequeueAction as RequeueAction
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.python_compat.retry import (
    BlockingRetry as LegacyRetry,
)
from spotify_manager.routines import new_wine
from spotify_manager.routines import slow_listening as slow_listening


# UFI


type ProgressCallback = Messages


type Echo = Messages


type RetryCall = Retry


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_LOG_PATH = FILES_DIR / "requeue_for_a_dream_log.jsonl"


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Requeue for a Dream playlist id.

    Args:
        reference: Configured identifier, URI, or share link.

    Returns:
        The original parsed playlist identifier.

    Raises:
        RequeueForADreamConfigError: The setting is absent or malformed.
    """
    try:
        return new_wine.parse_playlist_id(
            reference,
            "REQEUEUE_FOR_A_DREAM_PLAYLIST",
        )
    except new_wine.NewWineConfigError as exc:
        raise RequeueForADreamConfigError(str(exc)) from exc


async def _add_track(
    spotify: Spotify,
    playlist_id: str,
    track: NamedTrack,
    retry_call: RetryCall,
) -> None:
    """Append the replacement before the source is removed."""
    for attempt in retry_call.attempts(f"adding {track.name} to Requeue for a Dream"):
        async with attempt:
            await _post_track(spotify, playlist_id, track)


async def _remove_track(
    spotify: Spotify,
    playlist_id: str,
    track: NamedTrack,
    retry_call: RetryCall,
) -> None:
    """Remove the old playlist marker after its replacement is secure."""
    for attempt in retry_call.attempts(
        f"removing {track.name} from Requeue for a Dream"
    ):
        async with attempt:
            await _delete_track(spotify, playlist_id, track)


async def _post_track(spotify: Spotify, playlist_id: str, track: NamedTrack) -> object:
    return await spotify._post(
        f"playlists/{playlist_id}/items",
        payload={"uris": [track.uri]},
    )


async def _delete_track(
    spotify: Spotify, playlist_id: str, track: NamedTrack
) -> object:
    return await spotify._delete(
        f"playlists/{playlist_id}/items",
        payload={"items": [{"uri": track.uri}]},
    )


def _append_log(summary: RequeueForADreamSummary, path: Path) -> None:
    """Append one completed real transition to the review log."""
    record = asdict(summary)
    record["recorded_at"] = summary.recorded_at.isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise RequeueForADreamLogError(
            f"Could not write Requeue for a Dream log: {path}"
        ) from exc


def _clock() -> datetime:
    return datetime.now(UTC)


class ClockClock:
    """Observe the original clock source directly."""

    def now(self) -> datetime:
        """Read the original clock at the same execution boundary.

        Returns:
            Original observed value.
        """
        return _clock()


_CLOCK_RESOURCE = ClockClock()


async def async_flush_requeue_for_a_dream(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool = False,
    echo: Echo = STANDARD_OUTPUT,
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
    from spotify_manager.interfaces.operations.requeue_for_a_dream import (
        flush_requeue_for_a_dream as operation,
    )

    return await operation(
        spotify,
        playlist_id,
        dry_run=dry_run,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        log_path=log_path,
    )


def flush_requeue_for_a_dream(
    spotify: LegacySpotify,
    playlist_id: str,
    *,
    dry_run: bool = False,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None | LegacyRetry = None,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.retry import PythonRetry
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_flush_requeue_for_a_dream(
            legacy_spotify(spotify),
            playlist_id,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=PythonRetry(retry_call) if retry_call is not None else None,
            log_path=log_path,
        )
    )
