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
from collections.abc import AsyncIterator as AsyncIterator
from collections.abc import Callable as Callable
from collections.abc import Iterator as Iterator
from contextlib import asynccontextmanager as asynccontextmanager
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from functools import lru_cache as lru_cache
from pathlib import Path as Path
from threading import Event as Event
from threading import Lock as Lock
from threading import Thread as Thread
from typing import Annotated as Annotated
from typing import Any as Any
from typing import Literal as Literal
from uuid import uuid4 as uuid4

from fastapi import Depends as Depends
from fastapi import FastAPI as FastAPI
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi import Request as Request
from fastapi.responses import JSONResponse as JSONResponse
from fastapi.responses import Response as Response
from requests.exceptions import RequestException as RequestException
from spotipy import Spotify as Spotify
from spotipy.exceptions import SpotifyException as SpotifyException

from spotify_manager.application.job_lifecycle import (
    ACTIVE_STATUSES as _ACTIVE_JOB_STATUSES,
)
from spotify_manager.application.job_lifecycle import JobIdentity as JobIdentity
from spotify_manager.application.job_lifecycle import append_log as append_log
from spotify_manager.application.job_lifecycle import (
    first_active_job as first_active_job,
)
from spotify_manager.application.job_lifecycle import retain_logs as retain_logs
from spotify_manager.bootstrap.startup import (
    hydrate_library_data as hydrate_runtime_library_data,
)
from spotify_manager.client import get_spotipy_client as get_spotipy_client
from spotify_manager.client.lastfm import LastFmClient as LastFmClient
from spotify_manager.client.lastfm import LastFmError as LastFmError
from spotify_manager.core.library_data import LibraryDataError as LibraryDataError
from spotify_manager.core.library_data.runtime import (
    get_library_data_service as get_library_data_service,
)
from spotify_manager.core.state.editor import state_editor_schema as state_editor_schema
from spotify_manager.core.state.editor import (
    validate_namespace_editor_change as validate_namespace_editor_change,
)
from spotify_manager.core.state.models import (
    StateConfigurationError as StateConfigurationError,
)
from spotify_manager.core.state.models import StateConflictError as StateConflictError
from spotify_manager.core.state.models import StateDocumentError as StateDocumentError
from spotify_manager.core.state.models import StateError as StateError
from spotify_manager.core.state.models import canonical_json as canonical_json
from spotify_manager.core.state.models import namespace_value as namespace_value
from spotify_manager.core.state.runtime import get_state_service as get_state_service
from spotify_manager.core.state.service import StateFactory as StateFactory
from spotify_manager.core.state.service import StateValidator as StateValidator
from spotify_manager.interfaces.http.analysis_worker import (
    AnalysisWorker as AnalysisWorker,
)
from spotify_manager.interfaces.http.analysis_worker import (
    spotify_event_setter as spotify_event_setter,
)
from spotify_manager.interfaces.http.handlers.analysis import (
    AnalysisHandlers as AnalysisHandlers,
)
from spotify_manager.interfaces.http.handlers.daily_mind_radio import (
    DailyMindRadioHandlers as DailyMindRadioHandlers,
)
from spotify_manager.interfaces.http.handlers.discography import (
    DiscographyHandlers as DiscographyHandlers,
)
from spotify_manager.interfaces.http.handlers.discovery import (
    DiscoveryHandlers as DiscoveryHandlers,
)
from spotify_manager.interfaces.http.handlers.dormant import (
    DormantHandlers as DormantHandlers,
)
from spotify_manager.interfaces.http.handlers.found_art import (
    FoundArtHandlers as FoundArtHandlers,
)
from spotify_manager.interfaces.http.handlers.health import (
    HealthHandlers as HealthHandlers,
)
from spotify_manager.interfaces.http.handlers.historical import (
    HistoricalHandlers as HistoricalHandlers,
)
from spotify_manager.interfaces.http.handlers.history import (
    HistoryHandlers as HistoryHandlers,
)
from spotify_manager.interfaces.http.handlers.library_commands import (
    LibraryCommandsHandlers as LibraryCommandsHandlers,
)
from spotify_manager.interfaces.http.handlers.lookups import (
    LookupsHandlers as LookupsHandlers,
)
from spotify_manager.interfaces.http.handlers.new_year import (
    NewYearHandlers as NewYearHandlers,
)
from spotify_manager.interfaces.http.handlers.palace import (
    PalaceHandlers as PalaceHandlers,
)
from spotify_manager.interfaces.http.handlers.queue_2 import (
    Queue2Handlers as Queue2Handlers,
)
from spotify_manager.interfaces.http.handlers.queue_3 import (
    Queue3Handlers as Queue3Handlers,
)
from spotify_manager.interfaces.http.handlers.queue_fill import (
    QueueFillHandlers as QueueFillHandlers,
)
from spotify_manager.interfaces.http.handlers.queue_flush import (
    QueueFlushHandlers as QueueFlushHandlers,
)
from spotify_manager.interfaces.http.handlers.releases import (
    ReleasesHandlers as ReleasesHandlers,
)
from spotify_manager.interfaces.http.handlers.requeue import (
    RequeueHandlers as RequeueHandlers,
)
from spotify_manager.interfaces.http.handlers.sauvignon import (
    SauvignonHandlers as SauvignonHandlers,
)
from spotify_manager.interfaces.http.handlers.slow_listening import (
    SlowListeningHandlers as SlowListeningHandlers,
)
from spotify_manager.interfaces.http.handlers.something_old import (
    SomethingOldHandlers as SomethingOldHandlers,
)
from spotify_manager.interfaces.http.handlers.state import (
    StateHandlers as StateHandlers,
)
from spotify_manager.interfaces.http.handlers.wine import WineHandlers as WineHandlers
from spotify_manager.interfaces.http.job_queries import (
    active_analysis_snapshots as active_analysis_snapshots,
)
from spotify_manager.interfaces.http.job_queries import (
    active_playlist_snapshots as active_playlist_snapshots,
)
from spotify_manager.interfaces.http.job_records import AnalysisJob as _AnalysisJob
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.job_registry import lookup_job as lookup_job
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisJobLog as AnalysisJobLog,
)
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisJobResult as AnalysisJobResult,
)
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisResourceProgress as AnalysisResourceProgress,
)
from spotify_manager.interfaces.http.models.common import CommandResult as CommandResult
from spotify_manager.interfaces.http.models.common import CountResult as CountResult
from spotify_manager.interfaces.http.models.common import JobStatus as JobStatus
from spotify_manager.interfaces.http.models.common import (
    LibraryMirrorFilesStatus as LibraryMirrorFilesStatus,
)
from spotify_manager.interfaces.http.models.common import (
    ServerFileStatus as ServerFileStatus,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyArtistResult as DiscographyArtistResult,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyChoiceRequest as DiscographyChoiceRequest,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyPendingChoice as DiscographyPendingChoice,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyReleaseOption as DiscographyReleaseOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsChoiceRequest as NewKidsChoiceRequest,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsFillResult as NewKidsFillResult,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsPendingChoice as NewKidsPendingChoice,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsReleaseOption as NewKidsReleaseOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsTrackResult as NewKidsTrackResult,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3AnnualImportEntry as Queue3AnnualImportEntry,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ChoiceRequest as Queue3ChoiceRequest,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ComposerPlaylistOption as Queue3ComposerPlaylistOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3PendingChoice as Queue3PendingChoice,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ReleaseOption as Queue3ReleaseOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3TrackResult as Queue3TrackResult,
)
from spotify_manager.interfaces.http.models.historical import (
    BlastSelectionResult as BlastSelectionResult,
)
from spotify_manager.interfaces.http.models.historical import (
    DormantArtistResultEntry as DormantArtistResultEntry,
)
from spotify_manager.interfaces.http.models.jobs import BlastJobResult as BlastJobResult
from spotify_manager.interfaces.http.models.palace import (
    PalaceAlbumRefreshResult as PalaceAlbumRefreshResult,
)
from spotify_manager.interfaces.http.models.palace import (
    PalaceAlbumSelectionResult as PalaceAlbumSelectionResult,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueArtistOption as QueueArtistOption,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueChoiceRequest as QueueChoiceRequest,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueFillResultEntry as QueueFillResultEntry,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueFlushResultEntry as QueueFlushResultEntry,
)
from spotify_manager.interfaces.http.models.queue import (
    QueuePendingChoice as QueuePendingChoice,
)
from spotify_manager.interfaces.http.models.recommendations import (
    FoundArtSelectionResult as FoundArtSelectionResult,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonAlbumOption as SauvignonAlbumOption,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonChoiceRequest as SauvignonChoiceRequest,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonPendingChoice as SauvignonPendingChoice,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonSelectionResult as SauvignonSelectionResult,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckArtistOption as ReleaseCheckArtistOption,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckChoiceRequest as ReleaseCheckChoiceRequest,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckPendingChoice as ReleaseCheckPendingChoice,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckResultEntry as ReleaseCheckResultEntry,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckStateRestoreRequest as ReleaseCheckStateRestoreRequest,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckStateSnapshot as ReleaseCheckStateSnapshot,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningChoiceRequest as SlowListeningChoiceRequest,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice as SlowListeningPendingChoice,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningReleaseOption as SlowListeningReleaseOption,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningTrackResult as SlowListeningTrackResult,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldArtistOption as SomethingOldArtistOption,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldChoiceRequest as SomethingOldChoiceRequest,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPendingChoice as SomethingOldPendingChoice,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldRankingEntry as SomethingOldRankingEntry,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldReleaseOption as SomethingOldReleaseOption,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldTrackResult as SomethingOldTrackResult,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateNamespaceReplaceRequest as SharedStateNamespaceReplaceRequest,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateReplaceRequest as SharedStateReplaceRequest,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateSnapshot as SharedStateSnapshot,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateSummary as SharedStateSummary,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineCellarTrackResult as NewWineCellarTrackResult,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineChoiceRequest as NewWineChoiceRequest,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWinePendingChoice as NewWinePendingChoice,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineRefillResult as NewWineRefillResult,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineReleaseOption as NewWineReleaseOption,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineTrackResult as NewWineTrackResult,
)
from spotify_manager.interfaces.http.playlist_retry import (
    PlaylistRetry as PlaylistRetry,
)
from spotify_manager.interfaces.http.presenters.discography import (
    discography_artist_result as _discography_artist_result,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    new_kids_fill_result as _new_kids_fill_result,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    new_kids_track_result as _new_kids_track_result,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    queue_3_annual_entries as _queue_3_annual_entries,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    queue_3_release_option as _queue_3_release_option,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    queue_3_track_result as _queue_3_track_result,
)
from spotify_manager.interfaces.http.presenters.historical import (
    blast_selection_result as _blast_selection_result,
)
from spotify_manager.interfaces.http.presenters.queue import (
    queue_fill_result_entry as _queue_fill_result_entry,
)
from spotify_manager.interfaces.http.presenters.queue import (
    queue_flush_result_entry as _queue_flush_result_entry,
)
from spotify_manager.interfaces.http.presenters.recommendations import (
    found_art_selection_result as _found_art_selection_result,
)
from spotify_manager.interfaces.http.presenters.recommendations import (
    sauvignon_selection_result as _sauvignon_selection_result,
)
from spotify_manager.interfaces.http.presenters.releases import (
    release_check_result as _release_check_result,
)
from spotify_manager.interfaces.http.presenters.slow_listening import (
    slow_listening_track_result as _slow_listening_track_result,
)
from spotify_manager.interfaces.http.presenters.something_old import (
    something_old_track_result as _something_old_track_result,
)
from spotify_manager.interfaces.http.presenters.wine import (
    new_wine_refill_result as _new_wine_refill_result,
)
from spotify_manager.interfaces.http.presenters.wine import (
    new_wine_track_result as _new_wine_track_result,
)
from spotify_manager.interfaces.http.routers.analysis import router as _analysis_router
from spotify_manager.interfaces.http.routers.daily_mind_radio import (
    router as _daily_mind_radio_router,
)
from spotify_manager.interfaces.http.routers.discography import (
    router as _discography_router,
)
from spotify_manager.interfaces.http.routers.discovery import (
    router as _discovery_router,
)
from spotify_manager.interfaces.http.routers.dormant import router as _dormant_router
from spotify_manager.interfaces.http.routers.found_art import (
    router as _found_art_router,
)
from spotify_manager.interfaces.http.routers.health import router as _health_router
from spotify_manager.interfaces.http.routers.historical import (
    router as _historical_router,
)
from spotify_manager.interfaces.http.routers.history import router as _history_router
from spotify_manager.interfaces.http.routers.library_commands import (
    router as _library_commands_router,
)
from spotify_manager.interfaces.http.routers.lookups import router as _lookups_router
from spotify_manager.interfaces.http.routers.new_year import router as _new_year_router
from spotify_manager.interfaces.http.routers.palace import router as _palace_router
from spotify_manager.interfaces.http.routers.queue_2 import router as _queue_2_router
from spotify_manager.interfaces.http.routers.queue_3 import router as _queue_3_router
from spotify_manager.interfaces.http.routers.queue_fill import (
    router as _queue_fill_router,
)
from spotify_manager.interfaces.http.routers.queue_flush import (
    router as _queue_flush_router,
)
from spotify_manager.interfaces.http.routers.releases import router as _releases_router
from spotify_manager.interfaces.http.routers.requeue import router as _requeue_router
from spotify_manager.interfaces.http.routers.sauvignon import (
    router as _sauvignon_router,
)
from spotify_manager.interfaces.http.routers.slow_listening import (
    router as _slow_listening_router,
)
from spotify_manager.interfaces.http.routers.something_old import (
    router as _something_old_router,
)
from spotify_manager.interfaces.http.routers.state import router as _state_router
from spotify_manager.interfaces.http.routers.wine import router as _wine_router
from spotify_manager.interfaces.http.workers.blast import BlastWorker as BlastWorker
from spotify_manager.interfaces.http.workers.blast_artist import (
    BlastArtistWorker as BlastArtistWorker,
)
from spotify_manager.interfaces.http.workers.daily_mind_radio import (
    DailyMindRadioWorker as DailyMindRadioWorker,
)
from spotify_manager.interfaces.http.workers.discography import (
    DiscographyWorker as DiscographyWorker,
)
from spotify_manager.interfaces.http.workers.errors import (
    _DiscographyJobCancelledError as _DiscographyJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _NewKidsJobCancelledError as _NewKidsJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _NewWineJobCancelledError as _NewWineJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _PalaceOfMemoryJobCancelledError as _PalaceOfMemoryJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _Queue3JobCancelledError as _Queue3JobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _QueueJobCancelledError as _QueueJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _ReleaseCheckJobCancelledError as _ReleaseCheckJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _RequeueForADreamJobCancelledError as _RequeueForADreamJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SauvignonJobCancelledError as _SauvignonJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SlowListeningJobCancelledError as _SlowListeningJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SomethingOldJobCancelledError as _SomethingOldJobCancelledError,
)
from spotify_manager.interfaces.http.workers.found_art import (
    FoundArtWorker as FoundArtWorker,
)
from spotify_manager.interfaces.http.workers.new_kids import (
    NewKidsWorker as NewKidsWorker,
)
from spotify_manager.interfaces.http.workers.new_wine import (
    NewWineWorker as NewWineWorker,
)
from spotify_manager.interfaces.http.workers.new_year import (
    NewYearWorker as NewYearWorker,
)
from spotify_manager.interfaces.http.workers.palace_of_memory import (
    PalaceOfMemoryWorker as PalaceOfMemoryWorker,
)
from spotify_manager.interfaces.http.workers.queue_3 import Queue3Worker as Queue3Worker
from spotify_manager.interfaces.http.workers.queue_fill import (
    QueueFillWorker as QueueFillWorker,
)
from spotify_manager.interfaces.http.workers.queue_flush import (
    QueueFlushWorker as QueueFlushWorker,
)
from spotify_manager.interfaces.http.workers.release_check import (
    ReleaseCheckWorker as ReleaseCheckWorker,
)
from spotify_manager.interfaces.http.workers.requeue_for_a_dream import (
    RequeueForADreamWorker as RequeueForADreamWorker,
)
from spotify_manager.interfaces.http.workers.sauvignon import (
    SauvignonWorker as SauvignonWorker,
)
from spotify_manager.interfaces.http.workers.scrobble_history import (
    ScrobbleHistoryWorker as ScrobbleHistoryWorker,
)
from spotify_manager.interfaces.http.workers.slow_listening import (
    SlowListeningWorker as SlowListeningWorker,
)
from spotify_manager.interfaces.http.workers.something_old import (
    SomethingOldWorker as SomethingOldWorker,
)
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)
from spotify_manager.models.lookups import AlbumEvaluation as AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats as ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus as TrackScrobbleStatus
from spotify_manager.models.your_library import YourLibraryFile as YourLibraryFile
from spotify_manager.processors.library_lookups import (
    AlbumNotFoundError as AlbumNotFoundError,
)
from spotify_manager.processors.library_lookups import (
    AmbiguousAlbumError as AmbiguousAlbumError,
)
from spotify_manager.processors.library_lookups import (
    AmbiguousArtistError as AmbiguousArtistError,
)
from spotify_manager.processors.library_lookups import (
    ArtistNotFoundError as ArtistNotFoundError,
)
from spotify_manager.processors.library_lookups import (
    SpotifyLookupResponseError as SpotifyLookupResponseError,
)
from spotify_manager.processors.library_lookups import (
    evaluate_album_live as evaluate_album_live,
)
from spotify_manager.processors.library_lookups import (
    get_live_artist_library_stats as get_live_artist_library_stats,
)
from spotify_manager.processors.library_lookups import (
    parse_spotify_lookup_reference as parse_spotify_lookup_reference,
)
from spotify_manager.processors.scrobble_lookups import (
    AmbiguousTrackError as AmbiguousTrackError,
)
from spotify_manager.processors.scrobble_lookups import (
    TrackNotFoundError as TrackNotFoundError,
)
from spotify_manager.processors.scrobble_lookups import (
    get_track_scrobble_status as get_track_scrobble_status,
)
from spotify_manager.processors.total_albums_processor import (
    update_total_album_list as update_total_album_list,
)
from spotify_manager.routines import analyse_library as library_analysis
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines import blast_from_past_artists as blast_from_past_artists
from spotify_manager.routines import composer_playlists as composer_playlists
from spotify_manager.routines import daily_mind_radio as daily_mind_radio
from spotify_manager.routines import discography as discography
from spotify_manager.routines import found_art as found_art
from spotify_manager.routines import genre_reveal as genre_reveal
from spotify_manager.routines import new_kids as new_kids
from spotify_manager.routines import new_wine as new_wine
from spotify_manager.routines import new_year as new_year
from spotify_manager.routines import palace_of_memory as palace_of_memory
from spotify_manager.routines import queue_3 as queue_3
from spotify_manager.routines import recover_removed_albums as recover_removed_albums
from spotify_manager.routines import release_check as release_check
from spotify_manager.routines import requeue_for_a_dream as requeue_for_a_dream
from spotify_manager.routines import review_album_limits as review_album_limits
from spotify_manager.routines import review_artists as review_artists
from spotify_manager.routines import sauvignon as sauvignon
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines import slow_listening as slow_listening
from spotify_manager.routines import something_old as something_old
from spotify_manager.routines import the_queue as the_queue
from spotify_manager.routines.convert_library_file import (
    analyse_comparison as analyse_comparison,
)
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums as compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import (
    convert_your_library_file as convert_your_library_file,
)
from spotify_manager.routines.convert_library_file import (
    restore_your_library_from_file as restore_your_library_from_file,
)
from spotify_manager.routines.count_items import (
    count_artists_in_library as count_artists_in_library,
)
from spotify_manager.routines.monthly_routine import (
    run_monthly_routines as run_monthly_routines,
)
from spotify_manager.settings import Settings as Settings


