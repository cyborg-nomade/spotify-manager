"""Original public values for New Kids and Queue 2 application workflows."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.discovery import CatalogTrack


@dataclass(frozen=True)
class ArtistAssessment:
    """Live completion criteria for one artist.

    Args:
        liked_tracks: Unique liked primary-artist track count.
        saved_releases: Saved count across all observed membership statuses.
        total_releases: Catalog entry count, retaining duplicate releases.
        liked_primary_tracks: Unique liked primary-artist track count.
        total_primary_tracks: Unique primary-artist catalog track count.
        qualifies: Whether at least one existing promotion criterion matches.
        reasons: Original promotion messages in evaluation order.
        representative_track: First primary-artist track in preferred chronology.
        top_liked_track: First liked top track, or the catalog popularity fallback.
    """

    liked_tracks: int
    saved_releases: int
    total_releases: int
    liked_primary_tracks: int
    total_primary_tracks: int
    qualifies: bool
    reasons: tuple[str, ...]
    representative_track: CatalogTrack | None
    top_liked_track: CatalogTrack | None


class NewKidsError(RuntimeError):
    """Base error for the New Kids routine."""


class NewKidsConfigError(NewKidsError):
    """Raised when a required playlist is not configured."""


class NewKidsStateError(NewKidsError):
    """Raised when durable routine state is malformed or cannot be saved."""


@dataclass(frozen=True)
class FillResult:
    """One Queue 2 marker considered while filling New Kids.

    Args:
        artist: Logical artist display name.
        track: Original queue marker title.
        action: Original outcome classification.
    """

    artist: str
    track: str
    action: Literal["moved", "reconciled", "skipped"]


@dataclass(frozen=True)
class FlushResult:
    """One snapshotted New Kids track decision.

    Args:
        artist: Logical artist display name.
        source_track: Original review marker title.
        source_release: Original source release title.
        current_liked: Observed source membership in Liked Songs.
        consecutive_unliked: Streak after the source observation.
        action: Original outcome classification.
        target_track: Selected replacement title, when present.
        target_release: Selected replacement release, when present.
        release_number: Next release position according to current-year history.
        album_decision: Live keep/remove decision, when evaluated.
        album_liked_tracks: Observed liked count for the evaluated release.
        album_total_tracks: Observed total count for the evaluated release.
        qualification_reasons: Original promotion messages in evaluation order.
        composer_playlist: Accepted owned works-playlist name, when present.
        composer_position: Completed works count in original playlist order.
        composer_limit: Effective works-review cap.
        dry_run: Whether this result describes a preview.
    """

    artist: str
    source_track: str
    source_release: str
    current_liked: bool
    consecutive_unliked: int
    action: Literal[
        "advance",
        "next release",
        "great discovery",
        "unlucky",
        "unfollowed",
        "skip",
    ]
    target_track: str | None = None
    target_release: str | None = None
    release_number: int | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    qualification_reasons: tuple[str, ...] = ()
    composer_playlist: str | None = None
    composer_position: int | None = None
    composer_limit: int | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Complete result of one restart-safe New Kids run.

    Args:
        results: Processed artist outcomes in encounter order.
        prefill: Queue transfer decisions before reviewing markers.
        postfill: Queue transfer decisions after reviewing markers.
        playlist_length_before: Original destination length before prefill.
        playlist_length_after: Destination length after review and optional refill.
        paused: Whether the operator requested a pause.
        resumed: Whether a saved active run was selected.
        dry_run: Whether this result describes a preview.
    """

    results: tuple[FlushResult, ...]
    prefill: tuple[FillResult, ...]
    postfill: tuple[FillResult, ...]
    playlist_length_before: int
    playlist_length_after: int
    paused: bool
    resumed: bool
    dry_run: bool


@dataclass(frozen=True)
class Queue2Summary:
    """Complete result of one restart-safe Queue 2 run.

    Args:
        results: Processed artist outcomes in encounter order.
        prefill: Queue transfer decisions before reviewing markers.
        queue_length_before: Original Queue 2 length before prefill.
        queue_length_after: Queue 2 length after the review.
        new_kids_length_before: Original New Kids length before prefill.
        new_kids_length_after: New Kids length after prefill.
        paused: Whether the operator requested a pause.
        resumed: Whether a saved active run was selected.
        dry_run: Whether this result describes a preview.
    """

    results: tuple[FlushResult, ...]
    prefill: tuple[FillResult, ...]
    queue_length_before: int
    queue_length_after: int
    new_kids_length_before: int
    new_kids_length_after: int
    paused: bool
    resumed: bool
    dry_run: bool
