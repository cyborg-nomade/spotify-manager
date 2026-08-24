"""FastAPI interface exposing the same logic as the Typer CLI.

Run with::

    uvicorn spotify_manager.api:app --reload

or via the installed script ``spotify-api``.

Artist stats and album evaluation use live Spotify state. Library analyses run
as cancellable background jobs with pollable progress. The parsed export used
by legacy endpoints is cached; call ``POST /library/refresh`` after replacing
``YourLibrary.json``.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from threading import Event
from threading import Lock
from threading import Thread
from typing import Annotated
from typing import Any
from typing import Literal
from uuid import uuid4

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from pydantic import BaseModel
from pydantic import Field
from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.core.state.editor import state_editor_schema
from spotify_manager.core.state.editor import validate_namespace_editor_change
from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.models import canonical_json
from spotify_manager.core.state.models import namespace_value
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.service import StateFactory
from spotify_manager.core.state.service import StateValidator
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import AmbiguousArtistError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import SpotifyLookupResponseError
from spotify_manager.processors.library_lookups import evaluate_album_live
from spotify_manager.processors.library_lookups import get_live_artist_library_stats
from spotify_manager.processors.library_lookups import parse_spotify_lookup_reference
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines import analyse_library as library_analysis
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import daily_mind_radio
from spotify_manager.routines import discography
from spotify_manager.routines import found_art
from spotify_manager.routines import genre_reveal
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import queue_3
from spotify_manager.routines import recover_removed_albums
from spotify_manager.routines import release_check
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import review_artists
from spotify_manager.routines import sauvignon
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import something_old
from spotify_manager.routines import the_queue
from spotify_manager.routines.convert_library_file import analyse_comparison
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import convert_your_library_file
from spotify_manager.routines.convert_library_file import restore_your_library_from_file
from spotify_manager.routines.count_items import count_artists_in_library
from spotify_manager.routines.monthly_routine import run_monthly_routines
from spotify_manager.settings import Settings


class CommandResult(BaseModel):
    """Result of running a side-effecting command endpoint."""

    command: str
    status: str = "completed"
    detail: str | None = None


class SharedStateSnapshot(BaseModel):
    """One revision-guarded snapshot of the complete shared state."""

    revision: str
    document: dict[str, Any]


class SharedStateReplaceRequest(BaseModel):
    """Guarded manual replacement of the complete shared state."""

    expected_revision: str
    document: dict[str, Any]


class SharedStateNamespaceReplaceRequest(BaseModel):
    """Guarded manual replacement of one validated state namespace."""

    expected_revision: str
    value: dict[str, Any]


class SharedStateSummary(BaseModel):
    """Compact metadata for the cockpit state indicator."""

    revision: str
    updated_at: str
    namespaces: dict[str, str]


STATE_NAMESPACE_DEFINITIONS: dict[
    str,
    tuple[StateFactory, StateValidator],
] = {
    "discography": (discography._default_state, discography.validate_state),
    "genre_reveal": (genre_reveal._default_state, genre_reveal.validate_state),
    "new_kids": (new_kids._default_state, new_kids.validate_state),
    "new_wine": (new_wine._default_state, new_wine.validate_state),
    "palace_of_memory": (
        palace_of_memory._default_state,
        palace_of_memory.validate_state,
    ),
    "queue": (the_queue._default_state, the_queue.validate_state),
    "queue_3": (queue_3._default_state, queue_3.validate_state),
    "recover_removed_albums": (
        recover_removed_albums._default_state,
        recover_removed_albums.validate_state,
    ),
    "release_check": (release_check._default_state, release_check.validate_state),
    "review_album_limits": (dict, review_album_limits.validate_review_decisions),
    "review_artists": (review_artists._default_state, review_artists.validate_state),
    "slow_listening": (slow_listening._default_state, slow_listening.validate_state),
}


class CountResult(BaseModel):
    """Number of artists in the YourLibrary file."""

    count: int


JobStatus = Literal[
    "queued",
    "running",
    "waiting",
    "cancelling",
    "cancelled",
    "paused",
    "completed",
    "failed",
]


class AnalysisResourceProgress(BaseModel):
    """Latest progress for one library resource."""

    completed: int = 0
    total: int | None = None
    status: str = "Queued"


class AnalysisJobLog(BaseModel):
    """One timestamped analysis event shown by the web interface."""

    sequence: int
    timestamp: str
    message: str


class AnalysisJobResult(BaseModel):
    """Pollable state for one background library analysis."""

    job_id: str
    command: str
    status: JobStatus = "queued"
    detail: str | None = None
    retry_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    run_id: str | None = None
    backup_dir: str | None = None
    full_rebuild: bool = False
    mirror_resource: library_analysis.ResourceName | None = None
    resources: dict[str, AnalysisResourceProgress]
    logs: list[AnalysisJobLog] = Field(default_factory=list)


class ServerFileStatus(BaseModel):
    """Filesystem update status for one canonical server-side mirror."""

    filename: str
    exists: bool
    updated_at: str | None = None


class LibraryMirrorFilesStatus(BaseModel):
    """Update status for the files consumed by New Wine."""

    files: list[ServerFileStatus]


class BlastSelectionResult(BaseModel):
    """One Last.fm selection and its Spotify playlist outcome."""

    selected_date: str
    page: int
    total_pages: int
    direction: str
    position: int
    lastfm_scrobble: str
    spotify_match: str | None = None
    liked: bool | None = None
    track_similarity: float | None = None
    album_similarity: float | None = None
    qualifying_matches: int = 0
    action: str


class FoundArtSelectionResult(BaseModel):
    """One Last.fm recommendation and its Spotify playlist outcome."""

    artist: str
    track: str
    score: float
    best_match: float
    supporting_seeds: list[str] = Field(default_factory=list)
    base_rank: int
    weekly_rank: float
    spotify_match: str | None = None
    track_similarity: float | None = None
    action: str


class SauvignonAlbumOption(BaseModel):
    """One materially distinct Spotify album edition offered to the user."""

    spotify_id: str
    artist: str
    album: str
    release_type: str
    release_date: str
    total_tracks: int


class SauvignonPendingChoice(BaseModel):
    """Current ambiguous Sauvignon album match shown by the web client."""

    artist: str
    album: str
    score: float
    best_match: float
    base_rank: int
    weekly_rank: float
    supporting_tracks: list[str] = Field(default_factory=list)
    options: list[SauvignonAlbumOption] = Field(default_factory=list)


class SauvignonSelectionResult(BaseModel):
    """One Last.fm-derived album recommendation and its Spotify outcome."""

    artist: str
    album: str
    score: float
    best_match: float
    supporting_tracks: list[str] = Field(default_factory=list)
    base_rank: int
    weekly_rank: float
    spotify_album: str | None = None
    spotify_album_id: str | None = None
    release_type: str | None = None
    release_date: str | None = None
    first_track: str | None = None
    action: str


class SauvignonChoiceRequest(BaseModel):
    """One album edition, skip, or quit choice for Sauvignon discovery."""

    choice: str


class PalaceAlbumSelectionResult(BaseModel):
    """One Palace of Memory album and its resolved first track."""

    source: str
    selected_date: str | None = None
    history_position: int | None = None
    albums_on_date: int | None = None
    artist: str
    album: str
    spotify_album: str | None = None
    first_track: str | None = None
    action: str


class PalaceAlbumRefreshResult(BaseModel):
    """Saved-album mirror refresh details shown by the web client."""

    previous: int
    current: int
    added: int
    removed: int
    skipped: int
    persisted: bool
    backup_path: str | None = None


class NewWineReleaseOption(BaseModel):
    """One release offered while a web flush waits for a choice."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_name: str


class NewWinePendingChoice(BaseModel):
    """Current interactive choice exposed to the web client."""

    artist: str
    source_track: str
    terminal_release: bool = False
    releases: list[NewWineReleaseOption] = Field(default_factory=list)


class NewWineTrackResult(BaseModel):
    """One completed New Wine source-track decision."""

    artist: str
    source_track: str
    release: str
    release_type: str
    current_liked: bool
    consecutive_unliked: int
    action: str
    target_track: str | None = None
    album_unsaved: bool = False
    advance_reason: str | None = None
    drop_reason: str | None = None
    continuation_release: str | None = None
    continuation_track: str | None = None


class NewWineCellarTrackResult(BaseModel):
    """One Wine Cellar entry moved or reconciled by a web flush."""

    artist: str
    source_track: str
    action: str
    liked_tracks: int | None = None
    saved_albums: int | None = None


class NewWineRefillResult(BaseModel):
    """Web representation of the post-flush Wine Cellar refill."""

    target_size: int
    before: int
    after: int
    added: int
    removed_from_cellar: int
    ineligible: int
    no_discovery: bool
    results: list[NewWineCellarTrackResult] = Field(default_factory=list)


class NewWineChoiceRequest(BaseModel):
    """Choice submitted for a waiting New Wine job."""

    choice: str


class NewKidsReleaseOption(BaseModel):
    """One ranked release offered by an interactive New Kids job."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    popularity: int | None = None
    top_track_rank: int | None = None
    saved: bool = False


class NewKidsPendingChoice(BaseModel):
    """Current New Kids release choice exposed to the web client."""

    artist: str
    releases: list[NewKidsReleaseOption] = Field(default_factory=list)


class NewKidsTrackResult(BaseModel):
    """One completed New Kids artist decision."""

    artist: str
    source_track: str
    source_release: str
    current_liked: bool
    consecutive_unliked: int
    action: str
    target_track: str | None = None
    target_release: str | None = None
    release_number: int | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    qualification_reasons: list[str] = Field(default_factory=list)


class NewKidsFillResult(BaseModel):
    """One Queue 2 marker handled while filling New Kids."""

    artist: str
    track: str
    action: str


class NewKidsChoiceRequest(BaseModel):
    """Release or control choice submitted to a waiting New Kids job."""

    choice: str


class QueueArtistOption(BaseModel):
    """One Spotify artist offered for a Last.fm Queue recommendation."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None
    exact_name: bool


class QueuePendingChoice(BaseModel):
    """Current Last.fm-to-Spotify artist mapping shown by the web client."""

    artist: str
    base_rank: int
    score: float
    supporting_seeds: list[str] = Field(default_factory=list)
    candidates: list[QueueArtistOption] = Field(default_factory=list)


class QueueFillResultEntry(BaseModel):
    """One Last.fm Queue recommendation resolved against Spotify."""

    lastfm_artist: str
    score: float
    best_match: float
    supporting_seeds: list[str] = Field(default_factory=list)
    spotify_artist: str | None = None
    spotify_artist_id: str | None = None
    track: str | None = None
    action: str
    followed: bool = False


class QueueFlushResultEntry(BaseModel):
    """One live top-track decision from a Queue flush."""

    artist: str
    source_track: str
    action: str
    top_tracks: int
    top_liked_tracks: int
    total_liked_tracks: int
    target_track: str | None = None
    target_release: str | None = None
    reason: str | None = None


class QueueChoiceRequest(BaseModel):
    """Artist mapping, custom search, skip, or quit choice for Queue fill."""

    choice: str


class Queue3ReleaseOption(BaseModel):
    """One current or next Queue 3 release shown at a boundary."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int


class Queue3ComposerPlaylistOption(BaseModel):
    """One owned composer playlist offered to a Queue 3 job."""

    spotify_id: str
    name: str
    total_tracks: int


class Queue3PendingChoice(BaseModel):
    """Current Queue 3 release or composer-playlist decision."""

    kind: Literal["release", "composer_playlist"]
    artist: str
    source_track: str | None = None
    current_release: Queue3ReleaseOption | None = None
    next_release: Queue3ReleaseOption | None = None
    playlists: list[Queue3ComposerPlaylistOption] = Field(default_factory=list)


class Queue3TrackResult(BaseModel):
    """One completed Queue 3 artist transition."""

    artist: str
    source_track: str
    source_release: str
    action: str
    target_track: str | None = None
    target_release: str | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    composer_playlist: str | None = None
    reason: str | None = None


class Queue3AnnualImportEntry(BaseModel):
    """One previous-year discovery considered during Queue 3 fill-up."""

    artist: str
    track: str
    source_year: int
    action: str


class Queue3ChoiceRequest(BaseModel):
    """Release, composer-playlist, or quit choice for Queue 3."""

    choice: str


class SlowListeningReleaseOption(BaseModel):
    """One equal-date release offered for chronological ordering."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    plain: bool


class SlowListeningPendingChoice(BaseModel):
    """Current Slow Listening interaction exposed to the web client."""

    kind: Literal["track", "release_order", "completion"]
    artist: str
    source_track: str | None = None
    source_release: str | None = None
    target_track: str | None = None
    target_release: str | None = None
    release_date: str | None = None
    releases: list[SlowListeningReleaseOption] = Field(default_factory=list)


class SlowListeningTrackResult(BaseModel):
    """One completed Slow Listening source-track transition."""

    artist: str
    source_track: str
    source_release: str
    action: str
    target_track: str | None = None
    target_release: str | None = None
    skipped_candidates: list[str] = Field(default_factory=list)
    reason: str | None = None


class SlowListeningChoiceRequest(BaseModel):
    """Choice or release ordering submitted to a waiting web job."""

    choice: str
    order: list[str] = Field(default_factory=list)


class SomethingOldArtistOption(BaseModel):
    """One exact-name Spotify artist offered to the web client."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None


class SomethingOldReleaseOption(BaseModel):
    """One filtered studio album or EP offered for Something Old."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    plain: bool


class SomethingOldPendingChoice(BaseModel):
    """Current Something Old interaction exposed to the web client."""

    kind: Literal["artist", "mode", "album"]
    artist: str
    scrobbles: int
    average_scrobble_date: str
    spotify_artist: str | None = None
    artist_candidates: list[SomethingOldArtistOption] = Field(default_factory=list)
    releases: list[SomethingOldReleaseOption] = Field(default_factory=list)


class SomethingOldRankingEntry(BaseModel):
    """One Golden Oldies artist shown in the web ranking preview."""

    artist: str
    scrobbles: int
    average_scrobble_date: str


class SomethingOldTrackResult(BaseModel):
    """One Spotify track selected for Something Old."""

    spotify_id: str
    track: str
    album: str
    artists: list[str]
    source: str
    lastfm_scrobbles: int | None = None


class SomethingOldChoiceRequest(BaseModel):
    """One artist, source mode, album, or quit choice."""

    choice: str


class ReleaseCheckArtistOption(BaseModel):
    """One Spotify artist offered for a Last.fm artist mapping."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None
    exact_name: bool


class ReleaseCheckPendingChoice(BaseModel):
    """Current artist mapping or release approval exposed to the web client."""

    kind: Literal["artist", "release"]
    artist: str
    artist_rank: int
    artist_scrobbles: int
    artist_candidates: list[ReleaseCheckArtistOption] = Field(default_factory=list)
    release: str | None = None
    release_type: str | None = None
    release_date: str | None = None
    first_track: str | None = None
    destinations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    unattached_single: bool = False


class ReleaseCheckResultEntry(BaseModel):
    """One release decision and its destination-playlist outcomes."""

    artist: str
    artist_rank: int
    artist_scrobbles: int
    spotify_artist_id: str
    release_id: str
    release: str
    release_type: str
    release_date: str
    first_track_id: str | None = None
    first_track: str | None = None
    linked_future_release: str | None = None
    wine_cellar_action: str
    new_vintage_action: str
    reason: str | None = None
    dry_run: bool


class ReleaseCheckChoiceRequest(BaseModel):
    """One artist, custom search, release approval, skip, or quit choice."""

    choice: str


class ReleaseCheckStateSnapshot(BaseModel):
    """Versioned release-check state mirrored by the authenticated browser."""

    updated_at: str | None
    fingerprint: str
    state: dict[str, Any] | None = None
    backup_path: str | None = None


class ReleaseCheckStateRestoreRequest(BaseModel):
    """Optimistic restore request for a newer browser-held state copy."""

    expected_server_fingerprint: str
    state: dict[str, Any]


class DiscographyReleaseOption(BaseModel):
    """One canonical release offered in a discography checklist."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    default: bool


class DiscographyPendingChoice(BaseModel):
    """Current release checklist or final confirmation shown by the web client."""

    kind: Literal["releases", "confirm"]
    artist: str | None = None
    queue: str | None = None
    releases: list[DiscographyReleaseOption] = Field(default_factory=list)
    default_release_ids: list[str] = Field(default_factory=list)


class DiscographyArtistResult(BaseModel):
    """One artist selected for the next discography batch."""

    spotify_id: str
    artist: str
    queue: str
    releases: int
    days: float
    release_names: list[str] = Field(default_factory=list)


class DiscographyChoiceRequest(BaseModel):
    """One release checklist, final approval, or cancellation response."""

    choice: str
    release_ids: list[str] = Field(default_factory=list)


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
    week_start: str | None = None
    history_tracks: int | None = None
    history_scrobbles: int | None = None
    history_export_scrobbles: int | None = None
    history_legacy_scrobbles_added: int | None = None
    live_scrobbles_added: int | None = None
    history_persisted: bool | None = None
    history_backup_path: str | None = None
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


@dataclass
class _AnalysisJob:
    """Mutable server-side state and cancellation signal for one job."""

    result: AnalysisJobResult
    cancel_event: Event
    next_log_sequence: int = 1