STATE_NAMESPACE_DEFINITIONS: dict[str, tuple[StateFactory, StateValidator]] = {
    "discography": (discography._default_state, discography.validate_state),
    "genre_reveal": (genre_reveal._default_state, genre_reveal.validate_state),
    "new_kids": (new_kids._default_state, new_kids.validate_state),
    "new_wine": (new_wine._default_state, new_wine.validate_state),
    "new_year": (lambda: {"years": {}}, new_year.validate_state),
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
_analysis_jobs: dict[str, _AnalysisJob] = {}
_analysis_jobs_lock = Lock()
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
        "RELEASE_CHECK_STATE_BACKUP_DIR", release_check.DEFAULT_STATE_BACKUP_DIR
    )
)
SPOTIFY_CONNECTION_FAILURE_DETAIL = (
    "Spotify connection remained unavailable after "
    "automatic retries. Please try again shortly."
)
DEFAULT_SPOTIFY_RATE_LIMIT_RETRY_SECONDS = 60


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
    job.next_log_sequence = append_log(
        job.result.logs, job.next_log_sequence, message, _create_job_log
    )
    retain_logs(job.result.logs, _MAX_ANALYSIS_LOGS)


def _blast_job_snapshot(job: _BlastJob) -> BlastJobResult:
    """Return an isolated response model for one mutable playlist job."""
    return job.result.model_copy(deep=True)


