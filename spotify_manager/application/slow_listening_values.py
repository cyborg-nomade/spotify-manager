"""Public Slow Listening results and workflow errors, retaining legacy aliases."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


type FlushAction = Literal["advance", "complete", "skip"]
type ReleaseOrderReader = Callable[
    [str, tuple[DiscographyRelease, ...]], tuple[str, ...]
]
type TrackActionReader = Callable[
    [PlaylistTrack, ReleaseTrack, DiscographyRelease], str
]
type CompletionNotifier = Callable[[PlaylistTrack], None]


class SlowListeningError(RuntimeError):
    """Base error for Slow Listening flushes."""


class SlowListeningConfigError(SlowListeningError):
    """Raised when the Slow Listening playlist is not configured."""


class SlowListeningStateError(SlowListeningError):
    """Raised when restart state cannot be read or written safely."""


class SlowListeningCancelledError(SlowListeningError):
    """Raised when interactive release ordering is cancelled."""


@dataclass(frozen=True)
class FlushResult:
    """One planned or completed Slow Listening transition.

    Args:
        source_track: Original marker's display title.
        source_release: Original marker's release title.
        artist: Primary artist's display name.
        action: Original transition classification.
        target_track: Accepted successor title, when present.
        target_release: Selected studio edition title, when present.
        skipped_candidates: Declined candidates encountered while planning.
        reason: Original skip or completion explanation.
        dry_run: Whether this result describes a preview.
    """

    source_track: str
    source_release: str
    artist: str
    action: FlushAction
    target_track: str | None = None
    target_release: str | None = None
    skipped_candidates: tuple[str, ...] = ()
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one Slow Listening invocation.

    Args:
        run_id: Original durable execution identifier.
        total: Number of entries in the saved snapshot.
        processed: Number of results produced by this invocation.
        advanced: Number of advance results.
        completed_artists: Number of completed studio catalogs.
        skipped: Number of ineligible sources.
        paused: Whether the operator quit before finishing the run.
        dry_run: Whether the invocation was a preview.
        resumed: Whether an existing active run was selected.
        results: Results in their original processing order.
    """

    run_id: str
    total: int
    processed: int
    advanced: int
    completed_artists: int
    skipped: int
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]