@dataclass
class _BlastJob:
    """Mutable server-side state for one playlist routine job."""

    result: BlastJobResult
    next_log_sequence: int = 1
    choice_event: Event = dataclass_field(default_factory=Event)
    cancel_event: Event = dataclass_field(default_factory=Event)
    submitted_choice: str | None = None
    submitted_order: tuple[str, ...] | None = None


class _NewWineJobCancelledError(RuntimeError):
    """Stop one web flush while preserving the routine's durable state."""


class _NewKidsJobCancelledError(RuntimeError):
    """Stop one New Kids web job while preserving durable progress."""


class _Queue3JobCancelledError(RuntimeError):
    """Stop one Queue 3 web job while preserving durable progress."""


class _QueueJobCancelledError(RuntimeError):
    """Stop one Queue web job while preserving completed work."""


class _SauvignonJobCancelledError(RuntimeError):
    """Stop one Sauvignon recommendation job at a safe boundary."""


class _SlowListeningJobCancelledError(RuntimeError):
    """Stop one Slow Listening web flush at an interaction boundary."""


class _SomethingOldJobCancelledError(RuntimeError):
    """Stop one Something Old web job at an interaction or retry boundary."""


class _ReleaseCheckJobCancelledError(RuntimeError):
    """Stop one release-check job at an interaction or retry boundary."""


class _DiscographyJobCancelledError(RuntimeError):
    """Stop one discography job at an interaction or retry boundary."""


class _RequeueForADreamJobCancelledError(RuntimeError):
    """Stop one Requeue for a Dream job at an API or retry boundary."""


class _PalaceOfMemoryJobCancelledError(RuntimeError):
    """Stop one Palace of Memory job at an API or retry boundary."""


_analysis_jobs: dict[str, _AnalysisJob] = {}
_analysis_jobs_lock = Lock()
_ACTIVE_JOB_STATUSES = {"queued", "running", "waiting", "cancelling"}
_MAX_ANALYSIS_LOGS = 250
_analysis_logger = logging.getLogger(__name__)
_blast_jobs: dict[str, _BlastJob] = {}
_blast_jobs_lock = Lock()
_MAX_BLAST_LOGS = 250
LIBRARY_MIRROR_FILE_PATHS = (
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.albums_total,
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.liked_tracks_total,
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.artists_total,
    scrobble_history.DEFAULT_SCROBBLES_PATH,
)
RELEASE_CHECK_STATE_PATH = Path(
    os.environ.get("RELEASE_CHECK_STATE_PATH", release_check.DEFAULT_STATE_PATH)
)
RELEASE_CHECK_STATE_BACKUP_DIR = Path(
    os.environ.get(
        "RELEASE_CHECK_STATE_BACKUP_DIR",
        release_check.DEFAULT_STATE_BACKUP_DIR,
    )
)
SPOTIFY_CONNECTION_FAILURE_DETAIL = (
    "Spotify connection remained unavailable after automatic retries. "
    "Please try again shortly."
)


@lru_cache
def get_client() -> Spotify:
    """Provide a cached spotipy client (overridable in tests)."""
    return get_spotipy_client(allow_interactive_auth=False)


@lru_cache
def get_analysis_client() -> Spotify:
    """Provide a client whose retries are controlled by the analysis routine."""
    return get_spotipy_client(
        retries=0,
        status_retries=0,
        status_forcelist=(999,),
        allow_interactive_auth=False,
    )


@lru_cache
def get_interactive_client() -> Spotify:
    """Provide an isolated no-retry client for interactive web routines."""
    return get_spotipy_client(
        retries=0,
        status_retries=0,
        status_forcelist=(999,),
        allow_interactive_auth=False,
    )


@lru_cache
def get_library() -> YourLibraryFile:
    """Provide the parsed YourLibrary.json, cached for the process."""
    return load_your_library_file()


ClientDep = Annotated[Spotify, Depends(get_client)]
AnalysisClientDep = Annotated[Spotify, Depends(get_analysis_client)]
InteractiveClientDep = Annotated[Spotify, Depends(get_interactive_client)]
LibraryDep = Annotated[YourLibraryFile, Depends(get_library)]


def _job_snapshot(job: _AnalysisJob) -> AnalysisJobResult:
    """Return an isolated response model for one mutable job."""
    return job.result.model_copy(deep=True)


def _append_job_log_locked(job: _AnalysisJob, message: str) -> None:
    """Append one bounded log entry while the caller holds the jobs lock."""
    if not message:
        return
    job.result.logs.append(
        AnalysisJobLog(
            sequence=job.next_log_sequence,
            timestamp=datetime.now(UTC).isoformat(),
            message=message,
        )
    )
    job.next_log_sequence += 1
    if len(job.result.logs) > _MAX_ANALYSIS_LOGS:
        del job.result.logs[: len(job.result.logs) - _MAX_ANALYSIS_LOGS]


def _blast_job_snapshot(job: _BlastJob) -> BlastJobResult:
    """Return an isolated response model for one mutable playlist job."""
    return job.result.model_copy(deep=True)


def _append_blast_log_locked(job: _BlastJob, message: str) -> None:
    """Append one bounded playlist-job log entry while holding its lock."""
    if not message:
        return
    job.result.logs.append(
        AnalysisJobLog(
            sequence=job.next_log_sequence,
            timestamp=datetime.now(UTC).isoformat(),
            message=message,
        )
    )
    job.next_log_sequence += 1
    if len(job.result.logs) > _MAX_BLAST_LOGS:
        del job.result.logs[: len(job.result.logs) - _MAX_BLAST_LOGS]


def _release_check_state_snapshot(
    known_fingerprint: str | None = None,
    *,
    backup_path: Path | None = None,
) -> ReleaseCheckStateSnapshot:
    """Load one state snapshot, omitting its body when the browser is current."""
    state = (
        get_state_service()
        .namespace(
            "release_check",
            release_check._default_state,
            release_check.validate_state,
        )
        .load()
    )
    fingerprint = release_check.state_fingerprint(state)
    return ReleaseCheckStateSnapshot(
        updated_at=release_check.state_updated_at(state),
        fingerprint=fingerprint,
        state=None if fingerprint == known_fingerprint else state,
        backup_path=str(backup_path) if backup_path is not None else None,
    )


