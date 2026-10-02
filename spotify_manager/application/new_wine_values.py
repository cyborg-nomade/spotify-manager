"""Public New Wine outcomes and errors, re-exported by the legacy entry point."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack


type FlushAction = Literal["advance", "drop", "sauvignon", "complete single", "skip"]
type ReleaseChoiceReader = Callable[[PlaylistTrack, tuple[ReleaseCandidate, ...]], str]
type EndpointChoiceReader = Callable[
    [PlaylistTrack, tuple[ReleaseTrack, ...], int], str
]


class NewWineError(RuntimeError):
    """Base error for the New Wine flush."""


class NewWineConfigError(NewWineError):
    """Raised when a playlist setting or option is invalid."""


class NewWineStateError(NewWineError):
    """Raised when restart state cannot be read or written safely."""


@dataclass(frozen=True)
class FlushResult:
    """One source track's planned or completed outcome.

    Args:
        source_track: Original playlist marker's title.
        artist: Primary artist display name.
        release: Selected release title.
        release_type: Original release classification.
        current_liked: Observed source membership in Liked Songs.
        consecutive_unliked: Streak after observing the source.
        action: Original transition classification.
        target_track: Selected replacement title, when present.
        album_liked_tracks: Likes observed during album evaluation, if performed.
        album_total_tracks: Evaluated canonical track count, if performed.
        album_unsaved: Whether the album was unsaved or would be unsaved.
        advance_reason: Optional reason for a nonstandard advance.
        drop_reason: Optional reason for dropping the marker.
        continuation_release: Optional follow-up release title.
        continuation_track: Optional follow-up marker title.
        canonical_track_count: Operator-selected canonical length, when present.
        canonical_cutoff_track: Operator-selected endpoint title, when present.
        dry_run: Whether the result describes a preview.
    """

    source_track: str
    artist: str
    release: str
    release_type: str
    current_liked: bool
    consecutive_unliked: int
    action: FlushAction
    target_track: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    album_unsaved: bool = False
    advance_reason: str | None = None
    drop_reason: str | None = None
    continuation_release: str | None = None
    continuation_track: str | None = None
    canonical_track_count: int | None = None
    canonical_cutoff_track: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class CellarRefillResult:
    """One Wine Cellar entry considered during the post-flush refill.

    Args:
        source_track: Original cellar marker's title.
        artist: Primary artist display name.
        action: Transfer, duplicate removal or ineligibility outcome.
        liked_tracks: Observed likes when required for eligibility.
        saved_albums: Observed saved albums when eligibility was checked.
        dry_run: Whether the result describes a preview.
    """

    source_track: str
    artist: str
    action: Literal["moved", "already present", "ineligible"]
    liked_tracks: int | None = None
    saved_albums: int | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class CellarRefillSummary:
    """Outcome of filling available New Wine slots from Wine Cellar.

    Args:
        target_size: Existing destination marker limit.
        before: Unique destination IDs observed before refill.
        after: Unique destination IDs after accepted or previewed transfers.
        added: Number of destination additions.
        removed_from_cellar: Number of source removals.
        ineligible: Number of sources left by the library-affinity rule.
        no_discovery: Whether library affinity was required.
        results: Refill results in processing order.
    """

    target_size: int
    before: int
    after: int
    added: int
    removed_from_cellar: int
    ineligible: int
    no_discovery: bool
    results: tuple[CellarRefillResult, ...]


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one New Wine invocation.

    Args:
        run_id: Original durable execution identifier.
        total: Number of snapshotted entries.
        processed: Results produced during this invocation.
        advanced: Number of advanced markers.
        dropped: Number of dropped markers.
        sent_to_sauvignon: Number of completed albums routed to Sauvignon.
        completed_singles: Number of completed single releases.
        skipped: Number of sources skipped without advancement.
        albums_unsaved: Number of albums unsaved or previewed as unsaved.
        paused: Whether the operator quit before completion.
        dry_run: Whether this invocation is a preview.
        resumed: Whether a saved active run was selected.
        results: Transition results in processing order.
        refill: Optional post-flush cellar summary.
    """

    run_id: str
    total: int
    processed: int
    advanced: int
    dropped: int
    sent_to_sauvignon: int
    completed_singles: int
    skipped: int
    albums_unsaved: int
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]
    refill: CellarRefillSummary | None = None
