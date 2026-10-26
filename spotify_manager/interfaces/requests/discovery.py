"""Discovery destinations, interaction ownership and persistence resources."""

from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.ports.discovery import (
    DiscoveryInteraction as DiscoveryInteraction,
)
from spotify_manager.core.state import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.routines.scrobble_history import LastFmReader


FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class DiscoveryOptions:
    """Identify review destinations and the requested execution mode.

    Args:
        new_kids_playlist_id: Review destination for New Kids.
        queue_2_playlist_id: Queue source or review destination.
        great_discoveries_2026_playlist_id: Existing yearly promotion seed.
        unlucky_ones_playlist_id: Destination for nonqualifying liked artists.
        newfoundland_playlist_id: Additional qualifying-artist destination.
        dry_run: Suppress playlist writes and checkpoints.
        year: Review year, or the original current-year fallback.
    """

    new_kids_playlist_id: str
    queue_2_playlist_id: str
    great_discoveries_2026_playlist_id: str
    unlucky_ones_playlist_id: str
    newfoundland_playlist_id: str
    dry_run: bool = False
    year: int | None = None


@dataclass(frozen=True)
class DiscoveryResources:
    """Select the history, namespace, mirrors and audit used by one review.

    Args:
        state_path: Namespace selector or explicit legacy state path.
        state_service: Optional checkpoint authority.
        log_path: Original review audit destination.
        albums_path: Canonical saved-album mirror.
        artists_path: Canonical followed-artist mirror.
        removed_albums_log_path: Removed-album recovery log.
        scrobbles_path: Canonical history export.
        lastfm: Optional history reader, also used for previews.
        lastfm_username: Expected history account when a reader is supplied.
    """

    state_path: Path = FILES_DIR / "new_kids_state.json"
    state_service: StateService | None = None
    log_path: Path = FILES_DIR / "new_kids_log.jsonl"
    albums_path: Path = FILES_DIR / "albums_total_new.json"
    artists_path: Path = FILES_DIR / "artists_total.json"
    removed_albums_log_path: Path = FILES_DIR / "removed_albums_log.jsonl"
    scrobbles_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    lastfm: LastFmReader | None = None
    lastfm_username: str | None = None


@dataclass(frozen=True)
class DiscoveryReviewMode:
    """Retain the review's label, checkpoint keys and accepted queue snapshot.

    Args:
        label: Original review label.
        active_key: Checkpoint key advanced by this review.
        blocking_key: Other review's conflicting checkpoint key.
        fill_from_queue: Whether preparation and completion transfer markers.
        initial_tracks: Optional accepted review snapshot.
        live_tracks: Optional projected queue membership.
    """

    label: str = "New Kids"
    active_key: str = "active_run"
    blocking_key: str = "queue_2_active_run"
    fill_from_queue: bool = True
    initial_tracks: list[PlaylistTrack] | None = None
    live_tracks: list[PlaylistTrack] | None = None