def _state_timestamp(value: str | None) -> datetime | None:
    """Parse one state freshness timestamp as UTC."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _release_state_is_newer(
    candidate: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    """Return whether a browser-held state is semantically newer."""
    candidate_at = _state_timestamp(release_check.state_updated_at(candidate))
    current_at = _state_timestamp(release_check.state_updated_at(current))
    return candidate_at is not None and (
        current_at is None or candidate_at > current_at
    )


def get_analysis_job(job_id: str) -> _AnalysisJob:
    """Return one job or raise a conventional API 404."""
    with _analysis_jobs_lock:
        job = _analysis_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis job not found")
    return job


def get_blast_job(job_id: str, command: str | None = None) -> _BlastJob:
    """Return one playlist job or raise a conventional API 404."""
    with _blast_jobs_lock:
        job = _blast_jobs.get(job_id)
    if job is None or (command is not None and job.result.command != command):
        raise HTTPException(status_code=404, detail="playlist job not found")
    return job


def _cancel_simple_playlist_job(
    job_id: str,
    *,
    command: str,
    detail: str,
) -> BlastJobResult:
    """Signal a non-interactive playlist worker to stop cleanly."""
    job = get_blast_job(job_id, command=command)
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="Playlist job is not active")
        job.result.status = "cancelling"
        job.result.detail = detail
        _append_blast_log_locked(job, detail)
        job.cancel_event.set()
        return _blast_job_snapshot(job)


def _run_analysis_job(
    job_id: str,
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None,
    full_rebuild: bool = False,
    mirror_resource: library_analysis.ResourceName | None = None,
) -> None:
    """Execute one analysis worker and translate outcomes into job state."""
    job = get_analysis_job(job_id)
    with _analysis_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Analysis started"
        _append_job_log_locked(job, f"{mode.title()} analysis started.")

    def progress_callback(
        resource: library_analysis.ResourceName,
        completed: int,
        total: int | None,
        progress_status: str,
    ) -> None:
        with _analysis_jobs_lock:
            progress = job.result.resources[resource]
            status_changed = progress.status != progress_status
            progress.completed = completed
            progress.total = total
            progress.status = progress_status
            if job.result.status != "cancelling":
                job.result.status = "running"
                job.result.detail = f"{resource.title()}: {progress_status}"
            if status_changed:
                count = str(completed)
                if total is not None:
                    count = f"{completed} / {max(completed, total)}"
                _append_job_log_locked(
                    job,
                    f"{resource.title()}: {progress_status} ({count}).",
                )

    def echo(line: str) -> None:
        with _analysis_jobs_lock:
            _append_job_log_locked(job, line)
            if job.result.status not in {"waiting", "cancelling"}:
                job.result.detail = line

    def retry_wait(notice: library_analysis.RetryNotice) -> bool:
        retry_at = datetime.now(UTC) + timedelta(seconds=notice.delay_seconds)
        failure = (
            f"Spotify HTTP {notice.http_status}"
            if notice.http_status is not None
            else "Spotify connection interrupted"
        )
        with _analysis_jobs_lock:
            job.result.status = "waiting"
            job.result.retry_at = retry_at.isoformat()
            job.result.detail = (
                f"{failure}; retry {notice.attempt} while {notice.operation}"
            )
            _append_job_log_locked(
                job,
                f"Waiting until {retry_at.isoformat()} before retry "
                f"{notice.attempt} after {failure} "
                f"while {notice.operation}. Cancel to save and stop.",
            )
        cancelled = job.cancel_event.wait(notice.delay_seconds)
        with _analysis_jobs_lock:
            job.result.retry_at = None
            if not cancelled:
                job.result.status = "running"
                job.result.detail = "Retrying Spotify request"
                _append_job_log_locked(job, "Retrying Spotify request now.")
        return not cancelled

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        if mode == "async":
            summary = library_analysis.analyse_library_async_routine(
                echo=echo,
                progress_callback=progress_callback,
                cancel_check=job.cancel_event.is_set,
            )
        elif mode == "sync":
            if spotify is None:
                raise library_analysis.LibrarySyncError(
                    "A Spotify client is required for live analysis."
                )
            summary = library_analysis.analyse_library_sync_routine(
                spotify,
                echo=echo,
                progress_callback=progress_callback,
                retry_wait=retry_wait,
                cancel_check=job.cancel_event.is_set,
            )
        elif mirror_resource is None:
            if spotify is None:
                raise library_analysis.LibrarySyncError(
                    "A Spotify client is required for live mirror refresh."
                )
            summary = library_analysis.refresh_live_library_mirrors_routine(
                spotify,
                echo=echo,
                progress_callback=progress_callback,
                retry_wait=retry_wait,
                cancel_check=job.cancel_event.is_set,
                full_rebuild=full_rebuild,
            )
        else:
            if spotify is None:
                raise library_analysis.LibrarySyncError(
                    "A Spotify client is required for live mirror refresh."
                )
            summary = library_analysis.refresh_live_library_resource_routine(
                spotify,
                mirror_resource,
                echo=echo,
                progress_callback=progress_callback,
                retry_wait=retry_wait,
                cancel_check=job.cancel_event.is_set,
                full_rebuild=full_rebuild,
            )
    except library_analysis.LibraryAnalysisCancelledError as exc:
        with _analysis_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = f"{exc} Progress was saved."
            _append_job_log_locked(job, job.result.detail)
    except library_analysis.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _analysis_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = "Spotify rate limit reached. Progress was saved."
            _append_job_log_locked(job, job.result.detail)
    except library_analysis.LibrarySyncError as exc:
        with _analysis_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_job_log_locked(job, f"Analysis failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected library analysis error")
        with _analysis_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected analysis error: {exc}"
            _append_job_log_locked(job, job.result.detail)
    else:
        with _analysis_jobs_lock:
            job.result.status = "completed"
            job.result.detail = "Analysis completed"
            job.result.run_id = summary.run_id
            job.result.backup_dir = summary.backup_dir
            for resource in summary.resources:
                _append_job_log_locked(
                    job,
                    f"{resource.resource.title()}: {resource.previous} -> "
                    f"{resource.current} (+{resource.added}, "
                    f"-{resource.removed}, skipped {resource.skipped}).",
                )
            _append_job_log_locked(
                job,
                f"Analysis completed. Run {summary.run_id}; "
                f"backup {summary.backup_dir}.",
            )
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _analysis_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def start_analysis_job(
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None = None,
    full_rebuild: bool = False,
    mirror_resource: library_analysis.ResourceName | None = None,
) -> AnalysisJobResult:
    """Start one background analysis, rejecting duplicate active modes."""
    if mode == "mirrors" and mirror_resource is not None:
        command = f"refresh_library_mirror_{mirror_resource}"
    else:
        command = (
            "refresh_library_mirrors"
            if mode == "mirrors"
            else f"analyse_library_{mode}"
        )
    is_full_rebuild = mode == "mirrors" and full_rebuild
    resources = (
        (mirror_resource,)
        if mirror_resource is not None
        else (
            ("albums", "tracks")
            if mode == "mirrors"
            else ("albums", "tracks", "artists")
        )
    )
    with _analysis_jobs_lock:
        for existing in _analysis_jobs.values():
            if (
                existing.result.command == command
                and existing.result.status in _ACTIVE_JOB_STATUSES
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "an analysis of this type is already running",
                        "job_id": existing.result.job_id,
                    },
                )
        job_id = uuid4().hex
        job = _AnalysisJob(
            result=AnalysisJobResult(
                job_id=job_id,
                command=command,
                full_rebuild=is_full_rebuild,
                mirror_resource=mirror_resource,
                resources={
                    resource: AnalysisResourceProgress() for resource in resources
                },
            ),
            cancel_event=Event(),
        )
        _append_job_log_locked(job, f"{mode.title()} analysis queued.")
        _analysis_jobs[job_id] = job
        snapshot = _job_snapshot(job)

    Thread(
        target=_run_analysis_job,
        args=(job_id, mode, spotify, full_rebuild, mirror_resource),
        name=f"library-analysis-{mode}-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def _blast_selection_result(
    result: blast_from_past.SpotifySelectionResult,
) -> BlastSelectionResult:
    """Convert one routine result into its stable API representation."""
    selection = result.selection
    scrobble = selection.scrobble
    lastfm_album = scrobble.album or "(no album)"
    spotify_match = None
    liked = None
    track_similarity = None
    album_similarity = None
    if result.match is not None:
        spotify_album = result.match.album or "(no album)"
        spotify_match = (
            f"{', '.join(result.match.artists)} - {result.match.track} - "
            f"{spotify_album}"
        )
        liked = result.match.liked
        track_similarity = result.match.track_similarity
        album_similarity = result.match.album_similarity
    return BlastSelectionResult(
        selected_date=selection.selected_date.isoformat(),
        page=selection.page,
        total_pages=selection.total_pages,
        direction=selection.direction,
        position=selection.position,
        lastfm_scrobble=f"{scrobble.artist} - {scrobble.track} - {lastfm_album}",
        spotify_match=spotify_match,
        liked=liked,
        track_similarity=track_similarity,
        album_similarity=album_similarity,
        qualifying_matches=result.qualifying_matches,
        action=result.action,
    )


def _playlist_job_retry(
    job: _BlastJob,
    echo: Callable[[str], None],
) -> blast_from_past.RetryCall:
    """Build a bounded Spotify retry policy with interruptible waits."""

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise blast_from_past.BlastFromPastCancelledError(
                "Playlist routine cancelled."
            )

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        blast_from_past.check_cancel(job.cancel_event.is_set)
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        blast_from_past.check_cancel(job.cancel_event.is_set)
        return result

    return retry_call


def _run_blast_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
) -> None:
    """Execute one web playlist job and retain progress, logs, and results."""
    job = get_blast_job(job_id)
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Playlist routine started"
        _append_blast_log_locked(job, "A blast from the past started.")

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = blast_from_past.add_blast_from_past_to_spotify(
            spotify,
            playlist_id,
            count=count,
            max_playlist_length=max_playlist_length,
            progress_callback=echo,
            retry_call=_playlist_job_retry(job, echo),
            cancel_check=job.cancel_event.is_set,
        )
    except blast_from_past.BlastFromPastCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = "A blast from the past was cancelled."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = review_album_limits.format_transient_spotify_failure(
                exc
            )
            _append_blast_log_locked(job, job.result.detail)
    except (blast_from_past.BlastFromPastError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Playlist routine failed: {exc}")
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected blast-from-the-past error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected playlist error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        selections = [_blast_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requested_count = summary.requested_count
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.added
            job.result.selections = selections
            if summary.batch is not None:
                job.result.random_org_timestamp = summary.batch.generated_at.isoformat()
            job.result.detail = (
                f"Added {summary.added} of {summary.requested_count} selections; "
                f"playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for selection in selections:
                target = selection.spotify_match or "no qualifying Spotify match"
                liked_label = " liked" if selection.liked else ""
                _append_blast_log_locked(
                    job,
                    f"{selection.selected_date}: {selection.lastfm_scrobble} -> "
                    f"{target} ({selection.action}{liked_label}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_daily_mind_radio_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
) -> None:
    """Execute one Daily Mind Radio web job and retain its complete trace."""
    job = get_blast_job(job_id, command="daily_mind_radio")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Playlist routine started"
        _append_blast_log_locked(job, "Daily Mind Radio started.")

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
            spotify,
            playlist_id,
            progress_callback=echo,
            retry_call=_playlist_job_retry(job, echo),
            cancel_check=job.cancel_event.is_set,
        )
    except blast_from_past.BlastFromPastCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = "Daily Mind Radio was cancelled."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = review_album_limits.format_transient_spotify_failure(
                exc
            )
            _append_blast_log_locked(job, job.result.detail)
    except (blast_from_past.BlastFromPastError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Playlist routine failed: {exc}")
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Daily Mind Radio error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected playlist error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        selections = [_blast_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requested_count = len(summary.batch.selections)
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.added
            job.result.target_dates = [
                target_date.isoformat() for target_date in summary.batch.target_dates
            ]
            job.result.missing_dates = [
                missing_date.isoformat() for missing_date in summary.batch.missing_dates
            ]
            job.result.selections = selections
            if summary.batch.generated_at is not None:
                job.result.random_org_timestamp = summary.batch.generated_at.isoformat()
            if summary.playlist_length_before is None:
                job.result.detail = (
                    "No anniversary dates had scrobbles; nothing was added."
                )
            else:
                job.result.detail = (
                    f"Added {summary.added} of {len(summary.batch.selections)} "
                    f"populated dates; playlist {summary.playlist_length_before} -> "
                    f"{summary.playlist_length_after}."
                )
            for selection in selections:
                target = selection.spotify_match or "no qualifying Spotify match"
                liked_label = " liked" if selection.liked else ""
                _append_blast_log_locked(
                    job,
                    f"{selection.selected_date}: {selection.lastfm_scrobble} -> "
                    f"{target} ({selection.action}{liked_label}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _found_art_selection_result(
    result: found_art.FoundArtResult,
) -> FoundArtSelectionResult:
    """Convert one Found Art result into its stable API representation."""
    spotify_match = None
    track_similarity = None
    if result.match is not None:
        album = result.match.album or "(no album)"
        spotify_match = (
            f"{', '.join(result.match.artists)} - {result.match.track} - {album}"
        )
        track_similarity = result.match.track_similarity
    return FoundArtSelectionResult(
        artist=result.candidate.artist,
        track=result.candidate.track,
        score=result.candidate.score,
        best_match=result.candidate.best_match,
        supporting_seeds=list(result.candidate.supporting_seeds),
        base_rank=result.candidate.base_rank,
        weekly_rank=result.candidate.weekly_rank,
        spotify_match=spotify_match,
        track_similarity=track_similarity,
        action=result.action,
    )


def _run_found_art_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int,
) -> None:
    """Execute one Found Art web job and retain its complete trace."""
    job = get_blast_job(job_id, command="found_art")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Found Art started"
        _append_blast_log_locked(job, "Found Art started.")

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)
    lastfm = LastFmClient(
        api_key,
        username,
        event_callback=echo,
    )

    try:
        summary = found_art.run_found_art(
            spotify,
            lastfm,
            playlist_id,
            count=count,
            progress_callback=echo,
        )
    except (found_art.FoundArtError, LastFmError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Found Art failed: {exc}")
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Found Art error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Found Art error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_found_art_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requested_count = summary.requested_count
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.added
            job.result.week_start = summary.week_start.isoformat()
            job.result.history_tracks = summary.history_tracks
            job.result.history_scrobbles = summary.history_scrobbles
            job.result.live_scrobbles_added = summary.live_scrobbles_added
            job.result.candidate_count = summary.candidate_count
            job.result.found_art_results = results
            job.result.detail = (
                f"Added {summary.added} of {summary.requested_count} "
                f"recommendations; playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = result.spotify_match or "no unliked qualifying match"
                _append_blast_log_locked(
                    job,
                    f"{result.artist} - {result.track} -> {target} ({result.action}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _sauvignon_selection_result(
    result: sauvignon.SauvignonResult,
) -> SauvignonSelectionResult:
    """Convert one Sauvignon album recommendation for stable web polling."""
    album = result.album
    return SauvignonSelectionResult(
        artist=result.recommendation.artist,
        album=result.recommendation.album,
        score=result.recommendation.score,
        best_match=result.recommendation.best_match,
        supporting_tracks=list(result.recommendation.supporting_tracks),
        base_rank=result.recommendation.base_rank,
        weekly_rank=result.recommendation.weekly_rank,
        spotify_album=album.album if album is not None else None,
        spotify_album_id=album.spotify_id if album is not None else None,
        release_type=album.release_type if album is not None else None,
        release_date=album.release_date if album is not None else None,
        first_track=result.first_track.name if result.first_track is not None else None,
        action=result.action,
    )


def _run_sauvignon_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> None:
    """Run reconnectable Last.fm album discovery for Sauvignon."""
    job = get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Sauvignon album discovery started"
        dry_run_suffix = " in dry-run mode" if dry_run else ""
        _append_blast_log_locked(
            job,
            f"Sauvignon album discovery started{dry_run_suffix}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    last_progress: str | None = None

    def progress_callback(progress_status: str) -> None:
        nonlocal last_progress
        if job.cancel_event.is_set():
            raise _SauvignonJobCancelledError
        with _blast_jobs_lock:
            job.result.detail = progress_status
            if progress_status != last_progress:
                _append_blast_log_locked(job, progress_status)
                last_progress = progress_status

    def choice_reader(
        recommendation: sauvignon.AlbumRecommendation,
        options: tuple[sauvignon.SpotifyAlbumOption, ...],
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _SauvignonJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.sauvignon_pending_choice = SauvignonPendingChoice(
                artist=recommendation.artist,
                album=recommendation.album,
                score=recommendation.score,
                best_match=recommendation.best_match,
                base_rank=recommendation.base_rank,
                weekly_rank=recommendation.weekly_rank,
                supporting_tracks=list(recommendation.supporting_tracks),
                options=[
                    SauvignonAlbumOption(
                        spotify_id=option.spotify_id,
                        artist=option.artist,
                        album=option.album,
                        release_type=option.release_type,
                        release_date=option.release_date,
                        total_tracks=option.total_tracks,
                    )
                    for option in options
                ],
            )
            job.result.status = "waiting"
            job.result.detail = (
                f"Choose the Spotify edition for {recommendation.artist} - "
                f"{recommendation.album}"
            )
            _append_blast_log_locked(job, job.result.detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _SauvignonJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.sauvignon_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Sauvignon album choice"
                _append_blast_log_locked(job, f"Album choice received: {choice}.")
                return choice

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _SauvignonJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        if job.cancel_event.is_set():
            raise _SauvignonJobCancelledError
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)
    lastfm = LastFmClient(api_key, username, event_callback=echo)

    try:
        summary = sauvignon.fill_sauvignon_from_lastfm(
            spotify,
            lastfm,
            playlist_id,
            choice_reader,
            count=count,
            max_playlist_length=max_playlist_length,
            seed_count=seed_count,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _SauvignonJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "Sauvignon discovery stopped. Cached calls and completed additions "
                "remain saved."
                if not dry_run
                else "Sauvignon discovery dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Cached calls and completed additions remain saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except (
        sauvignon.SauvignonError,
        found_art.FoundArtError,
        LastFmError,
        SpotifyException,
    ) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Sauvignon discovery failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Sauvignon discovery error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Sauvignon discovery error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_sauvignon_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.requested_count = summary.requested_count
            job.result.week_start = summary.week_start.isoformat()
            job.result.history_scrobbles = summary.history_scrobbles
            job.result.sauvignon_history_albums = summary.history_albums
            job.result.live_scrobbles_added = summary.live_scrobbles_added
            job.result.sauvignon_seed_count = summary.seed_count
            job.result.sauvignon_track_candidate_count = summary.track_candidate_count
            job.result.sauvignon_album_candidate_count = summary.album_candidate_count
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.selected
            job.result.dry_run = summary.dry_run
            job.result.sauvignon_results = results
            verb = "Would add" if summary.dry_run else "Added"
            job.result.detail = (
                f"{verb} {summary.selected} of {summary.requested_count} album "
                f"recommendations; playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = result.spotify_album or "no selected Spotify edition"
                _append_blast_log_locked(
                    job,
                    f"{result.artist} - {result.album} -> {target} ({result.action}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.sauvignon_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _queue_fill_result_entry(result: the_queue.FillResult) -> QueueFillResultEntry:
    """Convert one Queue recommendation into its stable web representation."""
    return QueueFillResultEntry(
        lastfm_artist=result.recommendation.artist,
        score=result.recommendation.score,
        best_match=result.recommendation.best_match,
        supporting_seeds=list(result.recommendation.supporting_seeds),
        spotify_artist=(
            result.spotify_artist.name if result.spotify_artist is not None else None
        ),
        spotify_artist_id=(
            result.spotify_artist.spotify_id
            if result.spotify_artist is not None
            else None
        ),
        track=result.track.name if result.track is not None else None,
        action=result.action,
        followed=result.followed,
    )


def _queue_flush_result_entry(result: the_queue.FlushResult) -> QueueFlushResultEntry:
    """Convert one Queue top-track transition for web polling."""
    return QueueFlushResultEntry(
        artist=result.artist,
        source_track=result.source_track,
        action=result.action,
        top_tracks=result.top_tracks,
        top_liked_tracks=result.top_liked_tracks,
        total_liked_tracks=result.total_liked_tracks,
        target_track=result.target_track,
        target_release=result.target_release,
        reason=result.reason,
    )


def _run_queue_fill_job(
    job_id: str,
    spotify: Spotify,
    playlists: the_queue.QueuePlaylists,
    api_key: str,
    username: str,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> None:
    """Run reconnectable Last.fm artist discovery for The Queue."""
    job = get_blast_job(job_id, command="fill_queue_from_lastfm")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Queue artist discovery started"
        _append_blast_log_locked(
            job,
            f"Queue artist discovery started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    last_progress: str | None = None

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        nonlocal last_progress
        if job.cancel_event.is_set():
            raise _QueueJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total or None
            job.result.detail = progress_status
            if progress_status != last_progress:
                _append_blast_log_locked(job, progress_status)
                last_progress = progress_status

    def choice_reader(
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _QueueJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.queue_pending_choice = QueuePendingChoice(
                artist=recommendation.artist,
                base_rank=recommendation.base_rank,
                score=recommendation.score,
                supporting_seeds=list(recommendation.supporting_seeds),
                candidates=[
                    QueueArtistOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        popularity=candidate.popularity,
                        followers=candidate.followers,
                        exact_name=candidate.exact_name,
                    )
                    for candidate in candidates
                ],
            )
            job.result.status = "waiting"
            job.result.detail = f"Map Last.fm artist {recommendation.artist}"
            _append_blast_log_locked(job, job.result.detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _QueueJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.queue_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Queue artist mapping"
                _append_blast_log_locked(
                    job,
                    f"Artist mapping choice received: {choice}.",
                )
                return choice

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _QueueJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)
    lastfm = LastFmClient(api_key, username, event_callback=echo)

    try:
        summary = the_queue.fill_queue_from_lastfm(
            spotify,
            lastfm,
            playlists,
            choice_reader,
            count=count,
            max_playlist_length=max_playlist_length,
            seed_count=seed_count,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _QueueJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "Queue fill stopped. Cached calls and completed additions remain saved."
                if not dry_run
                else "Queue fill dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Cached calls and completed additions remain saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except (
        the_queue.QueueError,
        release_check.ReleaseCheckError,
        LastFmError,
        SpotifyException,
    ) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Queue fill failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Queue fill error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Queue fill error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_queue_fill_result_entry(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.requested_count = summary.requested_count
            job.result.week_start = summary.week_start.isoformat()
            job.result.history_scrobbles = summary.history_scrobbles
            job.result.queue_history_artists = summary.history_artists
            job.result.live_scrobbles_added = summary.live_scrobbles_added
            job.result.queue_seed_count = summary.seed_count
            job.result.candidate_count = summary.candidate_count
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.selected
            job.result.queue_fill_results = results
            job.result.detail = (
                "Queue fill paused; rerun to continue."
                if summary.paused
                else f"Selected {summary.selected} of "
                f"{summary.requested_count} artists; "
                f"Queue {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = result.spotify_artist or "no Spotify mapping"
                if result.track:
                    target += f" - {result.track}"
                _append_blast_log_locked(
                    job,
                    f"{result.lastfm_artist} -> {target} ({result.action}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.queue_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_queue_flush_job(
    job_id: str,
    spotify: Spotify,
    playlists: the_queue.QueuePlaylists,
    dry_run: bool,
) -> None:
    """Run the first-ten-artist Queue flush as a reconnectable web job."""
    job = get_blast_job(job_id, command="flush_queue")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Queue flush started"
        _append_blast_log_locked(
            job,
            f"Queue flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    last_progress: str | None = None

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        nonlocal last_progress
        if job.cancel_event.is_set():
            raise _QueueJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status
            if progress_status != last_progress:
                _append_blast_log_locked(job, progress_status)
                last_progress = progress_status

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _QueueJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = the_queue.flush_queue(
            spotify,
            playlists,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _QueueJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "Queue flush stopped. Progress was saved."
                if not dry_run
                else "Queue flush dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except (the_queue.QueueError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Queue flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Queue flush error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Queue flush error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_queue_flush_result_entry(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.run_id = summary.run_id
            job.result.processed = summary.processed
            job.result.total = summary.total
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.queue_resumed = summary.resumed
            job.result.queue_flush_results = results
            job.result.detail = (
                f"Processed {summary.processed} of {summary.total} artists; "
                f"Queue {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = result.target_track or "no replacement"
                if result.target_release:
                    target = f"{result.target_release} - {target}"
                _append_blast_log_locked(
                    job,
                    f"{result.artist}: {result.source_track} -> {target} "
                    f"({result.action}; top {result.top_liked_tracks}/"
                    f"{result.top_tracks}; total {result.total_liked_tracks}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _new_kids_track_result(result: new_kids.FlushResult) -> NewKidsTrackResult:
    """Convert one New Kids result into its stable API representation."""
    return NewKidsTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        current_liked=result.current_liked,
        consecutive_unliked=result.consecutive_unliked,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        release_number=result.release_number,
        album_decision=result.album_decision,
        album_liked_tracks=result.album_liked_tracks,
        album_total_tracks=result.album_total_tracks,
        qualification_reasons=list(result.qualification_reasons),
    )


def _new_kids_fill_result(result: new_kids.FillResult) -> NewKidsFillResult:
    """Convert one Queue 2 transfer into its web representation."""
    return NewKidsFillResult(
        artist=result.artist,
        track=result.track,
        action=result.action,
    )


def _run_new_kids_job(
    job_id: str,
    spotify: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    dry_run: bool,
    command: Literal["flush_new_kids", "flush_queue_2"] = "flush_new_kids",
) -> None:
    """Execute one interactive album-discovery flush as a reconnectable job."""
    label = "Queue 2" if command == "flush_queue_2" else "New Kids"
    job = get_blast_job(job_id, command=command)
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = f"{label} flush started"
        _append_blast_log_locked(
            job,
            f"{label} flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        if job.cancel_event.is_set():
            raise _NewKidsJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status

    def choice_reader(
        artist: str,
        candidates: tuple[new_kids.RankedRelease, ...],
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _NewKidsJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.new_kids_pending_choice = NewKidsPendingChoice(
                artist=artist,
                releases=[
                    NewKidsReleaseOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        release_type=candidate.release_type,
                        release_date=candidate.release_date,
                        total_tracks=candidate.total_tracks,
                        popularity=candidate.popularity,
                        top_track_rank=candidate.top_track_rank,
                        saved=candidate.saved,
                    )
                    for candidate in candidates
                ],
            )
            job.result.status = "waiting"
            job.result.detail = f"Choose the next release for {artist}"
            _append_blast_log_locked(job, job.result.detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _NewKidsJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.new_kids_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying release choice"
                _append_blast_log_locked(job, f"Release choice received: {choice}.")
                return choice

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _NewKidsJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        routine = (
            new_kids.flush_queue_2
            if command == "flush_queue_2"
            else new_kids.flush_new_kids
        )
        summary = routine(
            spotify,
            new_kids_playlist_id,
            queue_2_playlist_id,
            great_discoveries_playlist_id,
            unlucky_ones_playlist_id,
            newfoundland_playlist_id,
            choice_reader=choice_reader,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _NewKidsJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.new_kids_pending_choice = None
            job.result.detail = (
                f"{label} flush stopped. Progress was saved."
                if not dry_run
                else f"{label} dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.new_kids_pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.new_kids_pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.new_kids_pending_choice = None
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except (new_kids.NewKidsError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.new_kids_pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"{label} flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected %s flush error", label)
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.new_kids_pending_choice = None
            job.result.detail = f"Unexpected {label} error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_new_kids_track_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.processed = len(summary.results)
            if job.result.total is None:
                job.result.total = len(summary.results)
            if isinstance(summary, new_kids.Queue2Summary):
                job.result.playlist_length_before = summary.queue_length_before
                job.result.playlist_length_after = summary.queue_length_after
            else:
                job.result.playlist_length_before = summary.playlist_length_before
                job.result.playlist_length_after = summary.playlist_length_after
            job.result.advanced = sum(
                result.action in {"advance", "next release"}
                for result in summary.results
            )
            job.result.skipped = sum(
                result.action == "skip" for result in summary.results
            )
            job.result.new_kids_results = results
            job.result.new_kids_prefill = [
                _new_kids_fill_result(result) for result in summary.prefill
            ]
            job.result.new_kids_postfill = (
                []
                if isinstance(summary, new_kids.Queue2Summary)
                else [_new_kids_fill_result(result) for result in summary.postfill]
            )
            job.result.new_kids_pending_choice = None
            job.result.new_kids_resumed = summary.resumed
            job.result.new_kids_paused = summary.paused
            if summary.paused:
                job.result.detail = f"{label} flush paused. Progress was saved."
            elif isinstance(summary, new_kids.Queue2Summary):
                job.result.detail = (
                    f"{len(summary.results)} decisions; New Kids "
                    f"{summary.new_kids_length_before} -> "
                    f"{summary.new_kids_length_after}; Queue 2 "
                    f"{summary.queue_length_before} -> "
                    f"{summary.queue_length_after}; {len(summary.prefill)} "
                    "transfers."
                )
            else:
                transfers = len(summary.prefill) + len(summary.postfill)
                job.result.detail = (
                    f"{len(summary.results)} decisions; New Kids "
                    f"{summary.playlist_length_before} -> "
                    f"{summary.playlist_length_after}; {transfers} Queue 2 "
                    "transfers."
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.new_kids_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _queue_3_release_option(
    release: slow_listening.DiscographyRelease,
) -> Queue3ReleaseOption:
    """Convert one Queue 3 boundary release for the web client."""
    return Queue3ReleaseOption(
        spotify_id=release.spotify_id,
        name=release.name,
        release_type=release.release_type,
        release_date=release.chronology_date,
        total_tracks=release.total_tracks,
    )


def _queue_3_track_result(result: queue_3.FlushResult) -> Queue3TrackResult:
    """Convert one Queue 3 transition into its web representation."""
    return Queue3TrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        album_decision=result.album_decision,
        album_liked_tracks=result.album_liked_tracks,
        album_total_tracks=result.album_total_tracks,
        composer_playlist=result.composer_playlist,
        reason=result.reason,
    )


def _run_queue_3_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute one interactive Queue 3 flush as a reconnectable web job."""
    job = get_blast_job(job_id, command="flush_queue_3")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Queue 3 flush started"
        _append_blast_log_locked(
            job,
            f"Queue 3 flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        if job.cancel_event.is_set():
            raise _Queue3JobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status

    def wait_for_choice(detail: str) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _Queue3JobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)
        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _Queue3JobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.queue_3_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Queue 3 choice"
                _append_blast_log_locked(job, f"Queue 3 choice received: {choice}.")
                return choice

    def transition_reader(
        source: new_wine.PlaylistTrack,
        current: slow_listening.DiscographyRelease,
        following: slow_listening.DiscographyRelease,
    ) -> str:
        with _blast_jobs_lock:
            job.result.queue_3_pending_choice = Queue3PendingChoice(
                kind="release",
                artist=source.primary_artist_name,
                source_track=source.name,
                current_release=_queue_3_release_option(current),
                next_release=_queue_3_release_option(following),
            )
        return wait_for_choice(
            f"Confirm the next release for {source.primary_artist_name}"
        )

    def composer_playlist_reader(
        artist: str,
        candidates: tuple[queue_3.OwnedPlaylist, ...],
    ) -> str:
        with _blast_jobs_lock:
            job.result.queue_3_pending_choice = Queue3PendingChoice(
                kind="composer_playlist",
                artist=artist,
                playlists=[
                    Queue3ComposerPlaylistOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        total_tracks=candidate.total_tracks,
                    )
                    for candidate in candidates
                ],
            )
        return wait_for_choice(f"Choose the composer playlist for {artist}")

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _Queue3JobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = queue_3.flush_queue_3(
            spotify,
            playlist_id,
            transition_reader,
            composer_playlist_reader=composer_playlist_reader,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _Queue3JobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "Queue 3 flush stopped. Progress was saved."
                if not dry_run
                else "Queue 3 dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except (queue_3.Queue3Error, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Queue 3 flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Queue 3 flush error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Queue 3 error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.run_id = summary.run_id
            job.result.processed = summary.processed
            job.result.total = summary.total
            job.result.advanced = summary.advanced
            job.result.queue_3_changed_releases = summary.changed_releases
            job.result.completed_artists = summary.completed_artists
            job.result.skipped = summary.skipped
            job.result.queue_3_results = [
                _queue_3_track_result(result) for result in summary.results
            ]
            job.result.queue_3_annual_import = [
                Queue3AnnualImportEntry(
                    artist=result.artist,
                    track=result.track,
                    source_year=result.source_year,
                    action=result.action,
                )
                for result in summary.annual_import
            ]
            job.result.queue_3_resumed = summary.resumed
            job.result.queue_3_paused = summary.paused
            if summary.paused:
                job.result.detail = "Queue 3 flush paused. Progress was saved."
            else:
                job.result.detail = (
                    f"{summary.processed} decisions; {summary.advanced} advances; "
                    f"{summary.changed_releases} release changes; "
                    f"{summary.completed_artists} completed artists."
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.queue_3_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _new_wine_track_result(result: new_wine.FlushResult) -> NewWineTrackResult:
    """Convert one New Wine result into its stable API representation."""
    return NewWineTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        release=result.release,
        release_type=result.release_type,
        current_liked=result.current_liked,
        consecutive_unliked=result.consecutive_unliked,
        action=result.action,
        target_track=result.target_track,
        album_unsaved=result.album_unsaved,
        advance_reason=result.advance_reason,
        drop_reason=result.drop_reason,
        continuation_release=result.continuation_release,
        continuation_track=result.continuation_track,
    )


def _new_wine_refill_result(
    refill: new_wine.CellarRefillSummary | None,
) -> NewWineRefillResult | None:
    """Convert a Wine Cellar refill while keeping web payloads compact."""
    if refill is None:
        return None
    return NewWineRefillResult(
        target_size=refill.target_size,
        before=refill.before,
        after=refill.after,
        added=refill.added,
        removed_from_cellar=refill.removed_from_cellar,
        ineligible=refill.ineligible,
        no_discovery=refill.no_discovery,
        results=[
            NewWineCellarTrackResult(
                artist=result.artist,
                source_track=result.source_track,
                action=result.action,
                liked_tracks=result.liked_tracks,
                saved_albums=result.saved_albums,
            )
            for result in refill.results
            if result.action != "ineligible"
        ],
    )


def _run_new_wine_job(
    job_id: str,
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    dry_run: bool,
    no_discovery: bool,
) -> None:
    """Execute one interactive New Wine flush as a reconnectable web job."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "New Wine flush started"
        _append_blast_log_locked(
            job,
            f"New Wine flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        if job.cancel_event.is_set():
            raise _NewWineJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status

    def choice_reader(
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _NewWineJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.pending_choice = NewWinePendingChoice(
                artist=source.primary_artist_name,
                source_track=source.name,
                terminal_release=source.release.release_type in {"Album", "EP"},
                releases=[
                    NewWineReleaseOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        release_type=candidate.release_type,
                        release_date=candidate.release_date,
                        total_tracks=candidate.total_tracks,
                        primary_artist_name=candidate.primary_artist_name,
                    )
                    for candidate in candidates
                ],
            )
            job.result.status = "waiting"
            job.result.detail = (
                f"Choose a release for {source.primary_artist_name} after {source.name}"
            )
            _append_blast_log_locked(job, job.result.detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _NewWineJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying release choice"
                _append_blast_log_locked(job, f"Release choice received: {choice}.")
                return choice

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _NewWineJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = new_wine.flush_new_wine(
            spotify,
            new_wine_playlist_id,
            sauvignon_playlist_id,
            choice_reader=choice_reader,
            wine_cellar_playlist_id=wine_cellar_playlist_id,
            no_discovery=no_discovery,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _NewWineJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.pending_choice = None
            job.result.detail = (
                "New Wine flush stopped. Progress was saved."
                if not dry_run
                else "New Wine dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + ". "
                "Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except (new_wine.NewWineError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"New Wine flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected New Wine flush error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.pending_choice = None
            job.result.detail = f"Unexpected New Wine error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_new_wine_track_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.processed = summary.processed
            job.result.total = summary.total
            job.result.advanced = summary.advanced
            job.result.dropped = summary.dropped
            job.result.sent_to_sauvignon = summary.sent_to_sauvignon
            job.result.completed_singles = summary.completed_singles
            job.result.skipped = summary.skipped
            job.result.albums_unsaved = summary.albums_unsaved
            job.result.new_wine_results = results
            job.result.new_wine_refill = _new_wine_refill_result(summary.refill)
            job.result.pending_choice = None
            if summary.paused:
                job.result.detail = "New Wine flush paused. Progress was saved."
            else:
                unsave_label = "to unsave" if dry_run else "unsaved"
                job.result.detail = (
                    f"{summary.processed}/{summary.total} processed; "
                    f"{summary.advanced} advanced, {summary.dropped} dropped, "
                    f"{summary.sent_to_sauvignon} sent to Sauvignon, "
                    f"{summary.albums_unsaved} albums {unsave_label}."
                )
                if summary.refill is not None:
                    job.result.detail += (
                        f" New Wine {summary.refill.before} -> "
                        f"{summary.refill.after}; {summary.refill.added} pulled "
                        "from Wine Cellar."
                    )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _slow_listening_track_result(
    result: slow_listening.FlushResult,
) -> SlowListeningTrackResult:
    """Convert one Slow Listening result into its stable API representation."""
    return SlowListeningTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        skipped_candidates=list(result.skipped_candidates),
        reason=result.reason,
    )


def _run_slow_listening_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute an interactive Slow Listening flush as a reconnectable job."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Slow Listening flush started"
        _append_blast_log_locked(
            job,
            f"Slow Listening flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        if job.cancel_event.is_set():
            raise _SlowListeningJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status

    def wait_for_submission(
        pending: SlowListeningPendingChoice,
        detail: str,
    ) -> tuple[str, tuple[str, ...] | None]:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _SlowListeningJobCancelledError
            job.submitted_choice = None
            job.submitted_order = None
            job.choice_event.clear()
            job.result.slow_listening_pending_choice = pending
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _SlowListeningJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                order = job.submitted_order
                job.submitted_choice = None
                job.submitted_order = None
                job.choice_event.clear()
                job.result.slow_listening_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Slow Listening choice"
                _append_blast_log_locked(
                    job,
                    f"Slow Listening choice received: {choice}.",
                )
                return choice, order

    def action_reader(
        source: new_wine.PlaylistTrack,
        target: new_wine.ReleaseTrack,
        target_release: slow_listening.DiscographyRelease,
    ) -> str:
        choice, _order = wait_for_submission(
            SlowListeningPendingChoice(
                kind="track",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
                target_track=target.name,
                target_release=target_release.name,
            ),
            (
                f"Add {target.name} ({target_release.name}) after "
                f"{source.primary_artist_name} - {source.name}?"
            ),
        )
        return choice

    def order_reader(
        release_date: str,
        candidates: tuple[slow_listening.DiscographyRelease, ...],
    ) -> tuple[str, ...]:
        artist = candidates[0].primary_artist_name if candidates else "Artist"
        choice, order = wait_for_submission(
            SlowListeningPendingChoice(
                kind="release_order",
                artist=artist,
                release_date=release_date,
                releases=[
                    SlowListeningReleaseOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        release_type=candidate.release_type,
                        release_date=candidate.release_date,
                        total_tracks=candidate.total_tracks,
                        saved=candidate.saved,
                        plain=candidate.plain,
                    )
                    for candidate in candidates
                ],
            ),
            f"Order {artist}'s releases dated {release_date}.",
        )
        if choice != "order" or order is None:
            raise slow_listening.SlowListeningError(
                "Slow Listening release order was not submitted."
            )
        return order

    def completion_notifier(source: new_wine.PlaylistTrack) -> None:
        choice, _order = wait_for_submission(
            SlowListeningPendingChoice(
                kind="completion",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
            ),
            (
                f"{source.primary_artist_name} completed Slow Listening. "
                "Add a replacement artist, then continue."
            ),
        )
        if choice != "continue":
            raise slow_listening.SlowListeningError(
                "Slow Listening completion was not acknowledged."
            )

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _SlowListeningJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = slow_listening.flush_slow_listening(
            spotify,
            playlist_id,
            order_reader=order_reader,
            completion_notifier=completion_notifier,
            action_reader=action_reader,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _SlowListeningJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.slow_listening_pending_choice = None
            job.result.detail = (
                "Slow Listening flush stopped. Progress was saved."
                if not dry_run
                else "Slow Listening dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.slow_listening_pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.slow_listening_pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + ". "
                "Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except (slow_listening.SlowListeningError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.slow_listening_pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Slow Listening flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Slow Listening flush error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.slow_listening_pending_choice = None
            job.result.detail = f"Unexpected Slow Listening error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_slow_listening_track_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.processed = summary.processed
            job.result.total = summary.total
            job.result.advanced = summary.advanced
            job.result.completed_artists = summary.completed_artists
            job.result.skipped = summary.skipped
            job.result.slow_listening_results = results
            job.result.slow_listening_pending_choice = None
            if summary.paused:
                job.result.detail = "Slow Listening flush paused. Progress was saved."
            else:
                job.result.detail = (
                    f"{summary.processed}/{summary.total} processed; "
                    f"{summary.advanced} advanced, "
                    f"{summary.completed_artists} artists completed, "
                    f"{summary.skipped} skipped."
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.slow_listening_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _something_old_date(timestamp_ms: int) -> str:
    """Format one scrobble timestamp in the listening timezone."""
    return (
        datetime.fromtimestamp(
            timestamp_ms / 1000,
            blast_from_past.SCROBBLE_TIMEZONE,
        )
        .date()
        .isoformat()
    )


def _something_old_track_result(
    track: something_old.SelectedTrack,
) -> SomethingOldTrackResult:
    """Convert one Something Old selection into its API representation."""
    return SomethingOldTrackResult(
        spotify_id=track.spotify_id,
        track=track.track,
        album=track.album,
        artists=list(track.artists),
        source=track.source,
        lastfm_scrobbles=track.lastfm_scrobbles,
    )


def _run_something_old_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Execute Something Old as a reconnectable interactive web job."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Something Old started"
        _append_blast_log_locked(
            job,
            f"Something Old started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def wait_for_submission(
        pending: SomethingOldPendingChoice,
        detail: str,
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _SomethingOldJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.something_old_pending_choice = pending
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _SomethingOldJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.something_old_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Something Old choice"
                _append_blast_log_locked(
                    job,
                    f"Something Old choice received: {choice}.",
                )
                return choice

    def artist_choice_reader(
        artist: something_old.GoldenOldieArtist,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        average_date = _something_old_date(artist.average_scrobble_ms)
        with _blast_jobs_lock:
            job.result.something_old_artist = artist.artist
            job.result.something_old_average_scrobble_date = average_date
        return wait_for_submission(
            SomethingOldPendingChoice(
                kind="artist",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=average_date,
                artist_candidates=[
                    SomethingOldArtistOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        popularity=candidate.popularity,
                        followers=candidate.followers,
                    )
                    for candidate in candidates
                ],
            ),
            f"Choose the exact Spotify artist for {artist.artist}.",
        )

    def mode_reader(
        artist: something_old.GoldenOldieArtist,
        spotify_artist: something_old.SpotifyArtistCandidate,
    ) -> str:
        with _blast_jobs_lock:
            job.result.something_old_artist = artist.artist
            job.result.something_old_average_scrobble_date = _something_old_date(
                artist.average_scrobble_ms
            )
            job.result.something_old_spotify_artist = spotify_artist.name
        return wait_for_submission(
            SomethingOldPendingChoice(
                kind="mode",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=_something_old_date(artist.average_scrobble_ms),
                spotify_artist=spotify_artist.name,
            ),
            f"Choose what to add for {artist.artist}.",
        )

    def album_choice_reader(
        artist: something_old.GoldenOldieArtist,
        releases: tuple[slow_listening.DiscographyRelease, ...],
    ) -> str:
        return wait_for_submission(
            SomethingOldPendingChoice(
                kind="album",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=_something_old_date(artist.average_scrobble_ms),
                spotify_artist=job.result.something_old_spotify_artist,
                releases=[
                    SomethingOldReleaseOption(
                        spotify_id=release.spotify_id,
                        name=release.name,
                        release_type=release.release_type,
                        release_date=release.chronology_date,
                        total_tracks=release.total_tracks,
                        saved=release.saved,
                        plain=release.plain,
                    )
                    for release in releases
                ],
            ),
            f"Choose one album or EP by {artist.artist}.",
        )

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _SomethingOldJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    lastfm = LastFmClient(
        api_key,
        username,
        event_callback=echo,
    )
    try:
        summary = something_old.run_something_old(
            spotify,
            lastfm,
            playlist_id,
            expected_username=username,
            mode_reader=mode_reader,
            album_choice_reader=album_choice_reader,
            artist_choice_reader=artist_choice_reader,
            dry_run=dry_run,
            progress_callback=echo,
            retry_call=retry_call,
        )
    except _SomethingOldJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.something_old_pending_choice = None
            job.result.detail = "Something Old stopped. Spotify was unchanged."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.something_old_pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.something_old_pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    datetime.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                job.result.status = "paused"
                job.result.retry_at = retry_at.isoformat() if retry_at else None
                job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                job.result.status = "failed"
                job.result.detail = str(exc)
            job.result.something_old_pending_choice = None
            _append_blast_log_locked(job, job.result.detail)
    except (
        something_old.SomethingOldError,
        scrobble_history.ScrobbleHistoryError,
        LastFmError,
    ) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.something_old_pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Something Old failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Something Old error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.something_old_pending_choice = None
            job.result.detail = f"Unexpected Something Old error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        ranking = [
            SomethingOldRankingEntry(
                artist=entry.artist,
                scrobbles=entry.scrobbles,
                average_scrobble_date=_something_old_date(entry.average_scrobble_ms),
            )
            for entry in summary.ranking_preview
        ]
        tracks = [_something_old_track_result(track) for track in summary.tracks]
        with _blast_jobs_lock:
            job.result.status = (
                "cancelled" if summary.action == "cancelled" else "completed"
            )
            job.result.something_old_action = summary.action
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = len(tracks) if summary.action == "added" else 0
            job.result.something_old_ranking = ranking
            job.result.something_old_tracks = tracks
            job.result.something_old_pending_choice = None
            if summary.history_refresh is not None:
                job.result.live_scrobbles_added = (
                    summary.history_refresh.live_scrobbles_added
                )
                job.result.history_scrobbles = summary.history_refresh.total_scrobbles
            if summary.artist is not None:
                job.result.something_old_artist = summary.artist.artist
                job.result.something_old_average_scrobble_date = _something_old_date(
                    summary.artist.average_scrobble_ms
                )
            if summary.spotify_artist is not None:
                job.result.something_old_spotify_artist = summary.spotify_artist.name
            job.result.something_old_mode = summary.mode
            job.result.something_old_release = (
                summary.release.name if summary.release is not None else None
            )
            if summary.action == "playlist not empty":
                job.result.detail = (
                    f"Something Old already contains {summary.playlist_length_before} "
                    "item(s); nothing was changed."
                )
            elif summary.action == "cancelled":
                job.result.detail = "Something Old was cancelled."
            elif summary.action == "would add":
                job.result.detail = (
                    f"Dry run: would add {len(tracks)} track(s) for "
                    f"{job.result.something_old_artist}."
                )
            else:
                job.result.detail = (
                    f"Added {len(tracks)} track(s) for "
                    f"{job.result.something_old_artist}."
                )
            for track in tracks:
                _append_blast_log_locked(
                    job,
                    f"Selected {', '.join(track.artists)} - {track.track} "
                    f"({track.album or 'no album'}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.something_old_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _release_check_result(
    result: release_check.ReleaseCheckResult,
) -> ReleaseCheckResultEntry:
    """Convert one release-check decision into its API representation."""
    return ReleaseCheckResultEntry(
        artist=result.artist,
        artist_rank=result.artist_rank,
        artist_scrobbles=result.artist_scrobbles,
        spotify_artist_id=result.spotify_artist_id,
        release_id=result.release_id,
        release=result.release,
        release_type=result.release_type,
        release_date=result.release_date,
        first_track_id=result.first_track_id,
        first_track=result.first_track,
        linked_future_release=result.linked_future_release,
        wine_cellar_action=result.wine_cellar_action,
        new_vintage_action=result.new_vintage_action,
        reason=result.reason,
        dry_run=result.dry_run,
    )


def _run_release_check_job(
    job_id: str,
    spotify: Spotify,
    playlists: release_check.ReleaseCheckPlaylists,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Execute one reconnectable, interactive new-release check."""
    job = get_blast_job(job_id, command="check_new_releases")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "New-release check started"
        _append_blast_log_locked(
            job,
            f"New-release check started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def wait_for_submission(
        pending: ReleaseCheckPendingChoice,
        detail: str,
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _ReleaseCheckJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.release_check_pending_choice = pending
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _ReleaseCheckJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.release_check_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying release-check choice"
                if choice.startswith(release_check.CHOICE_SEARCH_PREFIX):
                    logged_choice = "custom artist search"
                else:
                    logged_choice = choice
                _append_blast_log_locked(
                    job,
                    f"Release-check choice received: {logged_choice}.",
                )
                return choice

    def artist_choice_reader(
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        return wait_for_submission(
            ReleaseCheckPendingChoice(
                kind="artist",
                artist=artist.name,
                artist_rank=artist.rank,
                artist_scrobbles=artist.scrobbles,
                artist_candidates=[
                    ReleaseCheckArtistOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        popularity=candidate.popularity,
                        followers=candidate.followers,
                        exact_name=candidate.exact_name,
                    )
                    for candidate in candidates
                ],
            ),
            f"Choose the Spotify artist for #{artist.rank} {artist.name}.",
        )

    def release_choice_reader(
        artist: release_check.RankedArtist,
        release: release_check.ReleaseCandidate,
        track: release_check.ReleaseTrack,
        destinations: tuple[str, ...],
        unattached_single: bool,
    ) -> str:
        return wait_for_submission(
            ReleaseCheckPendingChoice(
                kind="release",
                artist=artist.name,
                artist_rank=artist.rank,
                artist_scrobbles=artist.scrobbles,
                release=release.name,
                release_type=release.release_type,
                release_date=release.release_date,
                first_track=track.name,
                destinations=list(destinations),
                tags=list(release_check.release_tags(release)),
                unattached_single=unattached_single,
            ),
            (
                f"Review {release.release_type.casefold()} {release.name} "
                f"by {artist.name}."
            ),
        )

    def update_progress(completed: int, total: int, detail: str) -> None:
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _ReleaseCheckJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    lastfm = LastFmClient(api_key, username, event_callback=echo)
    try:
        summary = release_check.run_release_check(
            spotify,
            lastfm,
            playlists,
            expected_username=username,
            artist_choice_reader=artist_choice_reader,
            release_choice_reader=release_choice_reader,
            dry_run=dry_run,
            state_path=RELEASE_CHECK_STATE_PATH,
            state_service=get_state_service(),
            progress_callback=update_progress,
            retry_call=retry_call,
        )
    except _ReleaseCheckJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "New-release check stopped. Durable progress was preserved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Spotify request failed: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    except (
        release_check.ReleaseCheckError,
        scrobble_history.ScrobbleHistoryError,
        LastFmError,
        RequestException,
    ) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"New-release check failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected new-release check error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected new-release check error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_release_check_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.run_id = summary.run_id
            job.result.processed = summary.artists_processed
            job.result.total = summary.artists_total
            job.result.release_check_checked_from = summary.checked_from.isoformat()
            job.result.release_check_checked_through = (
                summary.checked_through.isoformat()
            )
            job.result.release_check_resumed = summary.resumed
            job.result.release_check_paused = summary.paused
            job.result.release_check_wine_cellar_added = summary.wine_cellar_added
            job.result.release_check_new_vintage_added = summary.new_vintage_added
            job.result.release_check_results = results
            if summary.history_refresh is not None:
                job.result.live_scrobbles_added = (
                    summary.history_refresh.live_scrobbles_added
                )
                job.result.history_scrobbles = summary.history_refresh.total_scrobbles
            if summary.paused:
                job.result.detail = (
                    "New-release check paused. Rerun it to resume from the "
                    "durable checkpoint."
                )
            else:
                verb = "Would add" if dry_run else "Added"
                job.result.detail = (
                    f"{summary.artists_processed}/{summary.artists_total} artists "
                    f"checked. {verb} {summary.wine_cellar_added} to Wine Cellar "
                    f"and {summary.new_vintage_added} to New Vintage."
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.release_check_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _discography_artist_result(
    selection: discography.ArtistSelection,
) -> DiscographyArtistResult:
    """Convert one planned discography artist into its API representation."""
    return DiscographyArtistResult(
        spotify_id=selection.spotify_id,
        artist=selection.name,
        queue=discography.QUEUE_LABELS[selection.source_queue],
        releases=selection.release_count,
        days=selection.days,
        release_names=[release.name for release in selection.releases],
    )


def _run_discography_job(
    job_id: str,
    spotify: Spotify,
    playlist_ids: dict[discography.QueueName, str],
    queue_3_playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute one reload-safe interactive discography planning job."""
    job = get_blast_job(job_id, command="plan_discographies")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Discography planning started"
        _append_blast_log_locked(
            job,
            f"Discography planning started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def wait_for_submission(
        pending: DiscographyPendingChoice,
        detail: str,
    ) -> tuple[str, tuple[str, ...]]:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _DiscographyJobCancelledError
            job.submitted_choice = None
            job.submitted_order = None
            job.choice_event.clear()
            job.result.discography_pending_choice = pending
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _DiscographyJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                release_ids = job.submitted_order or ()
                job.submitted_choice = None
                job.submitted_order = None
                job.choice_event.clear()
                job.result.discography_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying discography choice"
                _append_blast_log_locked(
                    job,
                    f"Discography choice received: {choice}.",
                )
                return choice, release_ids

    def release_selector(
        artist: discography.QueueArtist,
        releases: tuple[discography.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        choice, release_ids = wait_for_submission(
            DiscographyPendingChoice(
                kind="releases",
                artist=artist.name,
                queue=discography.QUEUE_LABELS[artist.queue],
                releases=[
                    DiscographyReleaseOption(
                        spotify_id=release.spotify_id,
                        name=release.name,
                        release_type=release.release_type,
                        release_date=release.chronology_date,
                        total_tracks=release.total_tracks,
                        saved=release.saved,
                        default=release.default,
                    )
                    for release in releases
                ],
                default_release_ids=[
                    release.spotify_id for release in releases if release.default
                ],
            ),
            f"Choose the releases to count for {artist.name}.",
        )
        if choice == "quit":
            raise _DiscographyJobCancelledError
        if choice == "none":
            return ()
        return release_ids

    def progress(detail: str) -> None:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _DiscographyJobCancelledError
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _DiscographyJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        plan = discography.build_discography_plan(
            spotify,
            playlist_ids,
            release_selector,
            queue_3_playlist_id=queue_3_playlist_id,
            retry_call=retry_call,
            progress_callback=progress,
        )
        with _blast_jobs_lock:
            job.result.discography_start_queue = discography.QUEUE_LABELS[
                plan.start_queue
            ]
            job.result.discography_next_queue = discography.QUEUE_LABELS[
                plan.next_queue
            ]
            job.result.discography_total_releases = plan.total_releases
            job.result.discography_days = plan.days
            job.result.discography_open_slots = plan.open_slots
            job.result.discography_results = [
                _discography_artist_result(selection) for selection in plan.artists
            ]

        if not plan.artists:
            with _blast_jobs_lock:
                job.result.status = "completed"
                job.result.detail = "No artists with selected releases were found."
                _append_blast_log_locked(job, job.result.detail)
        elif dry_run:
            with _blast_jobs_lock:
                job.result.status = "completed"
                job.result.detail = (
                    f"Dry run complete: {plan.total_releases} releases over "
                    f"{plan.days:g} days. Playlists and state were unchanged."
                )
                _append_blast_log_locked(job, job.result.detail)
        else:
            choice, _release_ids = wait_for_submission(
                DiscographyPendingChoice(kind="confirm"),
                (
                    "Confirm removal from the source queues and Queue 3 "
                    "where applicable."
                ),
            )
            if choice == "quit":
                raise _DiscographyJobCancelledError
            if choice == "keep":
                with _blast_jobs_lock:
                    job.result.status = "completed"
                    job.result.detail = (
                        "Discography plan complete; playlist markers and state "
                        "were kept unchanged."
                    )
                    _append_blast_log_locked(job, job.result.detail)
            else:
                summary = discography.apply_discography_plan(
                    spotify,
                    plan,
                    retry_call=retry_call,
                    progress_callback=progress,
                )
                with _blast_jobs_lock:
                    job.result.status = "completed"
                    job.result.discography_removed_artists = summary.removed_artists
                    job.result.discography_removed_markers = summary.removed_markers
                    job.result.detail = (
                        f"Removed {summary.removed_artists} artists and "
                        f"{summary.removed_markers} marker tracks. The next run "
                        f"starts with {discography.QUEUE_LABELS[summary.next_queue]}."
                    )
                    _append_blast_log_locked(job, job.result.detail)
    except _DiscographyJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = "Discography planning stopped; nothing else changed."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Spotify request failed: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    except (discography.DiscographyError, RequestException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Discography planning failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected discography planning error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected discography planning error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.discography_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_requeue_for_a_dream_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute one reconnectable Requeue for a Dream transition."""
    job = get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Requeue for a Dream started"
        _append_blast_log_locked(
            job,
            (
                "Requeue for a Dream started in dry-run mode."
                if dry_run
                else "Requeue for a Dream started."
            ),
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _RequeueForADreamJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        if job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        if job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
        return result

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            playlist_id,
            dry_run=dry_run,
            echo=echo,
            progress_callback=echo,
            retry_call=retry_call,
        )
    except _RequeueForADreamJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "Requeue for a Dream stopped safely. Rerun it to continue."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    datetime.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                job.result.status = "paused"
                job.result.retry_at = retry_at.isoformat() if retry_at else None
                job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                job.result.status = "failed"
                job.result.detail = str(exc)
            _append_blast_log_locked(job, job.result.detail)
    except requeue_for_a_dream.RequeueForADreamError as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Requeue for a Dream failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Requeue for a Dream error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Requeue for a Dream error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requeue_action = summary.action
            job.result.requeue_artist = summary.artist
            job.result.requeue_source_track = summary.source_track
            job.result.requeue_source_release = summary.source_release
            job.result.requeue_target_track = summary.target_track
            job.result.requeue_target_release = summary.target_release
            job.result.requeue_target_release_type = summary.target_release_type
            job.result.requeue_target_release_date = summary.target_release_date
            job.result.requeue_target_already_present = summary.target_already_present
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = int(
                summary.action == "advance" and not summary.target_already_present
            )
            if summary.action == "advance":
                verb = "would advance" if dry_run else "advanced"
                job.result.detail = (
                    f"{verb.capitalize()} {summary.artist} from "
                    f"{summary.source_release} to {summary.target_release}."
                )
            elif summary.action == "drop":
                verb = "would drop" if dry_run else "dropped"
                job.result.detail = (
                    f"{verb.capitalize()} {summary.artist} after the final "
                    "eligible release."
                )
            elif summary.action == "empty":
                job.result.detail = "Requeue for a Dream is empty."
            else:
                job.result.detail = (
                    f"Skipped {summary.artist or 'the playlist head'}: "
                    f"{summary.reason or 'no safe transition was found'}."
                )
            if summary.target_track:
                _append_blast_log_locked(
                    job,
                    f"Next track: {summary.target_track} ({summary.target_release}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_palace_of_memory_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str | None,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> None:
    """Execute one reconnectable Palace fill or cursor adjustment."""
    job = get_blast_job(job_id, command="fill_palace_of_memory")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = (
            "Setting Palace alphabetical cursor"
            if cursor_position is not None
            else "Palace of Memory started"
        )
        _append_blast_log_locked(job, job.result.detail)

    def echo(message: str) -> None:
        if job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _PalaceOfMemoryJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        if job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        if job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        return result

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    cursor_update: palace_of_memory.AlphabeticalCursorUpdate | None = None
    summary: palace_of_memory.PalaceOfMemorySummary | None = None
    try:
        if cursor_position is not None:
            cursor_update = palace_of_memory.set_alphabetical_cursor(
                spotify,
                cursor_position,
                progress_callback=echo,
                retry_call=retry_call,
            )
        else:
            if playlist_id is None:
                raise palace_of_memory.PalaceOfMemoryConfigError(
                    "Palace of Memory playlist is required."
                )
            summary = palace_of_memory.fill_palace_of_memory(
                spotify,
                playlist_id,
                dry_run=dry_run,
                alphabetical_start=alphabetical_start,
                echo=echo,
                progress_callback=echo,
                retry_call=retry_call,
            )
    except _PalaceOfMemoryJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = "Palace of Memory stopped safely. Rerun it to continue."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    datetime.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                job.result.status = "paused"
                job.result.retry_at = retry_at.isoformat() if retry_at else None
                job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                job.result.status = "failed"
                job.result.detail = str(exc)
            _append_blast_log_locked(job, job.result.detail)
    except palace_of_memory.PalaceOfMemoryError as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Palace of Memory failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Palace of Memory error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Palace of Memory error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "completed"
            if cursor_update is not None:
                refresh = cursor_update.album_refresh
                job.result.palace_alphabetical_start_index = cursor_update.next_index
                job.result.palace_alphabetical_next_index = cursor_update.next_index
                job.result.palace_next_album_artist = cursor_update.next_album.artist
                job.result.palace_next_album = cursor_update.next_album.album
                job.result.detail = (
                    f"Alphabetical cursor set to {cursor_update.next_index + 1}: "
                    f"{cursor_update.next_album.artist} - "
                    f"{cursor_update.next_album.album}."
                )
            elif summary is not None:
                refresh = summary.album_refresh
                job.result.random_org_timestamp = summary.generated_at.isoformat()
                job.result.palace_cutoff_date = summary.cutoff_date.isoformat()
                job.result.palace_available_dates = summary.available_dates
                job.result.palace_alphabetical_start_index = (
                    summary.alphabetical_start_index
                )
                job.result.palace_alphabetical_next_index = (
                    summary.alphabetical_next_index
                )
                job.result.palace_alphabetical_cursor_overridden = (
                    summary.alphabetical_cursor_overridden
                )
                job.result.playlist_length_before = summary.playlist_length_before
                job.result.playlist_length_after = summary.playlist_length_after
                job.result.added = summary.added
                job.result.palace_results = [
                    PalaceAlbumSelectionResult(
                        source=result.source,
                        selected_date=(
                            result.selected_date.isoformat()
                            if result.selected_date is not None
                            else None
                        ),
                        history_position=result.history_position,
                        albums_on_date=result.albums_on_date,
                        artist=result.artist,
                        album=result.album,
                        spotify_album=(
                            result.spotify_album.album
                            if result.spotify_album is not None
                            else None
                        ),
                        first_track=(
                            result.first_track.name
                            if result.first_track is not None
                            else None
                        ),
                        action=result.action,
                    )
                    for result in summary.results
                ]
                verb = "Would add" if dry_run else "Added"
                job.result.detail = (
                    f"{verb} {summary.added} first track(s) to Palace of Memory."
                )
                for result in job.result.palace_results:
                    _append_blast_log_locked(
                        job,
                        f"{result.source.title()}: {result.artist} - "
                        f"{result.album} -> {result.first_track or 'no match'} "
                        f"({result.action}).",
                    )
            else:  # pragma: no cover - defensive worker invariant
                raise AssertionError("Palace worker completed without a result")

            job.result.palace_album_refresh = PalaceAlbumRefreshResult(
                previous=refresh.previous,
                current=refresh.current,
                added=refresh.added,
                removed=refresh.removed,
                skipped=refresh.skipped,
                persisted=refresh.persisted,
                backup_path=refresh.backup_path,
            )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_scrobble_history_job(
    job_id: str,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Refresh the shared Last.fm record as a reconnectable web job."""
    job = get_blast_job(job_id, command="update_scrobble_history")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Last.fm scrobble history update started"
        _append_blast_log_locked(
            job,
            (
                "Last.fm scrobble history update started in dry-run mode."
                if dry_run
                else "Last.fm scrobble history update started."
            ),
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    lastfm = LastFmClient(
        api_key,
        username,
        event_callback=echo,
    )
    try:
        summary = scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username=username,
            dry_run=dry_run,
            progress_callback=echo,
        )
    except (scrobble_history.ScrobbleHistoryError, LastFmError) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Scrobble history update failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected scrobble history update error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected scrobble history update error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.history_export_scrobbles = summary.export_scrobbles
            job.result.history_legacy_scrobbles_added = summary.legacy_scrobbles_added
            job.result.live_scrobbles_added = summary.live_scrobbles_added
            job.result.history_scrobbles = summary.total_scrobbles
            job.result.history_persisted = summary.persisted
            job.result.history_backup_path = (
                str(summary.backup_path) if summary.backup_path else None
            )
            if summary.dry_run:
                job.result.detail = (
                    "Dry run complete; the canonical Last.fm history was unchanged."
                )
            elif summary.persisted:
                job.result.detail = "Last.fm scrobble history updated safely."
            else:
                job.result.detail = "Last.fm scrobble history was already current."
            _append_blast_log_locked(job, job.result.detail)
    finally:
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def start_blast_job(
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
) -> BlastJobResult:
    """Start one playlist job, rejecting another active invocation."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(result=BlastJobResult(job_id=job_id))
        _append_blast_log_locked(job, "A blast from the past queued.")
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_blast_job,
        args=(job_id, spotify, playlist_id, count, max_playlist_length),
        name=f"blast-from-the-past-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_daily_mind_radio_job(
    spotify: Spotify,
    playlist_id: str,
) -> BlastJobResult:
    """Start one Daily Mind Radio job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="daily_mind_radio",
            )
        )
        _append_blast_log_locked(job, "Daily Mind Radio queued.")
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_daily_mind_radio_job,
        args=(job_id, spotify, playlist_id),
        name=f"daily-mind-radio-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_found_art_job(
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int,
) -> BlastJobResult:
    """Start one Found Art job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="found_art",
                requested_count=count,
            )
        )
        _append_blast_log_locked(job, "Found Art queued.")
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_found_art_job,
        args=(job_id, spotify, playlist_id, api_key, username, count),
        name=f"found-art-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_sauvignon_job(
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    *,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> BlastJobResult:
    """Start a Sauvignon album-discovery job, rejecting playlist overlap."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_sauvignon_from_lastfm",
                requested_count=count,
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"Sauvignon album discovery queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_sauvignon_job,
        args=(
            job_id,
            spotify,
            playlist_id,
            api_key,
            username,
            count,
            max_playlist_length,
            seed_count,
            dry_run,
        ),
        name=f"sauvignon-fill-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_queue_fill_job(
    spotify: Spotify,
    playlists: the_queue.QueuePlaylists,
    api_key: str,
    username: str,
    *,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> BlastJobResult:
    """Start a Queue artist-discovery job, rejecting playlist overlap."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_queue_from_lastfm",
                requested_count=count,
                queue_max_playlist_length=max_playlist_length,
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"Queue artist discovery queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_queue_fill_job,
        args=(
            job_id,
            spotify,
            playlists,
            api_key,
            username,
            count,
            max_playlist_length,
            seed_count,
            dry_run,
        ),
        name=f"queue-fill-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_queue_flush_job(
    spotify: Spotify,
    playlists: the_queue.QueuePlaylists,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start a Queue flush job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_queue",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"Queue flush queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_queue_flush_job,
        args=(job_id, spotify, playlists, dry_run),
        name=f"queue-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_new_kids_job(
    spotify: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one New Kids web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_new_kids",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"New Kids flush queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_new_kids_job,
        args=(
            job_id,
            spotify,
            new_kids_playlist_id,
            queue_2_playlist_id,
            great_discoveries_playlist_id,
            unlucky_ones_playlist_id,
            newfoundland_playlist_id,
            dry_run,
        ),
        name=f"new-kids-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_queue_2_job(
    spotify: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Queue 2 web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_queue_2",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"Queue 2 flush queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_new_kids_job,
        args=(
            job_id,
            spotify,
            new_kids_playlist_id,
            queue_2_playlist_id,
            great_discoveries_playlist_id,
            unlucky_ones_playlist_id,
            newfoundland_playlist_id,
            dry_run,
            "flush_queue_2",
        ),
        name=f"queue-2-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_queue_3_job(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Queue 3 web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_queue_3",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"Queue 3 flush queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_queue_3_job,
        args=(job_id, spotify, playlist_id, dry_run),
        name=f"queue-3-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_new_wine_job(
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    *,
    dry_run: bool,
    no_discovery: bool,
) -> BlastJobResult:
    """Start one New Wine web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_new_wine",
                dry_run=dry_run,
                no_discovery=no_discovery,
            )
        )
        _append_blast_log_locked(
            job,
            f"New Wine flush queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_new_wine_job,
        args=(
            job_id,
            spotify,
            new_wine_playlist_id,
            sauvignon_playlist_id,
            wine_cellar_playlist_id,
            dry_run,
            no_discovery,
        ),
        name=f"new-wine-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_slow_listening_job(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Slow Listening web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_slow_listening",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Slow Listening flush queued in dry-run mode."
                if dry_run
                else "Slow Listening flush queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_slow_listening_job,
        args=(job_id, spotify, playlist_id, dry_run),
        name=f"slow-listening-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_something_old_job(
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one interactive Something Old job with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="something_old",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Something Old queued in dry-run mode."
                if dry_run
                else "Something Old queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_something_old_job,
        args=(job_id, spotify, playlist_id, api_key, username, dry_run),
        name=f"something-old-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_release_check_job(
    spotify: Spotify,
    playlists: release_check.ReleaseCheckPlaylists,
    api_key: str,
    username: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one interactive release check with reload-safe web state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="check_new_releases",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "New-release check queued in dry-run mode."
                if dry_run
                else "New-release check queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_release_check_job,
        args=(job_id, spotify, playlists, api_key, username, dry_run),
        name=f"release-check-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_discography_job(
    spotify: Spotify,
    playlist_ids: dict[discography.QueueName, str],
    queue_3_playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one interactive discography planner with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="plan_discographies",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Discography planning queued in dry-run mode."
                if dry_run
                else "Discography planning queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_discography_job,
        args=(job_id, spotify, playlist_ids, queue_3_playlist_id, dry_run),
        name=f"discography-plan-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_requeue_for_a_dream_job(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Requeue for a Dream job with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_requeue_for_a_dream",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Requeue for a Dream queued in dry-run mode."
                if dry_run
                else "Requeue for a Dream queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_requeue_for_a_dream_job,
        args=(job_id, spotify, playlist_id, dry_run),
        name=f"requeue-for-a-dream-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_palace_of_memory_job(
    spotify: Spotify,
    playlist_id: str | None,
    *,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> BlastJobResult:
    """Start one reload-safe Palace fill or cursor adjustment."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        cursor_only = cursor_position is not None
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_palace_of_memory",
                dry_run=dry_run,
                palace_cursor_only=cursor_only,
                palace_alphabetical_reference=(
                    str(cursor_position) if cursor_only else alphabetical_start
                ),
            )
        )
        queued_message = (
            f"Palace alphabetical cursor adjustment to {cursor_position} queued."
            if cursor_only
            else (
                "Palace of Memory queued in dry-run mode."
                if dry_run
                else "Palace of Memory queued."
            )
        )
        _append_blast_log_locked(job, queued_message)
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_palace_of_memory_job,
        args=(
            job_id,
            spotify,
            playlist_id,
            dry_run,
            alphabetical_start,
            cursor_position,
        ),
        name=f"palace-of-memory-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_scrobble_history_job(
    api_key: str,
    username: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one shared Last.fm history refresh with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist or history routine is running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="update_scrobble_history",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Last.fm scrobble history update queued in dry-run mode."
                if dry_run
                else "Last.fm scrobble history update queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_scrobble_history_job,
        args=(job_id, api_key, username, dry_run),
        name=f"scrobble-history-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


