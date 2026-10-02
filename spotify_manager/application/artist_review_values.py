"""Stable artist-review paths, mutable progress and complete results."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Self


def _no_persistence() -> None:
    pass


@dataclass(frozen=True)
class ArtistReviewPaths:
    """Files read and written by the artist review.

    Args:
        artists: Original artists observation.
        liked_tracks: Original liked tracks observation.
        stats_history: Original stats history observation.
        log: Original log observation.
        cache: Original cache observation.
    """

    artists: Path
    liked_tracks: Path
    stats_history: Path
    log: Path
    cache: Path

    @classmethod
    def for_files_dir(cls: type[Self], files_dir: Path) -> Self:
        """Build conventional review paths beneath a files directory.

        Args:
            files_dir: Original base directory.

        Returns:
            Original five conventional file paths.
        """
        return cls(
            artists=files_dir / "artists_total.json",
            liked_tracks=files_dir / "liked_tracks_total.json",
            stats_history=files_dir / "stats_history.json",
            log=files_dir / "artist_review_log.jsonl",
            cache=files_dir / "artist_review_cache.json",
        )


@dataclass
class ArtistReviewState:
    """Completed work and pending automatic Spotify operations.

    Args:
        completed_artist_ids: Original completed artist ids observation.
        pending_unfollows: Original pending unfollows observation.
        pending_queue_moves: Original pending queue moves observation.
        persist: Original persist observation.
    """

    completed_artist_ids: set[str]
    pending_unfollows: dict[str, dict[str, object]]
    pending_queue_moves: dict[str, dict[str, object]]
    persist: Callable[[], None] = field(default=_no_persistence, repr=False)


@dataclass
class ReviewCounts:
    """Mutable counters for one command invocation.

    Args:
        reviewed: Original reviewed observation.
        unfollowed: Original unfollowed observation.
        queued: Original queued observation.
        moved: Original moved observation.
        already_queued: Original already queued observation.
        declined: Original declined observation.
        no_action: Original no action observation.
        skipped: Original skipped observation.
    """

    reviewed: int = 0
    unfollowed: int = 0
    queued: int = 0
    moved: int = 0
    already_queued: int = 0
    declined: int = 0
    no_action: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ArtistReviewSummary:
    """Outcome of one invocation of the artist review.

    Args:
        total_pending_at_start: Original total pending at start observation.
        reviewed: Original reviewed observation.
        unfollowed: Original unfollowed observation.
        queued: Original queued observation.
        moved: Original moved observation.
        already_queued: Original already queued observation.
        declined: Original declined observation.
        no_action: Original no action observation.
        skipped: Original skipped observation.
        paused: Original paused observation.
    """

    total_pending_at_start: int
    reviewed: int
    unfollowed: int
    queued: int
    moved: int
    already_queued: int
    declined: int
    no_action: int
    skipped: int
    paused: bool


def summary_from_counts(
    total: int,
    counts: ReviewCounts,
    paused: bool,
) -> ArtistReviewSummary:
    """Freeze invocation counters into a public summary.

    Args:
        total: Original invocation total including recovered decisions.
        counts: Original accumulated action counts.
        paused: Whether an original interactive quit stopped the run.

    Returns:
        Complete original public result.
    """
    return ArtistReviewSummary(
        total_pending_at_start=total,
        reviewed=counts.reviewed,
        unfollowed=counts.unfollowed,
        queued=counts.queued,
        moved=counts.moved,
        already_queued=counts.already_queued,
        declined=counts.declined,
        no_action=counts.no_action,
        skipped=counts.skipped,
        paused=paused,
    )
