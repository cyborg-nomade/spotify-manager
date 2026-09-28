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