app = FastAPI(title="Spotify Manager", version="0.1.0")


@app.exception_handler(ArtistNotFoundError)
def _artist_not_found(request: Request, exc: ArtistNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousArtistError)
def _ambiguous_artist(request: Request, exc: AmbiguousArtistError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "candidates": exc.candidates},
    )


@app.exception_handler(AlbumNotFoundError)
def _album_not_found(request: Request, exc: AlbumNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousAlbumError)
def _ambiguous_album(request: Request, exc: AmbiguousAlbumError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


@app.exception_handler(SpotifyLookupResponseError)
def _invalid_spotify_lookup(
    request: Request,
    exc: SpotifyLookupResponseError,
) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(SpotifyException)
def _spotify_lookup_failed(request: Request, exc: SpotifyException) -> JSONResponse:
    """Return useful lookup errors instead of an opaque HTTP 500 response."""
    if exc.http_status == 429:
        retry_after = review_album_limits.get_retry_after_seconds(exc)
        detail = (
            "Spotify rate limit reached after trying all configured credentials. "
            f"{review_album_limits.format_retry_after(retry_after)}."
        )
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return JSONResponse(
            status_code=429,
            content={"detail": detail},
            headers=headers,
        )

    status_code = exc.http_status if exc.http_status in {400, 403, 404} else 502
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": (
                f"Spotify request failed (HTTP {exc.http_status}): "
                f"{exc.msg or 'unknown Spotify error'}"
            )
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/auth/check")
def auth_check() -> dict[str, str]:
    """Side-effect-free password check protected by the deployment middleware."""
    return {"status": "ok"}


