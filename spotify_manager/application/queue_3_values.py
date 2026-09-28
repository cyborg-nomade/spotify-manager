"""Queue 3 errors and annual import results, independent of external services."""

from dataclasses import dataclass
from typing import Literal


type SeedAction = Literal["added", "would add", "already present"]


class Queue3Error(RuntimeError):
    """Base error for Queue 3 operations."""


class Queue3ConfigError(Queue3Error):
    """Raised when Queue 3 or its yearly source cannot be resolved."""


class Queue3StateError(Queue3Error):
    """Raised when restart state cannot be read or written safely."""


class Queue3CancelledError(Queue3Error):
    """Raised when an interactive release decision is cancelled."""


@dataclass(frozen=True)
class AnnualImportResult:
    """One previous-year Great Discoveries marker considered for Queue 3.

    Args:
        artist: Primary artist display name.
        track: Original marker title.
        source_year: Year of the source discovery playlist.
        action: Accepted import decision or its preview.
    """

    artist: str
    track: str
    source_year: int
    action: SeedAction


@dataclass(frozen=True)
class AnnualImportSummary:
    """Outcome of an independently requested previous-year import.

    Args:
        active_year: Year of this import checkpoint.
        source_year: Previous year used to find the source playlist.
        additions: Number of new artists added or proposed.
        already_present: Number of source artists already in the queue.
        already_completed: Whether the saved annual checkpoint suppressed import.
        dry_run: Whether writes were suppressed.
        results: Artist decisions in original source order.
    """

    active_year: int
    source_year: int
    additions: int
    already_present: int
    already_completed: bool
    dry_run: bool
    results: tuple[AnnualImportResult, ...]


type FlushAction = Literal[
    "advance", "composer playlist", "next release", "complete", "skip"
]


@dataclass(frozen=True)
class FlushResult:
    """One snapshotted Queue 3 artist transition.

    Args:
        artist: Logical artist display name.
        source_track: Original marker title.
        source_release: Original source release title.
        action: Public transition action.
        target_track: Accepted replacement title, when available.
        target_release: Accepted replacement release, when available.
        album_decision: Live completed-release keep/remove decision.
        album_liked_tracks: Live liked track count for an evaluated release.
        album_total_tracks: Observed complete evaluated track count.
        composer_playlist: Selected owned works playlist name, when available.
        reason: Original explanation of the transition.
        dry_run: Whether the transition is a preview.
    """

    artist: str
    source_track: str
    source_release: str
    action: FlushAction
    target_track: str | None = None
    target_release: str | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    composer_playlist: str | None = None
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one restart-safe Queue 3 run.

    Args:
        run_id: Original durable run identifier.
        total: Number of snapshotted artists.
        processed: Transitions completed in this invocation.
        advanced: Within-release and composer-playlist advances.
        changed_releases: Accepted chronological release transitions.
        completed_artists: Artists reaching the end of their catalog.
        skipped: Artists whose marker cannot be advanced.
        annual_import: Annual source decisions preceding this review.
        paused: Whether an operator choice paused the review.
        dry_run: Whether effects are previews.
        resumed: Whether an existing active run was resumed.
        results: Public transitions completed in this invocation.
    """

    run_id: str
    total: int
    processed: int
    advanced: int
    changed_releases: int
    completed_artists: int
    skipped: int
    annual_import: tuple[AnnualImportResult, ...]
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]