def _append_blast_log_locked(job: _BlastJob, message: str) -> None:
    """Append one bounded playlist-job log entry while holding its lock."""
    if not message:
        return
    job.next_log_sequence = append_log(
        job.result.logs, job.next_log_sequence, message, _create_job_log
    )
    retain_logs(job.result.logs, _MAX_BLAST_LOGS)


def _create_job_log(sequence: int, message: str) -> AnalysisJobLog:
    return AnalysisJobLog(
        sequence=sequence, timestamp=datetime.now(UTC).isoformat(), message=message
    )


def _analysis_job_identities() -> Iterator[JobIdentity]:
    for job in _analysis_jobs.values():
        yield job.result


def _playlist_job_identities() -> Iterator[JobIdentity]:
    for job in _blast_jobs.values():
        yield job.result


def _require_analysis_slot(command: str) -> None:
    """Keep the original command-scoped conflict while the registry is locked.

    Args:
        command: Original analysis command requesting reservation.

    Raises:
        HTTPException: A matching active analysis retains its original 409 detail.
    """
    existing = first_active_job(_analysis_job_identities(), command)
    if existing is None:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "message": "an analysis of this type is already running",
            "job_id": existing.job_id,
        },
    )


def _require_playlist_slot(message: str) -> None:
    """Keep the original shared playlist/history conflict under its registry lock.

    Args:
        message: Original feature-specific conflict text.

    Raises:
        HTTPException: An active playlist/history job retains its original detail.
    """
    existing = first_active_job(_playlist_job_identities())
    if existing is None:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "message": message,
            "job_id": existing.job_id,
            "command": existing.command,
        },
    )