@app.get("/state/summary", response_model=SharedStateSummary)
def shared_state_summary() -> SharedStateSummary:
    """Return state freshness without transferring the complete document."""
    try:
        snapshot = get_state_service().snapshot()
    except StateConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    namespaces = snapshot.document["namespaces"]
    return SharedStateSummary(
        revision=snapshot.revision,
        updated_at=snapshot.document["updated_at"],
        namespaces={
            name: str(envelope["updated_at"]) for name, envelope in namespaces.items()
        },
    )


@app.get("/state", response_model=SharedStateSnapshot)
def shared_state() -> SharedStateSnapshot:
    """Return the complete shared application state and revision guard."""
    try:
        snapshot = get_state_service().snapshot()
    except StateConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SharedStateSnapshot(
        revision=snapshot.revision,
        document=snapshot.document,
    )


@app.get("/state/schema")
def shared_state_editor_schema() -> dict[str, Any]:
    """Return backend-owned controls and constraints for manual state edits."""
    schema = state_editor_schema()
    if set(schema["namespaces"]) != set(STATE_NAMESPACE_DEFINITIONS):
        raise HTTPException(
            status_code=500,
            detail="State editor schema and namespace validators are out of sync.",
        )
    return schema


@app.put(
    "/state/namespaces/{namespace}",
    response_model=SharedStateSnapshot,
)
def replace_shared_state_namespace(
    namespace: str,
    request: SharedStateNamespaceReplaceRequest,
) -> SharedStateSnapshot:
    """Validate and replace only one namespace at the viewed revision."""
    definition = STATE_NAMESPACE_DEFINITIONS.get(namespace)
    if definition is None:
        raise HTTPException(status_code=404, detail="Unknown state namespace.")
    default_factory, validator = definition
    service = get_state_service()
    try:
        current_snapshot = service.snapshot()
        current = namespace_value(current_snapshot.document, namespace)
        validate_namespace_editor_change(
            namespace,
            current if current is not None else default_factory(),
            request.value,
        )
        snapshot = service.replace_namespace(
            namespace,
            request.value,
            expected_revision=request.expected_revision,
            validator=validator,
            message=f"Edit {namespace} state from web app",
        )
    except StateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StateDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StateConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SharedStateSnapshot(
        revision=snapshot.revision,
        document=snapshot.document,
    )


