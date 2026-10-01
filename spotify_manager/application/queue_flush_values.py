"""Original Queue flush result contracts and gathered restart facts."""

from dataclasses import dataclass

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.queue_flush_decision import FlushAction as FlushAction


@dataclass(frozen=True)
class FlushResult:
    """Original snapshotted decision for one Queue artist.

    Args:
        artist: Original primary artist display name.
        source_track: Original source marker title.
        action: Original observed action.
        top_tracks: Original bounded top-track count.
        top_liked_tracks: Original liked top-track count.
        total_liked_tracks: Original liked primary-catalog count.
        target_track: Original optional selected marker title.
        target_release: Original optional promotion release title.
        reason: Original optional decision explanation.
        dry_run: Original preview behavior.
    """

    artist: str
    source_track: str
    action: FlushAction
    top_tracks: int
    top_liked_tracks: int
    total_liked_tracks: int
    target_track: str | None = None
    target_release: str | None = None
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Original outcome of one restart-safe Queue flush.

    Args:
        run_id: Original durable run identity or preview fallback.
        playlist_length_before: Original live Queue length.
        playlist_length_after: Original final distinct URI count.
        total: Original stored entry count.
        processed: Original completed outcomes in this invocation.
        resumed: Whether the original stored run was authoritative.
        dry_run: Original preview behavior.
        results: Original ordered completed outcomes.
    """

    run_id: str
    playlist_length_before: int
    playlist_length_after: int
    total: int
    processed: int
    resumed: bool
    dry_run: bool
    results: tuple[FlushResult, ...]


@dataclass
class QueueFlushFacts:
    """Retain caller-owned stored entries and original live membership observations.

    Args:
        run: Original authoritative mutable run.
        entries: Original stored entries in original order.
        tracks: Original initial live Queue observations.
        live_ids: Original distinct live track identities.
        live_uris: Original distinct live track URIs.
        queue_2_artists: Original promotion destination membership.
        unlucky_artists: Original unlucky destination membership.
        resumed: Whether the original stored run was authoritative.
    """

    run: dict[str, object]
    entries: list[object]
    tracks: tuple[PlaylistTrack, ...]
    live_ids: set[str]
    live_uris: set[str]
    queue_2_artists: set[str]
    unlucky_artists: set[str]
    resumed: bool