def _release_check_state_snapshot(
    known_fingerprint: str | None = None, *, backup_path: Path | None = None
) -> ReleaseCheckStateSnapshot:
    """Load one state snapshot, omitting its body when the browser is current."""
    state = (
        get_state_service()
        .namespace(
            "release_check", release_check._default_state, release_check.validate_state
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


def _release_state_is_newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    """Return whether a browser-held state is semantically newer."""
    candidate_at = _state_timestamp(release_check.state_updated_at(candidate))
    current_at = _state_timestamp(release_check.state_updated_at(current))
    return candidate_at is not None and (
        current_at is None or candidate_at > current_at
    )


def get_analysis_job(job_id: str) -> _AnalysisJob:
    """Return one job or raise a conventional API 404."""
    return lookup_job(
        _analysis_jobs, _analysis_jobs_lock, job_id, "analysis job not found"
    )


def get_blast_job(job_id: str, command: str | None = None) -> _BlastJob:
    """Return one playlist job or raise a conventional API 404."""
    return lookup_job(
        _blast_jobs, _blast_jobs_lock, job_id, "playlist job not found", command
    )


def _cancel_simple_playlist_job(
    job_id: str, *, command: str, detail: str
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
    worker = _analysis_worker(job_id, mode, spotify, full_rebuild, mirror_resource)
    worker.start()
    setter = spotify_event_setter(spotify)
    previous_callback = None
    if setter is not None:
        previous_callback = setter(worker.echo)
    try:
        summary = worker.execute()
    except library_analysis.LibraryAnalysisCancelledError as exc:
        worker.cancelled(exc)
    except library_analysis.SpotifyRateLimitError as exc:
        worker.paused(exc)
    except library_analysis.LibrarySyncError as exc:
        worker.failed(exc)
    except Exception as exc:
        _analysis_logger.exception("Unexpected library analysis error")
        worker.unexpected_failure(exc)
    else:
        worker.completed(summary)
    finally:
        if setter is not None:
            setter(previous_callback)
        worker.finish()


def _analysis_worker(
    job_id: str,
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None,
    full_rebuild: bool,
    mirror_resource: library_analysis.ResourceName | None,
) -> AnalysisWorker:
    return AnalysisWorker(
        job=get_analysis_job(job_id),
        lock=_analysis_jobs_lock,
        now=_job_time,
        append=_append_job_log_locked,
        mode=mode,
        spotify=spotify,
        full_rebuild=full_rebuild,
        mirror_resource=mirror_resource,
    )


def _job_time() -> datetime:
    return datetime.now(UTC)


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
        else ("albums", "tracks")
        if mode == "mirrors"
        else ("albums", "tracks", "artists")
    )
    with _analysis_jobs_lock:
        _require_analysis_slot(command)
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


def _playlist_job_retry(
    job: _BlastJob, echo: Callable[[str], None]
) -> blast_from_past.RetryCall:
    """Build a bounded Spotify retry policy with interruptible waits."""
    return PlaylistRetry(job, echo).call


def _run_blast_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
    dry_run: bool,
) -> None:
    """Execute one web playlist job and retain progress, logs, and results."""
    BlastWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        count=count,
        max_playlist_length=max_playlist_length,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _blast_selection_result=_blast_selection_result,
        _playlist_job_retry=_playlist_job_retry,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_blast_artist_job(
    job_id: str, spotify: Spotify, playlist_id: str, count: int, dry_run: bool
) -> None:
    """Execute one alphabetic dormant-artist playlist update."""
    BlastArtistWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        count=count,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _playlist_job_retry=_playlist_job_retry,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_daily_mind_radio_job(
    job_id: str, spotify: Spotify, playlist_id: str, dry_run: bool
) -> None:
    """Execute one Daily Mind Radio web job and retain its complete trace."""
    DailyMindRadioWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _blast_selection_result=_blast_selection_result,
        _playlist_job_retry=_playlist_job_retry,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_found_art_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int,
) -> None:
    """Execute one Found Art web job and retain its complete trace."""
    FoundArtWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        api_key=api_key,
        username=username,
        count=count,
        create_lastfm=LastFmClient,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _found_art_selection_result=_found_art_selection_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


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
    SauvignonWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        api_key=api_key,
        username=username,
        count=count,
        max_playlist_length=max_playlist_length,
        seed_count=seed_count,
        dry_run=dry_run,
        create_lastfm=LastFmClient,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _sauvignon_selection_result=_sauvignon_selection_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


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
    QueueFillWorker(
        job_id=job_id,
        spotify=spotify,
        playlists=playlists,
        api_key=api_key,
        username=username,
        count=count,
        max_playlist_length=max_playlist_length,
        seed_count=seed_count,
        dry_run=dry_run,
        create_lastfm=LastFmClient,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _queue_fill_result_entry=_queue_fill_result_entry,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_queue_flush_job(
    job_id: str, spotify: Spotify, playlists: the_queue.QueuePlaylists, dry_run: bool
) -> None:
    """Run the first-ten-artist Queue flush as a reconnectable web job."""
    QueueFlushWorker(
        job_id=job_id,
        spotify=spotify,
        playlists=playlists,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _queue_flush_result_entry=_queue_flush_result_entry,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


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
    NewKidsWorker(
        job_id=job_id,
        spotify=spotify,
        new_kids_playlist_id=new_kids_playlist_id,
        queue_2_playlist_id=queue_2_playlist_id,
        great_discoveries_playlist_id=great_discoveries_playlist_id,
        unlucky_ones_playlist_id=unlucky_ones_playlist_id,
        newfoundland_playlist_id=newfoundland_playlist_id,
        dry_run=dry_run,
        command=command,
        rate_limit_delay=DEFAULT_SPOTIFY_RATE_LIMIT_RETRY_SECONDS,
        create_lastfm=LastFmClient,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        configuration=Settings,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _new_kids_fill_result=_new_kids_fill_result,
        _new_kids_track_result=_new_kids_track_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _apply_queue_3_annual_summary(
    job: _BlastJob, summary: queue_3.AnnualImportSummary
) -> None:
    """Apply a completed annual-only summary to its web job."""
    job.result.status = "completed"
    job.result.processed = len(summary.results)
    job.result.total = len(summary.results)
    job.result.added = summary.additions
    job.result.queue_3_annual_import = _queue_3_annual_entries(summary.results)
    job.result.queue_3_annual_import_completed = summary.already_completed
    if summary.already_completed:
        job.result.detail = (
            f"Great Discoveries {summary.source_year} was already imported."
        )
    else:
        action = "would be added" if summary.dry_run else "added"
        artist_label = "artist" if summary.additions == 1 else "artists"
        job.result.detail = (
            "Great Discoveries "
            f"{summary.source_year}"
            ": "
            f"{summary.additions}"
            " "
            f"{artist_label}"
            " "
            f"{action}"
            "; "
            f"{summary.already_present}"
            " already present."
        )


def _apply_queue_3_flush_summary(job: _BlastJob, summary: queue_3.FlushSummary) -> None:
    """Apply a completed or paused flush summary to its web job."""
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
    job.result.queue_3_annual_import = _queue_3_annual_entries(summary.annual_import)
    job.result.queue_3_resumed = summary.resumed
    job.result.queue_3_paused = summary.paused
    if summary.paused:
        job.result.detail = "Queue 3 flush paused. Progress was saved."
    else:
        job.result.detail = (
            f"{summary.processed}"
            " decisions; "
            f"{summary.advanced}"
            " advances; "
            f"{summary.changed_releases}"
            " release changes; "
            f"{summary.completed_artists}"
            " completed artists."
        )


def _run_queue_3_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
    annual_only: bool = False,
) -> None:
    """Execute one Queue 3 operation as a reconnectable web job."""
    Queue3Worker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        annual_only=annual_only,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        _apply_queue_3_annual_summary=_apply_queue_3_annual_summary,
        _apply_queue_3_flush_summary=_apply_queue_3_flush_summary,
        lock=_blast_jobs_lock,
        _queue_3_release_option=_queue_3_release_option,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_new_wine_job(
    job_id: str,
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    dry_run: bool,
    no_discovery: bool,
    choose_album_endpoints: bool = False,
) -> None:
    """Execute one interactive New Wine flush as a reconnectable web job."""
    NewWineWorker(
        job_id=job_id,
        spotify=spotify,
        new_wine_playlist_id=new_wine_playlist_id,
        sauvignon_playlist_id=sauvignon_playlist_id,
        wine_cellar_playlist_id=wine_cellar_playlist_id,
        dry_run=dry_run,
        no_discovery=no_discovery,
        choose_album_endpoints=choose_album_endpoints,
        rate_limit_delay=DEFAULT_SPOTIFY_RATE_LIMIT_RETRY_SECONDS,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _new_wine_refill_result=_new_wine_refill_result,
        _new_wine_track_result=_new_wine_track_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_slow_listening_job(
    job_id: str, spotify: Spotify, playlist_id: str, dry_run: bool
) -> None:
    """Execute an interactive Slow Listening flush as a reconnectable job."""
    SlowListeningWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _slow_listening_track_result=_slow_listening_track_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _something_old_date(timestamp_ms: int) -> str:
    """Format one scrobble timestamp in the listening timezone."""
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, blast_from_past.SCROBBLE_TIMEZONE)
        .date()
        .isoformat()
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
    SomethingOldWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        api_key=api_key,
        username=username,
        dry_run=dry_run,
        create_lastfm=LastFmClient,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _something_old_date=_something_old_date,
        _something_old_track_result=_something_old_track_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_release_check_job(
    job_id: str,
    spotify: Spotify,
    playlists: release_check.ReleaseCheckPlaylists,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Execute one reconnectable, interactive new-release check."""
    ReleaseCheckWorker(
        RELEASE_CHECK_STATE_PATH=RELEASE_CHECK_STATE_PATH,
        job_id=job_id,
        spotify=spotify,
        playlists=playlists,
        api_key=api_key,
        username=username,
        dry_run=dry_run,
        create_lastfm=LastFmClient,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _release_check_result=_release_check_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_discography_job(
    job_id: str,
    spotify: Spotify,
    playlist_ids: dict[discography.QueueName, str],
    queue_3_playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute one reload-safe interactive discography planning job."""
    DiscographyWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_ids=playlist_ids,
        queue_3_playlist_id=queue_3_playlist_id,
        dry_run=dry_run,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _discography_artist_result=_discography_artist_result,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_requeue_for_a_dream_job(
    job_id: str, spotify: Spotify, playlist_id: str, dry_run: bool
) -> None:
    """Execute one reconnectable Requeue for a Dream transition."""
    RequeueForADreamWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_palace_of_memory_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str | None,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> None:
    """Execute one reconnectable Palace fill or cursor adjustment."""
    PalaceOfMemoryWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        alphabetical_start=alphabetical_start,
        cursor_position=cursor_position,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def _run_scrobble_history_job(
    job_id: str, api_key: str, username: str, dry_run: bool, full_rebuild: bool = False
) -> None:
    """Refresh the shared Last.fm record as a reconnectable web job."""
    ScrobbleHistoryWorker(
        job_id=job_id,
        api_key=api_key,
        username=username,
        dry_run=dry_run,
        full_rebuild=full_rebuild,
        create_lastfm=LastFmClient,
        logger=_analysis_logger,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def start_blast_job(
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
    dry_run: bool,
) -> BlastJobResult:
    """Start one playlist job, rejecting another active invocation."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(result=BlastJobResult(job_id=job_id, dry_run=dry_run))
        _append_blast_log_locked(
            job,
            "A blast from the past queued" + (" in dry-run mode." if dry_run else "."),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)
    Thread(
        target=_run_blast_job,
        args=(job_id, spotify, playlist_id, count, max_playlist_length, dry_run),
        name=f"blast-from-the-past-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_blast_artist_job(
    spotify: Spotify, playlist_id: str, count: int, dry_run: bool
) -> BlastJobResult:
    """Start one dormant-artist recovery job."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="blast_from_the_past_artists",
                requested_count=count,
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            "Dormant-artist recovery queued"
            + (" in dry-run mode." if dry_run else "."),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)
    Thread(
        target=_run_blast_artist_job,
        args=(job_id, spotify, playlist_id, count, dry_run),
        name=f"blast-from-the-past-artists-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_daily_mind_radio_job(
    spotify: Spotify, playlist_id: str, dry_run: bool
) -> BlastJobResult:
    """Start one Daily Mind Radio job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="daily_mind_radio", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job, "Daily Mind Radio queued" + (" in dry-run mode." if dry_run else ".")
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)
    Thread(
        target=_run_daily_mind_radio_job,
        args=(job_id, spotify, playlist_id, dry_run),
        name=f"daily-mind-radio-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_found_art_job(
    spotify: Spotify, playlist_id: str, api_key: str, username: str, count: int
) -> BlastJobResult:
    """Start one Found Art job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="found_art", requested_count=count
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
        _require_playlist_slot("another playlist routine is already running")
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
            (
                "Sauvignon album discovery queued"
                f"{(' in dry-run mode' if dry_run else '')}"
                "."
            ),
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
        _require_playlist_slot("another playlist routine is already running")
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
            f"Queue artist discovery queued{(' in dry-run mode' if dry_run else '')}.",
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
    spotify: Spotify, playlists: the_queue.QueuePlaylists, *, dry_run: bool
) -> BlastJobResult:
    """Start a Queue flush job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(job_id=job_id, command="flush_queue", dry_run=dry_run)
        )
        _append_blast_log_locked(
            job, f"Queue flush queued{(' in dry-run mode' if dry_run else '')}."
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
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_new_kids", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job, f"New Kids flush queued{(' in dry-run mode' if dry_run else '')}."
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
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_queue_2", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job, f"Queue 2 flush queued{(' in dry-run mode' if dry_run else '')}."
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
    spotify: Spotify, playlist_id: str, *, dry_run: bool, annual_only: bool = False
) -> BlastJobResult:
    """Start one Queue 3 flush or standalone annual-import web job."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_queue_3",
                dry_run=dry_run,
                queue_3_annual_only=annual_only,
            )
        )
        _append_blast_log_locked(
            job,
            ("Previous-year Queue 3 import" if annual_only else "Queue 3 flush")
            + f" queued{(' in dry-run mode' if dry_run else '')}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)
    Thread(
        target=_run_queue_3_job,
        args=(job_id, spotify, playlist_id, dry_run, annual_only),
        name=f"queue-3-{('import' if annual_only else 'flush')}-{job_id[:8]}",
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
    choose_album_endpoints: bool = False,
) -> BlastJobResult:
    """Start one New Wine web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_new_wine",
                dry_run=dry_run,
                no_discovery=no_discovery,
                choose_album_endpoints=choose_album_endpoints,
            )
        )
        _append_blast_log_locked(
            job, f"New Wine flush queued{(' in dry-run mode' if dry_run else '')}."
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
            choose_album_endpoints,
        ),
        name=f"new-wine-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_slow_listening_job(
    spotify: Spotify, playlist_id: str, *, dry_run: bool
) -> BlastJobResult:
    """Start one Slow Listening web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_slow_listening", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Slow Listening flush queued in dry-run mode."
            if dry_run
            else "Slow Listening flush queued.",
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
    spotify: Spotify, playlist_id: str, api_key: str, username: str, *, dry_run: bool
) -> BlastJobResult:
    """Start one interactive Something Old job with reload-safe state."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="something_old", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Something Old queued in dry-run mode."
            if dry_run
            else "Something Old queued.",
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
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="check_new_releases", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "New-release check queued in dry-run mode."
            if dry_run
            else "New-release check queued.",
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
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="plan_discographies", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Discography planning queued in dry-run mode."
            if dry_run
            else "Discography planning queued.",
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
    spotify: Spotify, playlist_id: str, *, dry_run: bool
) -> BlastJobResult:
    """Start one Requeue for a Dream job with reload-safe state."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_requeue_for_a_dream", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Requeue for a Dream queued in dry-run mode."
            if dry_run
            else "Requeue for a Dream queued.",
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
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        cursor_only = cursor_position is not None
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_palace_of_memory",
                dry_run=dry_run,
                palace_cursor_only=cursor_only,
                palace_alphabetical_reference=str(cursor_position)
                if cursor_only
                else alphabetical_start,
            )
        )
        queued_message = (
            f"Palace alphabetical cursor adjustment to {cursor_position} queued."
            if cursor_only
            else "Palace of Memory queued in dry-run mode."
            if dry_run
            else "Palace of Memory queued."
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
    api_key: str, username: str, *, dry_run: bool, full_rebuild: bool = False
) -> BlastJobResult:
    """Start one shared Last.fm history refresh with reload-safe state."""
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist or history routine is running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="update_scrobble_history",
                dry_run=dry_run,
                history_full_rebuild=full_rebuild,
            )
        )
        _append_blast_log_locked(
            job,
            "Last.fm scrobble history update queued in dry-run mode."
            if dry_run
            else "Last.fm scrobble history update queued.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)
    Thread(
        target=_run_scrobble_history_job,
        args=(job_id, api_key, username, dry_run, full_rebuild),
        name=f"scrobble-history-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Hydrate durable data once whenever an API process starts."""
    hydrate_runtime_library_data()
    yield


app = FastAPI(title="Spotify Manager", version="0.1.0", lifespan=_lifespan)


@app.exception_handler(ArtistNotFoundError)
def _artist_not_found(request: Request, exc: ArtistNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousArtistError)
def _ambiguous_artist(request: Request, exc: AmbiguousArtistError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


@app.exception_handler(AlbumNotFoundError)
def _album_not_found(request: Request, exc: AlbumNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousAlbumError)
def _ambiguous_album(request: Request, exc: AmbiguousAlbumError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


@app.exception_handler(TrackNotFoundError)
def _track_not_found(request: Request, exc: TrackNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousTrackError)
def _ambiguous_track(request: Request, exc: AmbiguousTrackError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


@app.exception_handler(SpotifyLookupResponseError)
def _invalid_spotify_lookup(
    request: Request, exc: SpotifyLookupResponseError
) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(SpotifyException)
def _spotify_lookup_failed(request: Request, exc: SpotifyException) -> JSONResponse:
    """Return useful lookup errors instead of an opaque HTTP 500 response."""
    if exc.http_status == 429:
        retry_after = review_album_limits.get_retry_after_seconds(exc)
        detail = (
            "Spotify rate limit reached after trying all "
            "configured credentials. "
            f"{review_album_limits.format_retry_after(retry_after)}"
            "."
        )
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return JSONResponse(
            status_code=429, content={"detail": detail}, headers=headers
        )
    status_code = exc.http_status if exc.http_status in {400, 403, 404} else 502
    return JSONResponse(
        status_code=status_code,
        content={
            ("detail"): (
                "Spotify request failed (HTTP "
                f"{exc.http_status}"
                "): "
                f"{exc.msg or 'unknown Spotify error'}"
            )
        },
    )


def _health_handlers() -> HealthHandlers:
    return HealthHandlers()


def _state_handlers() -> StateHandlers:
    return StateHandlers(
        STATE_NAMESPACE_DEFINITIONS=STATE_NAMESPACE_DEFINITIONS,
        canonical_json=canonical_json,
        datetime=datetime,
        get_state_service=get_state_service,
        namespace_value=namespace_value,
        state_editor_schema=state_editor_schema,
        validate_namespace_editor_change=validate_namespace_editor_change,
    )


def _lookups_handlers() -> LookupsHandlers:
    return LookupsHandlers(
        evaluate_album_live=evaluate_album_live,
        get_library=get_library,
        get_live_artist_library_stats=get_live_artist_library_stats,
        get_track_scrobble_status=get_track_scrobble_status,
        parse_spotify_lookup_reference=parse_spotify_lookup_reference,
    )


def _librarycommands_handlers() -> LibraryCommandsHandlers:
    return LibraryCommandsHandlers(
        analyse_comparison=analyse_comparison,
        compare_your_library_and_all_albums=compare_your_library_and_all_albums,
        convert_your_library_file=convert_your_library_file,
        count_artists_in_library=count_artists_in_library,
        restore_your_library_from_file=restore_your_library_from_file,
        run_monthly_routines=run_monthly_routines,
        update_total_album_list=update_total_album_list,
    )


def _historical_handlers() -> HistoricalHandlers:
    return HistoricalHandlers(
        Settings=Settings,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_simple_playlist_job=_cancel_simple_playlist_job,
        get_blast_job=get_blast_job,
        start_blast_job=start_blast_job,
    )


def _dormant_handlers() -> DormantHandlers:
    return DormantHandlers(
        Settings=Settings,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_simple_playlist_job=_cancel_simple_playlist_job,
        get_blast_job=get_blast_job,
        start_blast_artist_job=start_blast_artist_job,
    )


def _dailymindradio_handlers() -> DailyMindRadioHandlers:
    return DailyMindRadioHandlers(
        Settings=Settings,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_simple_playlist_job=_cancel_simple_playlist_job,
        get_blast_job=get_blast_job,
        start_daily_mind_radio_job=start_daily_mind_radio_job,
    )


def _foundart_handlers() -> FoundArtHandlers:
    return FoundArtHandlers(
        Settings=Settings,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_found_art_job=start_found_art_job,
    )


def _sauvignon_handlers() -> SauvignonHandlers:
    return SauvignonHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_sauvignon_job=start_sauvignon_job,
    )


def _queuefill_handlers() -> QueueFillHandlers:
    return QueueFillHandlers(
        Settings=Settings,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_queue_job=_cancel_queue_job,
        _configured_queue_playlists=_configured_queue_playlists,
        get_blast_job=get_blast_job,
        start_queue_fill_job=start_queue_fill_job,
    )


def _queueflush_handlers() -> QueueFlushHandlers:
    return QueueFlushHandlers(
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_queue_job=_cancel_queue_job,
        _configured_queue_playlists=_configured_queue_playlists,
        get_blast_job=get_blast_job,
        start_queue_flush_job=start_queue_flush_job,
    )


def _discovery_handlers() -> DiscoveryHandlers:
    return DiscoveryHandlers(
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _configured_album_discovery_playlists=_configured_album_discovery_playlists,
        get_blast_job=get_blast_job,
        start_new_kids_job=start_new_kids_job,
    )


def _queue2_handlers() -> Queue2Handlers:
    return Queue2Handlers(
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _configured_album_discovery_playlists=_configured_album_discovery_playlists,
        get_blast_job=get_blast_job,
        start_queue_2_job=start_queue_2_job,
    )


def _queue3_handlers() -> Queue3Handlers:
    return Queue3Handlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_queue_3_job=start_queue_3_job,
    )


def _wine_handlers() -> WineHandlers:
    return WineHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_new_wine_job=start_new_wine_job,
    )


def _slowlistening_handlers() -> SlowListeningHandlers:
    return SlowListeningHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_slow_listening_job=start_slow_listening_job,
    )


def _somethingold_handlers() -> SomethingOldHandlers:
    return SomethingOldHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_something_old_job=start_something_old_job,
    )