@app.put("/state", response_model=SharedStateSnapshot)
def replace_shared_state(request: SharedStateReplaceRequest) -> SharedStateSnapshot:
    """Manually replace shared state only when the viewed revision is current."""
    try:
        snapshot = get_state_service().replace(
            request.document,
            expected_revision=request.expected_revision,
            message="Edit Spotify Manager state from web app",
        )
    except StateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StateDocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StateConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SharedStateSnapshot(
        revision=snapshot.revision,
        document=snapshot.document,
    )


@app.get("/state/export")
def export_shared_state() -> Response:
    """Download the current shared state as a JSON snapshot."""
    try:
        snapshot = get_state_service().snapshot()
    except StateConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Response(
        canonical_json(
            {
                "revision": snapshot.revision,
                "document": snapshot.document,
            }
        )
        + "\n",
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="spotify-manager-state-{timestamp}.json"'
            )
        },
    )


@app.post("/library/refresh", response_model=CommandResult)
def refresh_library() -> CommandResult:
    """Drop the cached library so the next request re-reads YourLibrary.json."""
    get_library.cache_clear()
    return CommandResult(command="library_refresh")


# --------------------------------------------------------------------------- #
# Live Spotify lookups
# --------------------------------------------------------------------------- #
@app.get("/artists/stats", response_model=ArtistLibraryStats)
def artist_stats(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    artist_id: Annotated[str | None, Query()] = None,
) -> ArtistLibraryStats:
    """Return live Liked Songs and Saved Albums counts for one artist."""
    if reference is not None:
        try:
            name, artist_id = parse_spotify_lookup_reference(reference, "artist")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not name and not artist_id:
        raise HTTPException(
            status_code=400,
            detail="provide an artist name, ID, or Spotify link",
        )
    try:
        return get_live_artist_library_stats(
            client,
            name=name,
            artist_id=artist_id,
        )
    except RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Spotify could not be reached after several attempts. "
                "Please try again shortly."
            ),
        ) from exc


