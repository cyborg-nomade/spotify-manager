"""Existing Requeue result and errors, shared by use cases and adapters."""

from dataclasses import dataclass
from datetime import datetime

from spotify_manager.domain.requeue import RequeueAction


class RequeueForADreamError(RuntimeError):
    """Base error for Requeue for a Dream flushes."""


class RequeueForADreamConfigError(RequeueForADreamError):
    """Raised when the playlist setting is missing or invalid."""


class RequeueForADreamChangedError(RequeueForADreamError):
    """Raised when the playlist head changes before a real mutation."""


class RequeueForADreamLogError(RequeueForADreamError):
    """Raised when a completed real transition cannot be logged."""


@dataclass(frozen=True)
class RequeueForADreamSummary:
    """Outcome of one playlist-head transition.

    Args:
        recorded_at: Timestamp captured after effects complete.
        playlist_id: Processed playlist identifier.
        dry_run: Whether this was a preview.
        action: Existing transition kind.
        playlist_length_before: Observed initial playlist length.
        playlist_length_after: Predicted resulting length.
        artist: Source artist display name.
        source_track: Source track display name.
        source_release: Source release display name.
        target_track: Replacement track display name.
        target_release: Successor release display name.
        target_release_type: Successor classification.
        target_release_date: Successor chronology date.
        target_already_present: Whether the original playlist contained the replacement.
        reason: Existing explanation for an empty, skipped, or final-release outcome.
    """

    recorded_at: datetime
    playlist_id: str
    dry_run: bool
    action: RequeueAction
    playlist_length_before: int
    playlist_length_after: int
    artist: str | None = None
    source_track: str | None = None
    source_release: str | None = None
    target_track: str | None = None
    target_release: str | None = None
    target_release_type: str | None = None
    target_release_date: str | None = None
    target_already_present: bool = False
    reason: str | None = None