def _releases_handlers() -> ReleasesHandlers:
    return ReleasesHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs=_blast_jobs,
        _blast_jobs_lock=_blast_jobs_lock,
        _release_check_state_snapshot=_release_check_state_snapshot,
        _release_state_is_newer=_release_state_is_newer,
        get_blast_job=get_blast_job,
        get_state_service=get_state_service,
        start_release_check_job=start_release_check_job,
    )


def _discography_handlers() -> DiscographyHandlers:
    return DiscographyHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_discography_job=start_discography_job,
    )


def _requeue_handlers() -> RequeueHandlers:
    return RequeueHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_requeue_for_a_dream_job=start_requeue_for_a_dream_job,
    )


def _palace_handlers() -> PalaceHandlers:
    return PalaceHandlers(
        Settings=Settings,
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_playlist_jobs=_active_playlist_jobs,
        _append_blast_log_locked=_append_blast_log_locked,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        get_blast_job=get_blast_job,
        start_palace_of_memory_job=start_palace_of_memory_job,
    )


def _history_handlers() -> HistoryHandlers:
    return HistoryHandlers(
        LIBRARY_MIRROR_FILE_PATHS=LIBRARY_MIRROR_FILE_PATHS,
        Settings=Settings,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_simple_playlist_job=_cancel_simple_playlist_job,
        _server_file_status=_server_file_status,
        get_blast_job=get_blast_job,
        get_library_data_service=get_library_data_service,
        start_scrobble_history_job=start_scrobble_history_job,
    )


def _analysis_handlers() -> AnalysisHandlers:
    return AnalysisHandlers(
        _ACTIVE_JOB_STATUSES=_ACTIVE_JOB_STATUSES,
        _active_analysis_jobs=_active_analysis_jobs,
        _analysis_jobs_lock=_analysis_jobs_lock,
        _append_job_log_locked=_append_job_log_locked,
        _job_snapshot=_job_snapshot,
        get_analysis_job=get_analysis_job,
        start_analysis_job=start_analysis_job,
    )


def _newyear_handlers() -> NewYearHandlers:
    return NewYearHandlers(
        Thread=Thread,
        _active_playlist_jobs=_active_playlist_jobs,
        _blast_job_snapshot=_blast_job_snapshot,
        _blast_jobs=_blast_jobs,
        _blast_jobs_lock=_blast_jobs_lock,
        _cancel_simple_playlist_job=_cancel_simple_playlist_job,
        _require_playlist_slot=_require_playlist_slot,
        _run_new_year_job=_run_new_year_job,
        get_blast_job=get_blast_job,
        uuid4=uuid4,
    )


def health() -> dict[str, str]:
    """Liveness probe."""
    return _health_handlers().health()


def auth_check() -> dict[str, str]:
    """Side-effect-free password check protected by the deployment middleware."""
    return _health_handlers().auth_check()


def shared_state_summary() -> SharedStateSummary:
    """Return state freshness without transferring the complete document."""
    return _state_handlers().shared_state_summary()


def shared_state() -> SharedStateSnapshot:
    """Return the complete shared application state and revision guard."""
    return _state_handlers().shared_state()


