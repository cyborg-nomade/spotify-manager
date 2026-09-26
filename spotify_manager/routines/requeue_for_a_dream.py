"""Advance the first Requeue for a Dream artist to their next studio release."""

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.music import NamedTrack
from spotify_manager.application.requeue import flush_requeue
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

# UFI
from spotify_manager.routines import new_wine
from spotify_manager.routines import slow_listening as slow_listening


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_LOG_PATH = FILES_DIR / "requeue_for_a_dream_log.jsonl"
RetryCall = Callable[[Callable[[], object], str], object]
Echo = Callable[[str], None]
ProgressCallback = Callable[[str], None]


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


def _add_track(
    spotify: Spotify,
    playlist_id: str,
    track: NamedTrack,
    retry_call: RetryCall,
) -> None:
    """Append the replacement before the source is removed."""
    retry_call(
        partial(_post_track, spotify, playlist_id, track),
        f"adding {track.name} to Requeue for a Dream",
    )


def _remove_track(
    spotify: Spotify,
    playlist_id: str,
    track: NamedTrack,
    retry_call: RetryCall,
) -> None:
    """Remove the old playlist marker after its replacement is secure."""
    retry_call(
        partial(_delete_track, spotify, playlist_id, track),
        f"removing {track.name} from Requeue for a Dream",
    )


def _post_track(spotify: Spotify, playlist_id: str, track: NamedTrack) -> object:
    return spotify._post(
        f"playlists/{playlist_id}/items",
        payload={"uris": [track.uri]},
    )


def _delete_track(spotify: Spotify, playlist_id: str, track: NamedTrack) -> object:
    return spotify._delete(
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


def _direct_retry(operation: Callable[[], object], _description: str) -> object:
    return operation()


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
