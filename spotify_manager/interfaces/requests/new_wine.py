"""Interaction callbacks and persistence resources for a New Wine invocation."""

from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.new_wine_values import EndpointChoiceReader
from spotify_manager.application.new_wine_values import ReleaseChoiceReader
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import ReviewProgress
from spotify_manager.core.state import StateService
from spotify_manager.infrastructure.output import STANDARD_OUTPUT


FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class NewWineCallbacks:
    """Own the decisions and notifications for one New Wine run.

    Args:
        choose: Release selection, including skip and quit.
        endpoint: Optional album endpoint selection.
        output: Output sink for decisions and completed effects.
        progress: Optional progress and cancellation callback.
        retry: Caller-owned retry policy, or direct invocation when absent.
    """

    choose: ReleaseChoiceReader
    endpoint: EndpointChoiceReader | None = None
    output: Messages = STANDARD_OUTPUT
    progress: ReviewProgress | None = None
    retry: RetryCall | None = None


@dataclass(frozen=True)
class NewWineStorage:
    """Identify the namespace, mirrors and audit files used by one run.

    Args:
        state_path: Legacy namespace selector or explicit state file.
        state_service: Optional shared state authority.
        log_path: Ordered routine audit destination.
        albums_path: Saved-album mirror.
        liked_tracks_path: Liked-track mirror.
        removed_albums_log_path: Removed-album recovery log.
    """

    state_path: Path = FILES_DIR / "new_wine_flush_state.json"
    state_service: StateService | None = None
    log_path: Path = FILES_DIR / "new_wine_flush_log.jsonl"
    albums_path: Path = FILES_DIR / "albums_total_new.json"
    liked_tracks_path: Path = FILES_DIR / "liked_tracks_total.json"
    removed_albums_log_path: Path = FILES_DIR / "removed_albums_log.jsonl"