@app.get("/albums/evaluation", response_model=AlbumEvaluation)
def album_evaluation(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    album_id: Annotated[str | None, Query()] = None,
    artist: Annotated[str | None, Query()] = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Return a keep/remove decision from live Spotify album and liked state."""
    if reference is not None:
        try:
            name, album_id = parse_spotify_lookup_reference(reference, "album")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not name and not album_id:
        raise HTTPException(
            status_code=400,
            detail="provide an album name, ID, or Spotify link",
        )
    try:
        return evaluate_album_live(
            client,
            name=name,
            album_id=album_id,
            artist=artist,
            threshold=threshold,
        )
    except RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Spotify could not be reached after several attempts. "
                "Please try again shortly."
            ),
        ) from exc


# --------------------------------------------------------------------------- #
# Mirrored CLI commands
# --------------------------------------------------------------------------- #
@app.post("/commands/monthly-routines", response_model=CommandResult)
def cmd_monthly_routines(client: ClientDep) -> CommandResult:
    """Run the full monthly routine (compare, convert, monthly)."""
    compare_your_library_and_all_albums()
    convert_your_library_file(client)
    run_monthly_routines(client)
    return CommandResult(command="monthly_routines")


@app.post("/commands/update-total-albums", response_model=CommandResult)
def cmd_update_total_albums(
    client: ClientDep, just_update: bool = False
) -> CommandResult:
    """Update the total album list."""
    albums = update_total_album_list(client, just_update)
    return CommandResult(
        command="update_total_albums", detail=f"{len(albums)} albums in list"
    )


@app.post("/commands/restore-your-library", response_model=CommandResult)
def cmd_restore_your_library(client: ClientDep) -> CommandResult:
    """Restore artists and tracks from the YourLibrary file."""
    restore_your_library_from_file(client)
    return CommandResult(command="restore_your_library")


@app.post("/commands/compare-lib-files", response_model=CommandResult)
def cmd_compare_lib_files() -> CommandResult:
    """Create the comparison between YourLibrary and the total-albums file."""
    compare_your_library_and_all_albums()
    return CommandResult(command="compare_lib_files")


@app.post("/commands/analyse-comp", response_model=CommandResult)
def cmd_analyse_comp(client: ClientDep) -> CommandResult:
    """Analyse the saved comparison file against the live library."""
    analyse_comparison(client)
    return CommandResult(command="analyse_comp")


@app.post("/commands/convert-lib", response_model=CommandResult)
def cmd_convert_lib(client: ClientDep) -> CommandResult:
    """Convert the YourLibrary file into the total-albums file."""
    convert_your_library_file(client)
    return CommandResult(command="convert_lib")


@app.get("/commands/count-artists", response_model=CountResult)
def cmd_count_artists() -> CountResult:
    """Count the artists in the YourLibrary file."""
    return CountResult(count=count_artists_in_library())


@app.post(
    "/commands/blast-from-the-past",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_blast_from_the_past(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
) -> BlastJobResult:
    """Start a background Friday-routine playlist update."""
    if count is not None and max_playlist_length is not None:
        raise HTTPException(
            status_code=400,
            detail="use either count or max_playlist_length, not both",
        )
    effective_count = 10 if count is None and max_playlist_length is None else count
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            Settings().blast_from_the_past_playlist
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_blast_job(
        client,
        playlist_id,
        effective_count,
        max_playlist_length,
    )


@app.get(
    "/commands/blast-from-the-past-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_blast_jobs() -> list[BlastJobResult]:
    """Return active playlist jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "blast_from_the_past"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/blast-from-the-past-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_blast_job(job_id: str) -> BlastJobResult:
    """Return current progress for one playlist job."""
    job = get_blast_job(job_id, command="blast_from_the_past")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/blast-from-the-past-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_blast_job(job_id: str) -> BlastJobResult:
    """Stop a Blast job at the next bounded network-operation boundary."""
    return _cancel_simple_playlist_job(
        job_id,
        command="blast_from_the_past",
        detail="Stopping A blast from the past",
    )


@app.post(
    "/commands/daily-mind-radio",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_daily_mind_radio(client: InteractiveClientDep) -> BlastJobResult:
    """Start a background Daily Mind Radio anniversary update."""
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            Settings().daily_mind_radio_playlist,
            setting_name="DAILY_MIND_RADIO_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_daily_mind_radio_job(client, playlist_id)


@app.get(
    "/commands/daily-mind-radio-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_daily_mind_radio_jobs() -> list[BlastJobResult]:
    """Return active Daily Mind Radio jobs for web reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "daily_mind_radio"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/daily-mind-radio-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Daily Mind Radio job."""
    job = get_blast_job(job_id, command="daily_mind_radio")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/daily-mind-radio-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Stop Daily Mind Radio at the next bounded network-operation boundary."""
    return _cancel_simple_playlist_job(
        job_id,
        command="daily_mind_radio",
        detail="Stopping Daily Mind Radio",
    )


@app.post(
    "/commands/found-art",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_found_art(
    client: ClientDep,
    count: Annotated[int, Query(ge=1)] = found_art.DEFAULT_COUNT,
) -> BlastJobResult:
    """Start a background Found Art recommendation update."""
    configuration = Settings()
    try:
        playlist_id = found_art.parse_found_art_playlist_id(
            configuration.found_art_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_found_art_job(
        client,
        playlist_id,
        api_key,
        username,
        count,
    )


@app.get(
    "/commands/found-art-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_found_art_jobs() -> list[BlastJobResult]:
    """Return active Found Art jobs for web reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "found_art"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/found-art-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_found_art_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Found Art job."""
    job = get_blast_job(job_id, command="found_art")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-sauvignon-from-lastfm",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_fill_sauvignon_from_lastfm(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    seed_count: Annotated[int, Query(ge=1)] = sauvignon.DEFAULT_SEED_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start reconnectable Last.fm album discovery for Sauvignon."""
    if count is not None and max_playlist_length is not None:
        raise HTTPException(
            status_code=400,
            detail="use either count or maximum playlist length, not both",
        )
    configuration = Settings()
    try:
        playlist_id = sauvignon.parse_playlist_id(
            configuration.sauvignon_terre_neuve_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (sauvignon.SauvignonConfigError, found_art.FoundArtConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    effective_maximum = (
        sauvignon.DEFAULT_MAX_PLAYLIST_LENGTH
        if count is None and max_playlist_length is None
        else max_playlist_length
    )
    return start_sauvignon_job(
        client,
        playlist_id,
        api_key,
        username,
        count=count,
        max_playlist_length=effective_maximum,
        seed_count=seed_count,
        dry_run=dry_run,
    )


@app.get(
    "/commands/fill-sauvignon-from-lastfm-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_sauvignon_jobs() -> list[BlastJobResult]:
    """Return active Sauvignon jobs so the UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "fill_sauvignon_from_lastfm"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_sauvignon_job(job_id: str) -> BlastJobResult:
    """Return Sauvignon progress and any pending album-edition choice."""
    job = get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_sauvignon_album(
    job_id: str,
    request: SauvignonChoiceRequest,
) -> BlastJobResult:
    """Submit one ambiguous Spotify album edition, skip, or quit choice."""
    job = get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with _blast_jobs_lock:
        pending = job.result.sauvignon_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Sauvignon discovery is not waiting for an album choice",
            )
        allowed = {
            sauvignon.CHOICE_SKIP,
            sauvignon.CHOICE_QUIT,
            *(option.spotify_id for option in pending.options),
        }
        if request.choice not in allowed:
            raise HTTPException(status_code=400, detail="album choice is not available")
        job.submitted_choice = request.choice
        job.result.sauvignon_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Sauvignon album choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_sauvignon_job(job_id: str) -> BlastJobResult:
    """Stop Sauvignon discovery at its next safe boundary."""
    job = get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Sauvignon discovery job is not active",
            )
        job.result.status = "cancelling"
        job.result.sauvignon_pending_choice = None
        job.result.detail = "Stopping Sauvignon album discovery"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


def _configured_queue_playlists() -> the_queue.QueuePlaylists:
    """Parse every playlist shared by Queue fill and flush operations."""
    configuration = Settings()
    try:
        return the_queue.QueuePlaylists.from_references(
            configuration.the_queue_playlist,
            configuration.the_queue_2_playlist,
            configuration.new_kids_on_the_block_playlist,
            configuration.the_queue_3_playlist,
            configuration.unlucky_ones_playlist,
        )
    except the_queue.QueueConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/commands/fill-queue-from-lastfm",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_fill_queue_from_lastfm(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    seed_count: Annotated[int, Query(ge=1)] = the_queue.DEFAULT_SEED_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start reconnectable Last.fm artist discovery for The Queue."""
    if count is not None and max_playlist_length is not None:
        raise HTTPException(
            status_code=400,
            detail="use either count or maximum playlist length, not both",
        )
    configuration = Settings()
    playlists = _configured_queue_playlists()
    try:
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    effective_count = (
        the_queue.DEFAULT_COUNT
        if count is None and max_playlist_length is None
        else count
    )
    return start_queue_fill_job(
        client,
        playlists,
        api_key,
        username,
        count=effective_count,
        max_playlist_length=max_playlist_length,
        seed_count=seed_count,
        dry_run=dry_run,
    )


@app.get(
    "/commands/fill-queue-from-lastfm-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_queue_fill_jobs() -> list[BlastJobResult]:
    """Return active Queue fill jobs so the UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "fill_queue_from_lastfm"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/fill-queue-from-lastfm-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_queue_fill_job(job_id: str) -> BlastJobResult:
    """Return Queue fill progress and any pending artist mapping."""
    job = get_blast_job(job_id, command="fill_queue_from_lastfm")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_queue_artist(
    job_id: str,
    request: QueueChoiceRequest,
) -> BlastJobResult:
    """Submit one Spotify artist mapping, custom search, skip, or quit."""
    job = get_blast_job(job_id, command="fill_queue_from_lastfm")
    with _blast_jobs_lock:
        pending = job.result.queue_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Queue fill is not waiting for an artist mapping",
            )
        allowed = {
            the_queue.CHOICE_SKIP,
            the_queue.CHOICE_QUIT,
            *(candidate.spotify_id for candidate in pending.candidates),
        }
        custom_search = request.choice.startswith(the_queue.CHOICE_SEARCH_PREFIX)
        if custom_search:
            custom_search = bool(
                request.choice.removeprefix(the_queue.CHOICE_SEARCH_PREFIX).strip()
            )
        if request.choice not in allowed and not custom_search:
            raise HTTPException(
                status_code=400,
                detail="artist choice is not available",
            )
        job.submitted_choice = request.choice
        job.result.queue_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Queue artist choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


def _cancel_queue_job(job_id: str, command: str, label: str) -> BlastJobResult:
    """Signal one active Queue fill or flush worker to stop cleanly."""
    job = get_blast_job(job_id, command=command)
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail=f"{label} job is not active")
        job.result.status = "cancelling"
        job.result.queue_pending_choice = None
        job.result.detail = f"Stopping {label}"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-queue-from-lastfm-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_queue_fill_job(job_id: str) -> BlastJobResult:
    """Stop Queue artist discovery at its next safe boundary."""
    return _cancel_queue_job(job_id, "fill_queue_from_lastfm", "Queue fill")


@app.post(
    "/commands/flush-queue",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_queue(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a reconnectable flush of the first ten Queue artists."""
    return start_queue_flush_job(
        client,
        _configured_queue_playlists(),
        dry_run=dry_run,
    )


@app.get(
    "/commands/flush-queue-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_queue_flush_jobs() -> list[BlastJobResult]:
    """Return active Queue flush jobs for page reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_queue"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-queue-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_queue_flush_job(job_id: str) -> BlastJobResult:
    """Return current Queue flush progress and result details."""
    job = get_blast_job(job_id, command="flush_queue")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_queue_flush_job(job_id: str) -> BlastJobResult:
    """Stop a Queue flush while preserving its durable checkpoint."""
    return _cancel_queue_job(job_id, "flush_queue", "Queue flush")


@app.post(
    "/commands/flush-new-kids",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_new_kids(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive New Kids flush with reconnectable web state."""
    playlist_ids = _configured_album_discovery_playlists()
    return start_new_kids_job(client, *playlist_ids, dry_run=dry_run)


def _configured_album_discovery_playlists() -> tuple[str, str, str, str, str]:
    """Load the five shared New Kids and Queue 2 playlist settings."""
    configuration = Settings()
    try:
        new_kids_playlist_id = new_kids.parse_playlist_id(
            configuration.new_kids_on_the_block_playlist,
            "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
        )
        queue_2_playlist_id = new_kids.parse_playlist_id(
            configuration.the_queue_2_playlist,
            "THE_QUEUE_2_PLAYLIST",
        )
        great_discoveries_playlist_id = new_kids.parse_playlist_id(
            configuration.great_discoveries_2026_playlist,
            "GREAT_DISCOVERIES_2026_PLAYLIST",
        )
        unlucky_ones_playlist_id = new_kids.parse_playlist_id(
            configuration.unlucky_ones_playlist,
            "UNLUCKY_ONES_PLAYLIST",
        )
        newfoundland_playlist_id = new_kids.parse_playlist_id(
            configuration.discography_newfoundland_playlist,
            "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
        )
    except new_kids.NewKidsConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return (
        new_kids_playlist_id,
        queue_2_playlist_id,
        great_discoveries_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
    )


@app.get(
    "/commands/flush-new-kids-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_new_kids_jobs() -> list[BlastJobResult]:
    """Return active New Kids jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_new_kids"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-new-kids-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_new_kids_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending New Kids choice."""
    job = get_blast_job(job_id, command="flush_new_kids")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-kids-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_new_kids_release(
    job_id: str,
    request: NewKidsChoiceRequest,
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Kids job."""
    job = get_blast_job(job_id, command="flush_new_kids")
    with _blast_jobs_lock:
        pending = job.result.new_kids_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="New Kids job is not waiting for a release choice",
            )
        allowed = {
            new_kids.CHOICE_SKIP,
            new_kids.CHOICE_QUIT,
            *(release.spotify_id for release in pending.releases),
        }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="release choice is not available",
            )
        job.submitted_choice = request.choice
        job.result.new_kids_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-kids-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_new_kids_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Kids processing boundary."""
    job = get_blast_job(job_id, command="flush_new_kids")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="New Kids job is not active")
        job.result.status = "cancelling"
        job.result.new_kids_pending_choice = None
        job.result.detail = "Stopping New Kids flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-2",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_queue_2(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive Queue 2 flush with reconnectable web state."""
    playlist_ids = _configured_album_discovery_playlists()
    return start_queue_2_job(client, *playlist_ids, dry_run=dry_run)


@app.get(
    "/commands/flush-queue-2-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_queue_2_jobs() -> list[BlastJobResult]:
    """Return active Queue 2 jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_queue_2"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-queue-2-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_queue_2_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 2 choice."""
    job = get_blast_job(job_id, command="flush_queue_2")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-2-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_queue_2_release(
    job_id: str,
    request: NewKidsChoiceRequest,
) -> BlastJobResult:
    """Submit one release or control choice to a waiting Queue 2 job."""
    job = get_blast_job(job_id, command="flush_queue_2")
    with _blast_jobs_lock:
        pending = job.result.new_kids_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Queue 2 job is not waiting for a release choice",
            )
        allowed = {
            new_kids.CHOICE_SKIP,
            new_kids.CHOICE_QUIT,
            *(release.spotify_id for release in pending.releases),
        }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="release choice is not available",
            )
        job.submitted_choice = request.choice
        job.result.new_kids_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-2-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_queue_2_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 2 processing boundary."""
    job = get_blast_job(job_id, command="flush_queue_2")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="Queue 2 job is not active")
        job.result.status = "cancelling"
        job.result.new_kids_pending_choice = None
        job.result.detail = "Stopping Queue 2 flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-3",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_queue_3(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive Queue 3 flush with reconnectable web state."""
    configuration = Settings()
    try:
        playlist_id = queue_3.parse_playlist_id(configuration.the_queue_3_playlist)
    except queue_3.Queue3ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_queue_3_job(client, playlist_id, dry_run=dry_run)


@app.get(
    "/commands/flush-queue-3-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_queue_3_jobs() -> list[BlastJobResult]:
    """Return active Queue 3 jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_queue_3"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-queue-3-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_queue_3_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 3 choice."""
    job = get_blast_job(job_id, command="flush_queue_3")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-3-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_queue_3(
    job_id: str,
    request: Queue3ChoiceRequest,
) -> BlastJobResult:
    """Submit one release, composer-playlist, or quit choice to Queue 3."""
    job = get_blast_job(job_id, command="flush_queue_3")
    with _blast_jobs_lock:
        pending = job.result.queue_3_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Queue 3 job is not waiting for a choice",
            )
        if pending.kind == "release":
            allowed = {queue_3.CHOICE_ADVANCE, queue_3.CHOICE_QUIT}
        else:
            allowed = {
                queue_3.CHOICE_QUIT,
                *(playlist.spotify_id for playlist in pending.playlists),
            }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Queue 3 choice is not available",
            )
        job.submitted_choice = request.choice
        job.result.queue_3_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Queue 3 choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-queue-3-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_queue_3_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 3 processing boundary."""
    job = get_blast_job(job_id, command="flush_queue_3")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="Queue 3 job is not active")
        job.result.status = "cancelling"
        job.result.queue_3_pending_choice = None
        job.result.detail = "Stopping Queue 3 flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-wine",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_new_wine(
    client: InteractiveClientDep,
    dry_run: bool = True,
    no_discovery: bool = False,
) -> BlastJobResult:
    """Start an interactive New Wine flush with reconnectable web state."""
    configuration = Settings()
    try:
        new_wine_playlist_id = new_wine.parse_playlist_id(
            configuration.new_wine_from_old_bottles_playlist,
            "NEW_WINE_FROM_OLD_BOTTLES_PLAYLIST",
        )
        sauvignon_playlist_id = new_wine.parse_playlist_id(
            configuration.sauvignon_terre_neuve_playlist,
            "SAUVIGNON_TERRE_NEUVE_PLAYLIST",
        )
        wine_cellar_playlist_id = new_wine.parse_playlist_id(
            configuration.wine_cellar_playlist,
            "WINE_CELLAR_PLAYLIST",
        )
    except new_wine.NewWineConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_new_wine_job(
        client,
        new_wine_playlist_id,
        sauvignon_playlist_id,
        wine_cellar_playlist_id,
        dry_run=dry_run,
        no_discovery=no_discovery,
    )


@app.get(
    "/commands/flush-new-wine-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_new_wine_jobs() -> list[BlastJobResult]:
    """Return active New Wine jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_new_wine"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-new-wine-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_new_wine_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending choice for one New Wine job."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-wine-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_new_wine_release(
    job_id: str,
    request: NewWineChoiceRequest,
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Wine job."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        pending = job.result.pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="New Wine job is not waiting for a release choice",
            )
        allowed = {
            new_wine.CHOICE_DROP,
            new_wine.CHOICE_SKIP,
            new_wine.CHOICE_QUIT,
            *(release.spotify_id for release in pending.releases),
        }
        if pending.terminal_release:
            allowed.add(new_wine.CHOICE_FINISH)
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="release choice is not available",
            )
        job.submitted_choice = request.choice
        job.result.pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-wine-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_new_wine_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Wine processing boundary."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="New Wine job is not active")
        job.result.status = "cancelling"
        job.result.pending_choice = None
        job.result.detail = "Stopping New Wine flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-slow-listening",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_slow_listening(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive Slow Listening flush with reconnectable state."""
    configuration = Settings()
    try:
        playlist_id = slow_listening.parse_playlist_id(
            configuration.slow_listening_playlist
        )
    except slow_listening.SlowListeningConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_slow_listening_job(
        client,
        playlist_id,
        dry_run=dry_run,
    )


@app.get(
    "/commands/flush-slow-listening-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_slow_listening_jobs() -> list[BlastJobResult]:
    """Return active Slow Listening jobs for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_slow_listening"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-slow-listening-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_slow_listening_job(job_id: str) -> BlastJobResult:
    """Return current progress and the pending Slow Listening choice."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-slow-listening-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_slow_listening_track(
    job_id: str,
    request: SlowListeningChoiceRequest,
) -> BlastJobResult:
    """Submit a candidate, release order, or completion acknowledgement."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        pending = job.result.slow_listening_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Slow Listening job is not waiting for a choice",
            )

        submitted_order: tuple[str, ...] | None = None
        if pending.kind == "track":
            allowed = {
                slow_listening.CHOICE_ADVANCE,
                slow_listening.CHOICE_SKIP,
                slow_listening.CHOICE_QUIT,
            }
            if request.choice not in allowed or request.order:
                raise HTTPException(
                    status_code=400,
                    detail="track choice is not available",
                )
        elif pending.kind == "release_order":
            expected_ids = {release.spotify_id for release in pending.releases}
            submitted_order = tuple(request.order)
            if (
                request.choice != "order"
                or len(submitted_order) != len(expected_ids)
                or set(submitted_order) != expected_ids
            ):
                raise HTTPException(
                    status_code=400,
                    detail="release order must include every option exactly once",
                )
        elif request.choice != "continue" or request.order:
            raise HTTPException(
                status_code=400,
                detail="completion choice is not available",
            )

        job.submitted_choice = request.choice
        job.submitted_order = submitted_order
        job.result.slow_listening_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Slow Listening choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-slow-listening-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_slow_listening_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Slow Listening boundary."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Slow Listening job is not active",
            )
        job.result.status = "cancelling"
        job.result.slow_listening_pending_choice = None
        job.result.detail = "Stopping Slow Listening flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/something-old",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_something_old(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive Something Old selection with reconnectable state."""
    configuration = Settings()
    try:
        playlist_id = something_old.parse_playlist_id(
            configuration.something_old_new_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (
        something_old.SomethingOldConfigError,
        found_art.FoundArtConfigError,
    ) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_something_old_job(
        client,
        playlist_id,
        api_key,
        username,
        dry_run=dry_run,
    )


@app.get(
    "/commands/something-old-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_something_old_jobs() -> list[BlastJobResult]:
    """Return active Something Old jobs for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "something_old"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/something-old-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_something_old_job(job_id: str) -> BlastJobResult:
    """Return current Something Old progress and any pending choice."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/something-old-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_something_old(
    job_id: str,
    request: SomethingOldChoiceRequest,
) -> BlastJobResult:
    """Submit an exact artist, source mode, album/EP, or quit choice."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        pending = job.result.something_old_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Something Old job is not waiting for a choice",
            )

        if pending.kind == "artist":
            allowed = {
                "quit",
                *(candidate.spotify_id for candidate in pending.artist_candidates),
            }
        elif pending.kind == "mode":
            allowed = {
                "lastfm_top_tracks",
                "spotify_top_tracks",
                "album",
                "quit",
            }
        else:
            allowed = {
                "quit",
                *(release.spotify_id for release in pending.releases),
            }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Something Old choice is not available",
            )

        job.submitted_choice = request.choice
        job.result.something_old_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Something Old choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/something-old-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_something_old_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Something Old boundary."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Something Old job is not active",
            )
        job.result.status = "cancelling"
        job.result.something_old_pending_choice = None
        job.result.detail = "Stopping Something Old"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/check-new-releases",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_check_new_releases(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a reconnectable release check for Last.fm's top artists."""
    configuration = Settings()
    try:
        playlists = release_check.ReleaseCheckPlaylists.from_references(
            configuration.wine_cellar_playlist,
            configuration.new_vintage_playlist,
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (
        release_check.ReleaseCheckConfigError,
        found_art.FoundArtConfigError,
    ) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_release_check_job(
        client,
        playlists,
        api_key,
        username,
        dry_run=dry_run,
    )


@app.get(
    "/commands/check-new-releases-state",
    response_model=ReleaseCheckStateSnapshot,
)
def cmd_release_check_state(
    known_fingerprint: str | None = None,
) -> ReleaseCheckStateSnapshot:
    """Return restart state, omitting the payload when the browser is current."""
    try:
        return _release_check_state_snapshot(known_fingerprint)
    except (release_check.ReleaseCheckStateError, StateError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put(
    "/commands/check-new-releases-state",
    response_model=ReleaseCheckStateSnapshot,
)
def cmd_restore_release_check_state(
    request: ReleaseCheckStateRestoreRequest,
) -> ReleaseCheckStateSnapshot:
    """Restore a newer browser mirror without overwriting concurrent progress."""
    with _blast_jobs_lock:
        if any(
            job.result.command == "check_new_releases"
            and job.result.status in _ACTIVE_JOB_STATUSES
            for job in _blast_jobs.values()
        ):
            raise HTTPException(
                status_code=409,
                detail="New-release check is active; state restore was not applied",
            )
        try:
            candidate = release_check.validate_state(request.state)
            state_access = get_state_service().namespace(
                "release_check",
                release_check._default_state,
                release_check.validate_state,
            )
            current = state_access.load()
            current_fingerprint = release_check.state_fingerprint(current)
            if current_fingerprint != request.expected_server_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Release-check state changed; reload before restoring",
                )
            if not _release_state_is_newer(candidate, current):
                raise HTTPException(
                    status_code=409,
                    detail="Browser release-check state is not newer",
                )
            state_access.save(
                candidate,
                message="Restore newer browser release-check state",
            )
            return _release_check_state_snapshot()
        except StateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except release_check.ReleaseCheckStateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/commands/check-new-releases-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_release_check_jobs() -> list[BlastJobResult]:
    """Return active release checks for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "check_new_releases"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/check-new-releases-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_release_check_job(job_id: str) -> BlastJobResult:
    """Return release-check progress and any pending interaction."""
    job = get_blast_job(job_id, command="check_new_releases")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/check-new-releases-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_release_check(
    job_id: str,
    request: ReleaseCheckChoiceRequest,
) -> BlastJobResult:
    """Submit an artist mapping, custom search, or release decision."""
    job = get_blast_job(job_id, command="check_new_releases")
    with _blast_jobs_lock:
        pending = job.result.release_check_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="New-release check is not waiting for a choice",
            )

        if pending.kind == "artist":
            allowed = {
                release_check.CHOICE_SKIP,
                release_check.CHOICE_SKIP_ARTIST,
                release_check.CHOICE_QUIT,
                *(candidate.spotify_id for candidate in pending.artist_candidates),
            }
            custom_search = request.choice.startswith(
                release_check.CHOICE_SEARCH_PREFIX
            )
            search_text = request.choice.removeprefix(
                release_check.CHOICE_SEARCH_PREFIX
            ).strip()
            if request.choice not in allowed and not (custom_search and search_text):
                raise HTTPException(
                    status_code=400,
                    detail="artist mapping choice is not available",
                )
        elif request.choice not in {
            release_check.CHOICE_ADD,
            release_check.CHOICE_PENDING,
            release_check.CHOICE_SKIP,
            release_check.CHOICE_QUIT,
        } or (
            request.choice == release_check.CHOICE_PENDING
            and not pending.unattached_single
        ):
            raise HTTPException(
                status_code=400,
                detail="release review choice is not available",
            )

        job.submitted_choice = request.choice
        job.result.release_check_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release-check choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/check-new-releases-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_release_check_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next release-check boundary."""
    job = get_blast_job(job_id, command="check_new_releases")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="New-release check is not active",
            )
        job.result.status = "cancelling"
        job.result.release_check_pending_choice = None
        job.result.detail = "Stopping new-release check"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/plan-discographies",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_plan_discographies(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a reload-safe interactive discography planning job."""
    configuration = Settings()
    try:
        playlist_ids = discography.parse_playlist_ids(
            configuration.discography_newfoundland_playlist,
            configuration.discography_memory_lane_playlist,
            configuration.discography_requeue_playlist,
        )
        queue_3_playlist_id = discography.parse_playlist_id(
            configuration.the_queue_3_playlist,
            "THE_QUEUE_3_PLAYLIST",
        )
    except discography.DiscographyConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_discography_job(
        client,
        playlist_ids,
        queue_3_playlist_id,
        dry_run=dry_run,
    )


@app.get(
    "/commands/plan-discographies-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_discography_jobs() -> list[BlastJobResult]:
    """Return active discography jobs for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "plan_discographies"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/plan-discographies-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_discography_job(job_id: str) -> BlastJobResult:
    """Return discography progress and its current interaction."""
    job = get_blast_job(job_id, command="plan_discographies")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/plan-discographies-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_discography(
    job_id: str,
    request: DiscographyChoiceRequest,
) -> BlastJobResult:
    """Submit a release checklist or final marker-removal decision."""
    job = get_blast_job(job_id, command="plan_discographies")
    with _blast_jobs_lock:
        pending = job.result.discography_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Discography job is not waiting for a choice",
            )

        if pending.kind == "releases":
            if request.choice not in {"select", "none", "quit"}:
                raise HTTPException(
                    status_code=400,
                    detail="release checklist choice is not available",
                )
            available = {release.spotify_id for release in pending.releases}
            selected = set(request.release_ids)
            if request.choice == "select" and (
                not request.release_ids
                or len(selected) != len(request.release_ids)
                or not selected.issubset(available)
            ):
                raise HTTPException(
                    status_code=400,
                    detail="selected releases are not available",
                )
        elif request.choice not in {"apply", "keep", "quit"}:
            raise HTTPException(
                status_code=400,
                detail="final discography choice is not available",
            )

        job.submitted_choice = request.choice
        job.submitted_order = tuple(request.release_ids)
        job.result.discography_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Discography choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/plan-discographies-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_discography_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next discography boundary."""
    job = get_blast_job(job_id, command="plan_discographies")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Discography job is not active",
            )
        job.result.status = "cancelling"
        job.result.discography_pending_choice = None
        job.result.detail = "Stopping discography planning"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-requeue-for-a-dream",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_requeue_for_a_dream(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a reconnectable Requeue for a Dream transition."""
    configuration = Settings()
    try:
        playlist_id = requeue_for_a_dream.parse_playlist_id(
            configuration.reqeueue_for_a_dream_playlist
        )
    except requeue_for_a_dream.RequeueForADreamConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_requeue_for_a_dream_job(
        client,
        playlist_id,
        dry_run=dry_run,
    )


@app.get(
    "/commands/flush-requeue-for-a-dream-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_requeue_for_a_dream_jobs() -> list[BlastJobResult]:
    """Return active Requeue for a Dream jobs after a page reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_requeue_for_a_dream"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-requeue-for-a-dream-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one Requeue transition."""
    job = get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-requeue-for-a-dream-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next API or retry boundary."""
    job = get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Requeue for a Dream job is not active",
            )
        job.result.status = "cancelling"
        job.result.detail = "Stopping Requeue for a Dream"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-palace-of-memory",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_fill_palace_of_memory(
    client: InteractiveClientDep,
    dry_run: bool = True,
    alphabetical_start: str | None = None,
    set_alphabetical_cursor: int | None = Query(default=None, ge=1),
) -> BlastJobResult:
    """Start a reconnectable Palace fill or cursor-only adjustment."""
    cleaned_start = alphabetical_start.strip() if alphabetical_start else None
    if set_alphabetical_cursor is not None and dry_run:
        raise HTTPException(
            status_code=400,
            detail=(
                "set_alphabetical_cursor persists immediately and cannot use dry_run"
            ),
        )
    if set_alphabetical_cursor is not None and cleaned_start is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "use either set_alphabetical_cursor or alphabetical_start, not both"
            ),
        )

    playlist_id = None
    if set_alphabetical_cursor is None:
        configuration = Settings()
        try:
            playlist_id = palace_of_memory.parse_playlist_id(
                configuration.palace_of_memory_playlist
            )
        except palace_of_memory.PalaceOfMemoryConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return start_palace_of_memory_job(
        client,
        playlist_id,
        dry_run=dry_run,
        alphabetical_start=cleaned_start,
        cursor_position=set_alphabetical_cursor,
    )


@app.get(
    "/commands/fill-palace-of-memory-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_palace_of_memory_jobs() -> list[BlastJobResult]:
    """Return active Palace jobs after a page reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "fill_palace_of_memory"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/fill-palace-of-memory-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Return current Palace progress, results, and logs."""
    job = get_blast_job(job_id, command="fill_palace_of_memory")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-palace-of-memory-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Request a clean Palace stop at the next API or retry boundary."""
    job = get_blast_job(job_id, command="fill_palace_of_memory")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Palace of Memory job is not active",
            )
        job.result.status = "cancelling"
        job.result.detail = "Stopping Palace of Memory"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/update-scrobble-history",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_update_scrobble_history(
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a background refresh of the shared Last.fm scrobble record."""
    configuration = Settings()
    try:
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_scrobble_history_job(
        api_key,
        username,
        dry_run=dry_run,
    )


def _server_file_status(path: Path) -> ServerFileStatus:
    """Return a UTC modification timestamp without failing on a missing file."""
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except FileNotFoundError:
        return ServerFileStatus(filename=path.name, exists=False)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read server file status for {path.name}.",
        ) from exc
    return ServerFileStatus(
        filename=path.name,
        exists=True,
        updated_at=modified_at,
    )


@app.get(
    "/library-mirrors/status",
    response_model=LibraryMirrorFilesStatus,
)
def library_mirror_files_status() -> LibraryMirrorFilesStatus:
    """Return update timestamps for New Wine's canonical mirror files."""
    return LibraryMirrorFilesStatus(
        files=[_server_file_status(path) for path in LIBRARY_MIRROR_FILE_PATHS]
    )


@app.get(
    "/commands/update-scrobble-history-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_scrobble_history_jobs() -> list[BlastJobResult]:
    """Return active history refreshes for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "update_scrobble_history"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/update-scrobble-history-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one history refresh."""
    job = get_blast_job(job_id, command="update_scrobble_history")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/analyse-library-async",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_analyse_library_async() -> AnalysisJobResult:
    """Start an export-only ``*_async`` library analysis."""
    return start_analysis_job("async")


@app.post(
    "/commands/analyse-library-sync",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_analyse_library_sync(client: AnalysisClientDep) -> AnalysisJobResult:
    """Start a live-only ``*_sync`` library analysis."""
    return start_analysis_job("sync", client)


@app.post(
    "/commands/refresh-library-mirrors",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_refresh_library_mirrors(
    client: AnalysisClientDep,
    full_rebuild: bool = False,
) -> AnalysisJobResult:
    """Refresh canonical saved-album and liked-track mirrors from Spotify."""
    return start_analysis_job("mirrors", client, full_rebuild=full_rebuild)


@app.post(
    "/commands/refresh-library-mirrors/{resource}",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_refresh_library_mirror_resource(
    resource: library_analysis.ResourceName,
    client: AnalysisClientDep,
    full_rebuild: bool = False,
) -> AnalysisJobResult:
    """Refresh one canonical Spotify mirror with independent progress."""
    return start_analysis_job(
        "mirrors",
        client,
        full_rebuild=full_rebuild,
        mirror_resource=resource,
    )


@app.get(
    "/commands/library-analysis-jobs",
    response_model=list[AnalysisJobResult],
)
def cmd_active_library_analysis_jobs() -> list[AnalysisJobResult]:
    """Return active analyses so the web UI can reconnect after a reload."""
    with _analysis_jobs_lock:
        return [
            _job_snapshot(job)
            for job in _analysis_jobs.values()
            if job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/library-analysis-jobs/{job_id}",
    response_model=AnalysisJobResult,
)
def cmd_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Return current progress for one library analysis job."""
    job = get_analysis_job(job_id)
    with _analysis_jobs_lock:
        return _job_snapshot(job)


@app.post(
    "/commands/library-analysis-jobs/{job_id}/cancel",
    response_model=AnalysisJobResult,
)
def cmd_cancel_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Request a clean stop at the next durable analysis boundary."""
    job = get_analysis_job(job_id)
    with _analysis_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="analysis job is not active")
        job.cancel_event.set()
        job.result.status = "cancelling"
        job.result.detail = "Saving progress and stopping"
        _append_job_log_locked(job, "Cancellation requested; saving progress.")
        return _job_snapshot(job)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API with uvicorn (entry point for the ``spotify-api`` script)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
