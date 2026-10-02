"""Stable jobs HTTP request/response contracts."""

from typing import Any

from pydantic import BaseModel
from pydantic import Field

from .analysis import AnalysisJobLog
from .common import JobStatus
from .discography import DiscographyArtistResult
from .discography import DiscographyPendingChoice
from .discovery import NewKidsFillResult
from .discovery import NewKidsPendingChoice
from .discovery import NewKidsTrackResult
from .discovery import Queue3AnnualImportEntry
from .discovery import Queue3PendingChoice
from .discovery import Queue3TrackResult
from .historical import BlastSelectionResult
from .historical import DormantArtistResultEntry
from .palace import PalaceAlbumRefreshResult
from .palace import PalaceAlbumSelectionResult
from .queue import QueueFillResultEntry
from .queue import QueueFlushResultEntry
from .queue import QueuePendingChoice
from .recommendations import FoundArtSelectionResult
from .recommendations import SauvignonPendingChoice
from .recommendations import SauvignonSelectionResult
from .releases import ReleaseCheckPendingChoice
from .releases import ReleaseCheckResultEntry
from .slow_listening import SlowListeningPendingChoice
from .slow_listening import SlowListeningTrackResult
from .something_old import SomethingOldPendingChoice
from .something_old import SomethingOldRankingEntry
from .something_old import SomethingOldTrackResult
from .wine import NewWinePendingChoice
from .wine import NewWineRefillResult
from .wine import NewWineTrackResult


class BlastJobResult(BaseModel):
    """Pollable state for one Last.fm-based playlist job."""

    job_id: str
    command: str = "blast_from_the_past"
    status: JobStatus = "queued"
    detail: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    run_id: str | None = None
    requested_count: int | None = None
    playlist_length_before: int | None = None
    playlist_length_after: int | None = None
    added: int | None = None
    random_org_timestamp: str | None = None
    target_dates: list[str] = Field(default_factory=list)
    missing_dates: list[str] = Field(default_factory=list)
    selections: list[BlastSelectionResult] = Field(default_factory=list)
    dormant_artist_years: list[int] = Field(default_factory=list)
    dormant_artist_current_year: int | None = None
    dormant_artist_represented: int | None = None
    dormant_artist_results: list[DormantArtistResultEntry] = Field(default_factory=list)
    week_start: str | None = None
    history_tracks: int | None = None
    history_scrobbles: int | None = None
    history_export_scrobbles: int | None = None
    history_legacy_scrobbles_added: int | None = None
    live_scrobbles_added: int | None = None
    history_persisted: bool | None = None
    history_full_rebuild: bool = False
    history_backup_path: str | None = None
    new_year_result: dict[str, Any] | None = None
    candidate_count: int | None = None
    found_art_results: list[FoundArtSelectionResult] = Field(default_factory=list)
    sauvignon_history_albums: int | None = None
    sauvignon_seed_count: int | None = None
    sauvignon_track_candidate_count: int | None = None
    sauvignon_album_candidate_count: int | None = None
    sauvignon_results: list[SauvignonSelectionResult] = Field(default_factory=list)
    sauvignon_pending_choice: SauvignonPendingChoice | None = None
    dry_run: bool = False
    no_discovery: bool = False
    choose_album_endpoints: bool = False
    processed: int | None = None
    total: int | None = None
    advanced: int | None = None
    dropped: int | None = None
    sent_to_sauvignon: int | None = None
    completed_singles: int | None = None
    skipped: int | None = None
    albums_unsaved: int | None = None
    new_wine_results: list[NewWineTrackResult] = Field(default_factory=list)
    new_wine_refill: NewWineRefillResult | None = None
    pending_choice: NewWinePendingChoice | None = None
    new_kids_results: list[NewKidsTrackResult] = Field(default_factory=list)
    new_kids_prefill: list[NewKidsFillResult] = Field(default_factory=list)
    new_kids_postfill: list[NewKidsFillResult] = Field(default_factory=list)
    new_kids_pending_choice: NewKidsPendingChoice | None = None
    new_kids_resumed: bool = False
    new_kids_paused: bool = False
    queue_history_artists: int | None = None
    queue_seed_count: int | None = None
    queue_max_playlist_length: int | None = None
    queue_fill_results: list[QueueFillResultEntry] = Field(default_factory=list)
    queue_flush_results: list[QueueFlushResultEntry] = Field(default_factory=list)
    queue_pending_choice: QueuePendingChoice | None = None
    queue_resumed: bool = False
    queue_3_results: list[Queue3TrackResult] = Field(default_factory=list)
    queue_3_annual_import: list[Queue3AnnualImportEntry] = Field(default_factory=list)
    queue_3_annual_only: bool = False
    queue_3_annual_import_completed: bool = False
    queue_3_pending_choice: Queue3PendingChoice | None = None
    queue_3_resumed: bool = False
    queue_3_paused: bool = False
    queue_3_changed_releases: int | None = None
    completed_artists: int | None = None
    slow_listening_results: list[SlowListeningTrackResult] = Field(default_factory=list)
    slow_listening_pending_choice: SlowListeningPendingChoice | None = None
    something_old_action: str | None = None
    something_old_artist: str | None = None
    something_old_average_scrobble_date: str | None = None
    something_old_spotify_artist: str | None = None
    something_old_mode: str | None = None
    something_old_release: str | None = None
    something_old_ranking: list[SomethingOldRankingEntry] = Field(default_factory=list)
    something_old_tracks: list[SomethingOldTrackResult] = Field(default_factory=list)
    something_old_pending_choice: SomethingOldPendingChoice | None = None
    release_check_checked_from: str | None = None
    release_check_checked_through: str | None = None
    release_check_resumed: bool = False
    release_check_paused: bool = False
    release_check_wine_cellar_duplicates_removed: int | None = None
    release_check_wine_cellar_added: int | None = None
    release_check_new_vintage_added: int | None = None
    release_check_results: list[ReleaseCheckResultEntry] = Field(default_factory=list)
    release_check_pending_choice: ReleaseCheckPendingChoice | None = None
    discography_start_queue: str | None = None
    discography_next_queue: str | None = None
    discography_total_releases: int | None = None
    discography_days: float | None = None
    discography_open_slots: int | None = None
    discography_removed_artists: int | None = None
    discography_removed_markers: int | None = None
    discography_results: list[DiscographyArtistResult] = Field(default_factory=list)
    discography_pending_choice: DiscographyPendingChoice | None = None
    requeue_action: str | None = None
    requeue_artist: str | None = None
    requeue_source_track: str | None = None
    requeue_source_release: str | None = None
    requeue_target_track: str | None = None
    requeue_target_release: str | None = None
    requeue_target_release_type: str | None = None
    requeue_target_release_date: str | None = None
    requeue_target_already_present: bool | None = None
    palace_cursor_only: bool = False
    palace_alphabetical_reference: str | None = None
    palace_alphabetical_start_index: int | None = None
    palace_alphabetical_next_index: int | None = None
    palace_alphabetical_cursor_overridden: bool = False
    palace_next_album_artist: str | None = None
    palace_next_album: str | None = None
    palace_cutoff_date: str | None = None
    palace_available_dates: int | None = None
    palace_album_refresh: PalaceAlbumRefreshResult | None = None
    palace_results: list[PalaceAlbumSelectionResult] = Field(default_factory=list)
    retry_at: str | None = None
    logs: list[AnalysisJobLog] = Field(default_factory=list)