def shared_state_editor_schema() -> dict[str, Any]:
    """Return backend-owned controls and constraints for manual state edits."""
    return _state_handlers().shared_state_editor_schema()


def replace_shared_state_namespace(
    namespace: str, request: SharedStateNamespaceReplaceRequest
) -> SharedStateSnapshot:
    """Validate and replace only one namespace at the viewed revision."""
    return _state_handlers().replace_shared_state_namespace(namespace, request)


def replace_shared_state(request: SharedStateReplaceRequest) -> SharedStateSnapshot:
    """Manually replace shared state only when the viewed revision is current."""
    return _state_handlers().replace_shared_state(request)


def export_shared_state() -> Response:
    """Download the current shared state as a JSON snapshot."""
    return _state_handlers().export_shared_state()


def refresh_library() -> CommandResult:
    """Drop the cached library so the next request re-reads YourLibrary.json."""
    return _lookups_handlers().refresh_library()


def artist_stats(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    artist_id: Annotated[str | None, Query()] = None,
) -> ArtistLibraryStats:
    """Return live Liked Songs and Saved Albums counts for one artist."""
    return _lookups_handlers().artist_stats(client, reference, name, artist_id)


def album_evaluation(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    album_id: Annotated[str | None, Query()] = None,
    artist: Annotated[str | None, Query()] = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Return a keep/remove decision from live Spotify album and liked state."""
    return _lookups_handlers().album_evaluation(
        client, reference, name, album_id, artist, threshold
    )


def track_scrobble_status(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    track_id: Annotated[str | None, Query()] = None,
) -> TrackScrobbleStatus:
    """Return the latest Last.fm scrobble for one live Spotify track."""
    return _lookups_handlers().track_scrobble_status(client, reference, name, track_id)


def cmd_monthly_routines(client: ClientDep) -> CommandResult:
    """Run the full monthly routine (compare, convert, monthly)."""
    return _librarycommands_handlers().cmd_monthly_routines(client)


def cmd_update_total_albums(
    client: ClientDep, just_update: bool = False
) -> CommandResult:
    """Update the total album list."""
    return _librarycommands_handlers().cmd_update_total_albums(client, just_update)


def cmd_restore_your_library(client: ClientDep) -> CommandResult:
    """Restore artists and tracks from the YourLibrary file."""
    return _librarycommands_handlers().cmd_restore_your_library(client)


def cmd_compare_lib_files() -> CommandResult:
    """Create the comparison between YourLibrary and the total-albums file."""
    return _librarycommands_handlers().cmd_compare_lib_files()


def cmd_analyse_comp(client: ClientDep) -> CommandResult:
    """Analyse the saved comparison file against the live library."""
    return _librarycommands_handlers().cmd_analyse_comp(client)


def cmd_convert_lib(client: ClientDep) -> CommandResult:
    """Convert the YourLibrary file into the total-albums file."""
    return _librarycommands_handlers().cmd_convert_lib(client)


def cmd_count_artists() -> CountResult:
    """Count the artists in the YourLibrary file."""
    return _librarycommands_handlers().cmd_count_artists()


def cmd_blast_from_the_past(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a background Friday-routine playlist update."""
    return _historical_handlers().cmd_blast_from_the_past(
        client, count, max_playlist_length, dry_run
    )


def cmd_active_blast_jobs() -> list[BlastJobResult]:
    """Return active playlist jobs so the web UI can reconnect after reload."""
    return _historical_handlers().cmd_active_blast_jobs()


def cmd_blast_job(job_id: str) -> BlastJobResult:
    """Return current progress for one playlist job."""
    return _historical_handlers().cmd_blast_job(job_id)


def cmd_cancel_blast_job(job_id: str) -> BlastJobResult:
    """Stop a Blast job at the next bounded network-operation boundary."""
    return _historical_handlers().cmd_cancel_blast_job(job_id)


def cmd_blast_from_the_past_artists(
    client: InteractiveClientDep,
    count: Annotated[int, Query(ge=1)] = blast_from_past_artists.DEFAULT_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an alphabetic dormant-artist recovery update."""
    return _dormant_handlers().cmd_blast_from_the_past_artists(client, count, dry_run)


def cmd_active_blast_artist_jobs() -> list[BlastJobResult]:
    """Return the active dormant-artist job for browser reconnection."""
    return _dormant_handlers().cmd_active_blast_artist_jobs()


def cmd_blast_artist_job(job_id: str) -> BlastJobResult:
    """Return current progress for one dormant-artist job."""
    return _dormant_handlers().cmd_blast_artist_job(job_id)


def cmd_cancel_blast_artist_job(job_id: str) -> BlastJobResult:
    """Cancel dormant-artist recovery at the next safe boundary."""
    return _dormant_handlers().cmd_cancel_blast_artist_job(job_id)


def cmd_daily_mind_radio(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a background Daily Mind Radio anniversary update."""
    return _dailymindradio_handlers().cmd_daily_mind_radio(client, dry_run)


def cmd_active_daily_mind_radio_jobs() -> list[BlastJobResult]:
    """Return active Daily Mind Radio jobs for web reload reconnection."""
    return _dailymindradio_handlers().cmd_active_daily_mind_radio_jobs()


def cmd_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Daily Mind Radio job."""
    return _dailymindradio_handlers().cmd_daily_mind_radio_job(job_id)


def cmd_cancel_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Stop Daily Mind Radio at the next bounded network-operation boundary."""
    return _dailymindradio_handlers().cmd_cancel_daily_mind_radio_job(job_id)


def cmd_found_art(
    client: ClientDep, count: Annotated[int, Query(ge=1)] = found_art.DEFAULT_COUNT
) -> BlastJobResult:
    """Start a background Found Art recommendation update."""
    return _foundart_handlers().cmd_found_art(client, count)


def cmd_active_found_art_jobs() -> list[BlastJobResult]:
    """Return active Found Art jobs for web reload reconnection."""
    return _foundart_handlers().cmd_active_found_art_jobs()


def cmd_found_art_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Found Art job."""
    return _foundart_handlers().cmd_found_art_job(job_id)


def cmd_fill_sauvignon_from_lastfm(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    seed_count: Annotated[int, Query(ge=1)] = sauvignon.DEFAULT_SEED_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start reconnectable Last.fm album discovery for Sauvignon."""
    return _sauvignon_handlers().cmd_fill_sauvignon_from_lastfm(
        client, count, max_playlist_length, seed_count, dry_run
    )


def cmd_active_sauvignon_jobs() -> list[BlastJobResult]:
    """Return active Sauvignon jobs so the UI can reconnect after reload."""
    return _sauvignon_handlers().cmd_active_sauvignon_jobs()


def cmd_sauvignon_job(job_id: str) -> BlastJobResult:
    """Return Sauvignon progress and any pending album-edition choice."""
    return _sauvignon_handlers().cmd_sauvignon_job(job_id)


def cmd_choose_sauvignon_album(
    job_id: str, request: SauvignonChoiceRequest
) -> BlastJobResult:
    """Submit one ambiguous Spotify album edition, skip, or quit choice."""
    return _sauvignon_handlers().cmd_choose_sauvignon_album(job_id, request)


def cmd_cancel_sauvignon_job(job_id: str) -> BlastJobResult:
    """Stop Sauvignon discovery at its next safe boundary."""
    return _sauvignon_handlers().cmd_cancel_sauvignon_job(job_id)


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


def cmd_fill_queue_from_lastfm(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    seed_count: Annotated[int, Query(ge=1)] = the_queue.DEFAULT_SEED_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start reconnectable Last.fm artist discovery for The Queue."""
    return _queuefill_handlers().cmd_fill_queue_from_lastfm(
        client, count, max_playlist_length, seed_count, dry_run
    )


def cmd_active_queue_fill_jobs() -> list[BlastJobResult]:
    """Return active Queue fill jobs so the UI can reconnect after reload."""
    return _queuefill_handlers().cmd_active_queue_fill_jobs()


def cmd_queue_fill_job(job_id: str) -> BlastJobResult:
    """Return Queue fill progress and any pending artist mapping."""
    return _queuefill_handlers().cmd_queue_fill_job(job_id)


def cmd_choose_queue_artist(job_id: str, request: QueueChoiceRequest) -> BlastJobResult:
    """Submit one Spotify artist mapping, custom search, skip, or quit."""
    return _queuefill_handlers().cmd_choose_queue_artist(job_id, request)


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


def cmd_cancel_queue_fill_job(job_id: str) -> BlastJobResult:
    """Stop Queue artist discovery at its next safe boundary."""
    return _queuefill_handlers().cmd_cancel_queue_fill_job(job_id)


def cmd_flush_queue(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reconnectable flush of the first ten Queue artists."""
    return _queueflush_handlers().cmd_flush_queue(client, dry_run)


def cmd_active_queue_flush_jobs() -> list[BlastJobResult]:
    """Return active Queue flush jobs for page reload reconnection."""
    return _queueflush_handlers().cmd_active_queue_flush_jobs()


def cmd_queue_flush_job(job_id: str) -> BlastJobResult:
    """Return current Queue flush progress and result details."""
    return _queueflush_handlers().cmd_queue_flush_job(job_id)


def cmd_cancel_queue_flush_job(job_id: str) -> BlastJobResult:
    """Stop a Queue flush while preserving its durable checkpoint."""
    return _queueflush_handlers().cmd_cancel_queue_flush_job(job_id)


def cmd_flush_new_kids(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive New Kids flush with reconnectable web state."""
    return _discovery_handlers().cmd_flush_new_kids(client, dry_run)


def _configured_album_discovery_playlists() -> tuple[str, str, str, str, str]:
    """Load the five shared New Kids and Queue 2 playlist settings."""
    configuration = Settings()
    try:
        new_kids_playlist_id = new_kids.parse_playlist_id(
            configuration.new_kids_on_the_block_playlist,
            "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
        )
        queue_2_playlist_id = new_kids.parse_playlist_id(
            configuration.the_queue_2_playlist, "THE_QUEUE_2_PLAYLIST"
        )
        great_discoveries_playlist_id = new_kids.parse_playlist_id(
            configuration.great_discoveries_2026_playlist,
            "GREAT_DISCOVERIES_2026_PLAYLIST",
        )
        unlucky_ones_playlist_id = new_kids.parse_playlist_id(
            configuration.unlucky_ones_playlist, "UNLUCKY_ONES_PLAYLIST"
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


def cmd_active_new_kids_jobs() -> list[BlastJobResult]:
    """Return active New Kids jobs so the web UI can reconnect after reload."""
    return _discovery_handlers().cmd_active_new_kids_jobs()


def cmd_new_kids_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending New Kids choice."""
    return _discovery_handlers().cmd_new_kids_job(job_id)


def cmd_choose_new_kids_release(
    job_id: str, request: NewKidsChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Kids job."""
    return _discovery_handlers().cmd_choose_new_kids_release(job_id, request)


def cmd_cancel_new_kids_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Kids processing boundary."""
    return _discovery_handlers().cmd_cancel_new_kids_job(job_id)


def cmd_flush_queue_2(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Queue 2 flush with reconnectable web state."""
    return _queue2_handlers().cmd_flush_queue_2(client, dry_run)


def cmd_active_queue_2_jobs() -> list[BlastJobResult]:
    """Return active Queue 2 jobs so the web UI can reconnect after reload."""
    return _queue2_handlers().cmd_active_queue_2_jobs()


def cmd_queue_2_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 2 choice."""
    return _queue2_handlers().cmd_queue_2_job(job_id)


def cmd_choose_queue_2_release(
    job_id: str, request: NewKidsChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting Queue 2 job."""
    return _queue2_handlers().cmd_choose_queue_2_release(job_id, request)


def cmd_cancel_queue_2_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 2 processing boundary."""
    return _queue2_handlers().cmd_cancel_queue_2_job(job_id)


def cmd_flush_queue_3(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Queue 3 flush with reconnectable web state."""
    return _queue3_handlers().cmd_flush_queue_3(client, dry_run)


def cmd_import_queue_3_previous_year(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start the annual Queue 3 import without advancing existing artists."""
    return _queue3_handlers().cmd_import_queue_3_previous_year(client, dry_run)


def cmd_active_queue_3_jobs() -> list[BlastJobResult]:
    """Return active Queue 3 jobs so the web UI can reconnect after reload."""
    return _queue3_handlers().cmd_active_queue_3_jobs()


def cmd_queue_3_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 3 choice."""
    return _queue3_handlers().cmd_queue_3_job(job_id)


def cmd_choose_queue_3(job_id: str, request: Queue3ChoiceRequest) -> BlastJobResult:
    """Submit one release, composer-playlist, or quit choice to Queue 3."""
    return _queue3_handlers().cmd_choose_queue_3(job_id, request)


def cmd_cancel_queue_3_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 3 processing boundary."""
    return _queue3_handlers().cmd_cancel_queue_3_job(job_id)


def cmd_flush_new_wine(
    client: InteractiveClientDep,
    dry_run: bool = True,
    no_discovery: bool = False,
    choose_album_endpoints: bool = False,
) -> BlastJobResult:
    """Start an interactive New Wine flush with reconnectable web state."""
    return _wine_handlers().cmd_flush_new_wine(
        client, dry_run, no_discovery, choose_album_endpoints
    )


def cmd_active_new_wine_jobs() -> list[BlastJobResult]:
    """Return active New Wine jobs so the web UI can reconnect after reload."""
    return _wine_handlers().cmd_active_new_wine_jobs()


def cmd_new_wine_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending choice for one New Wine job."""
    return _wine_handlers().cmd_new_wine_job(job_id)


def cmd_choose_new_wine_release(
    job_id: str, request: NewWineChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Wine job."""
    return _wine_handlers().cmd_choose_new_wine_release(job_id, request)


def cmd_cancel_new_wine_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Wine processing boundary."""
    return _wine_handlers().cmd_cancel_new_wine_job(job_id)


def cmd_flush_slow_listening(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Slow Listening flush with reconnectable state."""
    return _slowlistening_handlers().cmd_flush_slow_listening(client, dry_run)


def cmd_active_slow_listening_jobs() -> list[BlastJobResult]:
    """Return active Slow Listening jobs for page-reload reconnection."""
    return _slowlistening_handlers().cmd_active_slow_listening_jobs()


def cmd_slow_listening_job(job_id: str) -> BlastJobResult:
    """Return current progress and the pending Slow Listening choice."""
    return _slowlistening_handlers().cmd_slow_listening_job(job_id)


def cmd_choose_slow_listening_track(
    job_id: str, request: SlowListeningChoiceRequest
) -> BlastJobResult:
    """Submit a candidate, release order, or completion acknowledgement."""
    return _slowlistening_handlers().cmd_choose_slow_listening_track(job_id, request)


def cmd_cancel_slow_listening_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Slow Listening boundary."""
    return _slowlistening_handlers().cmd_cancel_slow_listening_job(job_id)


def cmd_something_old(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Something Old selection with reconnectable state."""
    return _somethingold_handlers().cmd_something_old(client, dry_run)


def cmd_active_something_old_jobs() -> list[BlastJobResult]:
    """Return active Something Old jobs for page-reload reconnection."""
    return _somethingold_handlers().cmd_active_something_old_jobs()


def cmd_something_old_job(job_id: str) -> BlastJobResult:
    """Return current Something Old progress and any pending choice."""
    return _somethingold_handlers().cmd_something_old_job(job_id)


def cmd_choose_something_old(
    job_id: str, request: SomethingOldChoiceRequest
) -> BlastJobResult:
    """Submit an exact artist, source mode, album/EP, or quit choice."""
    return _somethingold_handlers().cmd_choose_something_old(job_id, request)


def cmd_cancel_something_old_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Something Old boundary."""
    return _somethingold_handlers().cmd_cancel_something_old_job(job_id)


def cmd_check_new_releases(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reconnectable release check for Last.fm's top artists."""
    return _releases_handlers().cmd_check_new_releases(client, dry_run)


def cmd_release_check_state(
    known_fingerprint: str | None = None,
) -> ReleaseCheckStateSnapshot:
    """Return restart state, omitting the payload when the browser is current."""
    return _releases_handlers().cmd_release_check_state(known_fingerprint)


def cmd_restore_release_check_state(
    request: ReleaseCheckStateRestoreRequest,
) -> ReleaseCheckStateSnapshot:
    """Restore a newer browser mirror without overwriting concurrent progress."""
    return _releases_handlers().cmd_restore_release_check_state(request)


def cmd_active_release_check_jobs() -> list[BlastJobResult]:
    """Return active release checks for page-reload reconnection."""
    return _releases_handlers().cmd_active_release_check_jobs()


def cmd_release_check_job(job_id: str) -> BlastJobResult:
    """Return release-check progress and any pending interaction."""
    return _releases_handlers().cmd_release_check_job(job_id)


def cmd_choose_release_check(
    job_id: str, request: ReleaseCheckChoiceRequest
) -> BlastJobResult:
    """Submit an artist mapping, custom search, or release decision."""
    return _releases_handlers().cmd_choose_release_check(job_id, request)


def cmd_cancel_release_check_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next release-check boundary."""
    return _releases_handlers().cmd_cancel_release_check_job(job_id)


def cmd_plan_discographies(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reload-safe interactive discography planning job."""
    return _discography_handlers().cmd_plan_discographies(client, dry_run)


def cmd_active_discography_jobs() -> list[BlastJobResult]:
    """Return active discography jobs for page-reload reconnection."""
    return _discography_handlers().cmd_active_discography_jobs()


def cmd_discography_job(job_id: str) -> BlastJobResult:
    """Return discography progress and its current interaction."""
    return _discography_handlers().cmd_discography_job(job_id)


def cmd_choose_discography(
    job_id: str, request: DiscographyChoiceRequest
) -> BlastJobResult:
    """Submit a release checklist or final marker-removal decision."""
    return _discography_handlers().cmd_choose_discography(job_id, request)


def cmd_cancel_discography_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next discography boundary."""
    return _discography_handlers().cmd_cancel_discography_job(job_id)


def cmd_flush_requeue_for_a_dream(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reconnectable Requeue for a Dream transition."""
    return _requeue_handlers().cmd_flush_requeue_for_a_dream(client, dry_run)


def cmd_active_requeue_for_a_dream_jobs() -> list[BlastJobResult]:
    """Return active Requeue for a Dream jobs after a page reload."""
    return _requeue_handlers().cmd_active_requeue_for_a_dream_jobs()


def cmd_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one Requeue transition."""
    return _requeue_handlers().cmd_requeue_for_a_dream_job(job_id)


def cmd_cancel_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next API or retry boundary."""
    return _requeue_handlers().cmd_cancel_requeue_for_a_dream_job(job_id)


def cmd_fill_palace_of_memory(
    client: InteractiveClientDep,
    dry_run: bool = True,
    alphabetical_start: str | None = None,
    set_alphabetical_cursor: int | None = Query(default=None, ge=1),
) -> BlastJobResult:
    """Start a reconnectable Palace fill or cursor-only adjustment."""
    return _palace_handlers().cmd_fill_palace_of_memory(
        client, dry_run, alphabetical_start, set_alphabetical_cursor
    )


def cmd_active_palace_of_memory_jobs() -> list[BlastJobResult]:
    """Return active Palace jobs after a page reload."""
    return _palace_handlers().cmd_active_palace_of_memory_jobs()


def cmd_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Return current Palace progress, results, and logs."""
    return _palace_handlers().cmd_palace_of_memory_job(job_id)


def cmd_cancel_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Request a clean Palace stop at the next API or retry boundary."""
    return _palace_handlers().cmd_cancel_palace_of_memory_job(job_id)


def cmd_update_scrobble_history(
    dry_run: bool = True, full_rebuild: bool = False
) -> BlastJobResult:
    """Start a background refresh of the shared Last.fm scrobble record."""
    return _history_handlers().cmd_update_scrobble_history(dry_run, full_rebuild)


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
    return ServerFileStatus(filename=path.name, exists=True, updated_at=modified_at)


def library_mirror_files_status() -> LibraryMirrorFilesStatus:
    """Return durable update metadata for all canonical data files."""
    return _history_handlers().library_mirror_files_status()


def cmd_active_scrobble_history_jobs() -> list[BlastJobResult]:
    """Return active history refreshes for page-reload reconnection."""
    return _history_handlers().cmd_active_scrobble_history_jobs()


def cmd_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one history refresh."""
    return _history_handlers().cmd_scrobble_history_job(job_id)


def cmd_cancel_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Request a clean history stop before its next persistence boundary."""
    return _history_handlers().cmd_cancel_scrobble_history_job(job_id)


def cmd_analyse_library_async() -> AnalysisJobResult:
    """Start an export-only ``*_async`` library analysis."""
    return _analysis_handlers().cmd_analyse_library_async()


def cmd_analyse_library_sync(client: AnalysisClientDep) -> AnalysisJobResult:
    """Start a live-only ``*_sync`` library analysis."""
    return _analysis_handlers().cmd_analyse_library_sync(client)


def cmd_refresh_library_mirrors(
    client: AnalysisClientDep, full_rebuild: bool = False
) -> AnalysisJobResult:
    """Refresh canonical saved-album and liked-track mirrors from Spotify."""
    return _analysis_handlers().cmd_refresh_library_mirrors(client, full_rebuild)


def cmd_refresh_library_mirror_resource(
    resource: library_analysis.ResourceName,
    client: AnalysisClientDep,
    full_rebuild: bool = False,
) -> AnalysisJobResult:
    """Refresh one canonical Spotify mirror with independent progress."""
    return _analysis_handlers().cmd_refresh_library_mirror_resource(
        resource, client, full_rebuild
    )


def cmd_active_library_analysis_jobs() -> list[AnalysisJobResult]:
    """Return active analyses so the web UI can reconnect after a reload."""
    return _analysis_handlers().cmd_active_library_analysis_jobs()


def cmd_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Return current progress for one library analysis job."""
    return _analysis_handlers().cmd_library_analysis_job(job_id)


def cmd_cancel_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Request a clean stop at the next durable analysis boundary."""
    return _analysis_handlers().cmd_cancel_library_analysis_job(job_id)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API with uvicorn (entry point for the ``spotify-api`` script)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


def _run_new_year_job(
    job_id: str, spotify: Spotify, year: int | None, dry_run: bool
) -> None:
    """Run the annual workflow through the shared routine and job registry."""
    NewYearWorker(
        job_id=job_id,
        spotify=spotify,
        year=year,
        dry_run=dry_run,
        create_lastfm=LastFmClient,
        configuration=Settings,
        append=_append_blast_log_locked,
        lock=_blast_jobs_lock,
        _playlist_job_retry=_playlist_job_retry,
        clock=datetime,
        lookup=get_blast_job,
    ).run()


def cmd_new_year(
    client: ClientDep, dry_run: bool = True, year: int | None = None
) -> BlastJobResult:
    """Start all New Year's Routines for the previous completed calendar year."""
    return _newyear_handlers().cmd_new_year(client, dry_run, year)


def cmd_active_new_year_jobs() -> list[BlastJobResult]:
    """Reconnect to an active annual workflow after browser reload."""
    return _newyear_handlers().cmd_active_new_year_jobs()


def cmd_new_year_job(job_id: str) -> BlastJobResult:
    """Return annual progress, rankings, and logs."""
    return _newyear_handlers().cmd_new_year_job(job_id)


def cmd_cancel_new_year_job(job_id: str) -> BlastJobResult:
    """Cancel at the next boundary, retaining completed annual steps."""
    return _newyear_handlers().cmd_cancel_new_year_job(job_id)


def _active_playlist_jobs(command: str) -> list[BlastJobResult]:
    with _blast_jobs_lock:
        return active_playlist_snapshots(
            _blast_jobs.values(), command, _blast_job_snapshot
        )


def _active_analysis_jobs() -> list[AnalysisJobResult]:
    with _analysis_jobs_lock:
        return active_analysis_snapshots(_analysis_jobs.values(), _job_snapshot)


app.include_router(_health_router(health, auth_check))
app.include_router(
    _state_router(
        shared_state_summary,
        shared_state,
        shared_state_editor_schema,
        replace_shared_state_namespace,
        replace_shared_state,
        export_shared_state,
    )
)
app.include_router(
    _lookups_router(
        refresh_library, artist_stats, album_evaluation, track_scrobble_status
    )
)
app.include_router(
    _library_commands_router(
        cmd_monthly_routines,
        cmd_update_total_albums,
        cmd_restore_your_library,
        cmd_compare_lib_files,
        cmd_analyse_comp,
        cmd_convert_lib,
        cmd_count_artists,
    )
)
app.include_router(
    _historical_router(
        cmd_blast_from_the_past,
        cmd_active_blast_jobs,
        cmd_blast_job,
        cmd_cancel_blast_job,
    )
)
app.include_router(
    _dormant_router(
        cmd_blast_from_the_past_artists,
        cmd_active_blast_artist_jobs,
        cmd_blast_artist_job,
        cmd_cancel_blast_artist_job,
    )
)
app.include_router(
    _daily_mind_radio_router(
        cmd_daily_mind_radio,
        cmd_active_daily_mind_radio_jobs,
        cmd_daily_mind_radio_job,
        cmd_cancel_daily_mind_radio_job,
    )
)
app.include_router(
    _found_art_router(cmd_found_art, cmd_active_found_art_jobs, cmd_found_art_job)
)
app.include_router(
    _sauvignon_router(
        cmd_fill_sauvignon_from_lastfm,
        cmd_active_sauvignon_jobs,
        cmd_sauvignon_job,
        cmd_choose_sauvignon_album,
        cmd_cancel_sauvignon_job,
    )
)
app.include_router(
    _queue_fill_router(
        cmd_fill_queue_from_lastfm,
        cmd_active_queue_fill_jobs,
        cmd_queue_fill_job,
        cmd_choose_queue_artist,
        cmd_cancel_queue_fill_job,
    )
)
app.include_router(
    _queue_flush_router(
        cmd_flush_queue,
        cmd_active_queue_flush_jobs,
        cmd_queue_flush_job,
        cmd_cancel_queue_flush_job,
    )
)
app.include_router(
    _discovery_router(
        cmd_flush_new_kids,
        cmd_active_new_kids_jobs,
        cmd_new_kids_job,
        cmd_choose_new_kids_release,
        cmd_cancel_new_kids_job,
    )
)
app.include_router(
    _queue_2_router(
        cmd_flush_queue_2,
        cmd_active_queue_2_jobs,
        cmd_queue_2_job,
        cmd_choose_queue_2_release,
        cmd_cancel_queue_2_job,
    )
)
app.include_router(
    _queue_3_router(
        cmd_flush_queue_3,
        cmd_import_queue_3_previous_year,
        cmd_active_queue_3_jobs,
        cmd_queue_3_job,
        cmd_choose_queue_3,
        cmd_cancel_queue_3_job,
    )
)
app.include_router(
    _wine_router(
        cmd_flush_new_wine,
        cmd_active_new_wine_jobs,
        cmd_new_wine_job,
        cmd_choose_new_wine_release,
        cmd_cancel_new_wine_job,
    )
)
app.include_router(
    _slow_listening_router(
        cmd_flush_slow_listening,
        cmd_active_slow_listening_jobs,
        cmd_slow_listening_job,
        cmd_choose_slow_listening_track,
        cmd_cancel_slow_listening_job,
    )
)
app.include_router(
    _something_old_router(
        cmd_something_old,
        cmd_active_something_old_jobs,
        cmd_something_old_job,
        cmd_choose_something_old,
        cmd_cancel_something_old_job,
    )
)
app.include_router(
    _releases_router(
        cmd_check_new_releases,
        cmd_release_check_state,
        cmd_restore_release_check_state,
        cmd_active_release_check_jobs,
        cmd_release_check_job,
        cmd_choose_release_check,
        cmd_cancel_release_check_job,
    )
)
app.include_router(
    _discography_router(
        cmd_plan_discographies,
        cmd_active_discography_jobs,
        cmd_discography_job,
        cmd_choose_discography,
        cmd_cancel_discography_job,
    )
)
app.include_router(
    _requeue_router(
        cmd_flush_requeue_for_a_dream,
        cmd_active_requeue_for_a_dream_jobs,
        cmd_requeue_for_a_dream_job,
        cmd_cancel_requeue_for_a_dream_job,
    )
)
app.include_router(
    _palace_router(
        cmd_fill_palace_of_memory,
        cmd_active_palace_of_memory_jobs,
        cmd_palace_of_memory_job,
        cmd_cancel_palace_of_memory_job,
    )
)
app.include_router(
    _history_router(
        cmd_update_scrobble_history,
        library_mirror_files_status,
        cmd_active_scrobble_history_jobs,
        cmd_scrobble_history_job,
        cmd_cancel_scrobble_history_job,
    )
)
app.include_router(
    _analysis_router(
        cmd_analyse_library_async,
        cmd_analyse_library_sync,
        cmd_refresh_library_mirrors,
        cmd_refresh_library_mirror_resource,
        cmd_active_library_analysis_jobs,
        cmd_library_analysis_job,
        cmd_cancel_library_analysis_job,
    )
)
app.include_router(
    _new_year_router(
        cmd_new_year,
        cmd_active_new_year_jobs,
        cmd_new_year_job,
        cmd_cancel_new_year_job,
    )
)
