"""Declare HTTP routes and their explicit request-to-use-case paths."""

from typing import Annotated as Annotated
from typing import Any as Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query as Query
from fastapi import status
from fastapi.responses import Response as Response
from requests.exceptions import RequestException

from spotify_manager.application.album_review import review_album
from spotify_manager.bootstrap.listening import album_review_ports
from spotify_manager.interfaces import sauvignon_operations as sauvignon
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.execution import ExecutionMiddleware
from spotify_manager.interfaces.http.handlers import analysis as analysis_http
from spotify_manager.interfaces.http.handlers import (
    daily_mind_radio as daily_mind_radio_http,
)
from spotify_manager.interfaces.http.handlers import discography as discography_http
from spotify_manager.interfaces.http.handlers import discovery as discovery_http
from spotify_manager.interfaces.http.handlers import dormant as dormant_http
from spotify_manager.interfaces.http.handlers import found_art as found_art_http
from spotify_manager.interfaces.http.handlers import health as health_http
from spotify_manager.interfaces.http.handlers import historical as historical_http
from spotify_manager.interfaces.http.handlers import history as history_http
from spotify_manager.interfaces.http.handlers import (
    library_commands as library_commands_http,
)
from spotify_manager.interfaces.http.handlers import lookups as lookups_http
from spotify_manager.interfaces.http.handlers import new_year as new_year_http
from spotify_manager.interfaces.http.handlers import palace as palace_http
from spotify_manager.interfaces.http.handlers import queue_2 as queue_2_http
from spotify_manager.interfaces.http.handlers import queue_3 as queue_3_http
from spotify_manager.interfaces.http.handlers import queue_fill as queue_fill_http
from spotify_manager.interfaces.http.handlers import queue_flush as queue_flush_http
from spotify_manager.interfaces.http.handlers import releases as releases_http
from spotify_manager.interfaces.http.handlers import requeue as requeue_http
from spotify_manager.interfaces.http.handlers import sauvignon as sauvignon_http
from spotify_manager.interfaces.http.handlers import (
    slow_listening as slow_listening_http,
)
from spotify_manager.interfaces.http.handlers import something_old as something_old_http
from spotify_manager.interfaces.http.handlers import state as state_http
from spotify_manager.interfaces.http.handlers import wine as wine_http
from spotify_manager.interfaces.http.jobs import AnalysisClientDep as AnalysisClientDep
from spotify_manager.interfaces.http.jobs import ClientDep as ClientDep
from spotify_manager.interfaces.http.jobs import (
    InteractiveClientDep as InteractiveClientDep,
)
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisJobResult as AnalysisJobResult,
)
from spotify_manager.interfaces.http.models.common import CommandResult as CommandResult
from spotify_manager.interfaces.http.models.common import CountResult as CountResult
from spotify_manager.interfaces.http.models.common import (
    LibraryMirrorFilesStatus as LibraryMirrorFilesStatus,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyChoiceRequest as DiscographyChoiceRequest,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsChoiceRequest as NewKidsChoiceRequest,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ChoiceRequest as Queue3ChoiceRequest,
)
from spotify_manager.interfaces.http.models.jobs import BlastJobResult as BlastJobResult
from spotify_manager.interfaces.http.models.queue import (
    QueueChoiceRequest as QueueChoiceRequest,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonChoiceRequest as SauvignonChoiceRequest,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckChoiceRequest as ReleaseCheckChoiceRequest,
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
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldChoiceRequest as SomethingOldChoiceRequest,
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
    NewWineChoiceRequest as NewWineChoiceRequest,
)
from spotify_manager.interfaces.operations import analyse_library as library_analysis
from spotify_manager.interfaces.operations import (
    blast_from_past_artists as blast_from_past_artists,
)
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import the_queue as the_queue
from spotify_manager.interfaces.presenters.albums import (
    album_evaluation as present_album,
)
from spotify_manager.models.lookups import AlbumEvaluation as AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats as ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus as TrackScrobbleStatus


app = FastAPI(title="Spotify Manager", version="0.1.0", lifespan=jobs._lifespan)
app.add_middleware(ExecutionMiddleware)
app.exception_handler(jobs.ArtistNotFoundError)(jobs._artist_not_found)
app.exception_handler(jobs.AmbiguousArtistError)(jobs._ambiguous_artist)
app.exception_handler(jobs.AlbumNotFoundError)(jobs._album_not_found)
app.exception_handler(jobs.AmbiguousAlbumError)(jobs._ambiguous_album)
app.exception_handler(jobs.TrackNotFoundError)(jobs._track_not_found)
app.exception_handler(jobs.AmbiguousTrackError)(jobs._ambiguous_track)
app.exception_handler(jobs.SpotifyLookupResponseError)(jobs._invalid_spotify_lookup)
app.exception_handler(jobs.SpotifyException)(jobs._spotify_lookup_failed)


@app.api_route("/health", methods=["GET"], description="Liveness probe.")
def health() -> dict[str, str]:
    """Liveness probe.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return health_http.health()


@app.api_route(
    "/auth/check",
    methods=["GET"],
    description=(
        "Side-effect-free password check protected by the deployment middleware."
    ),
)
def auth_check() -> dict[str, str]:
    """Side-effect-free password check protected by the deployment middleware.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return health_http.auth_check()


@app.api_route(
    "/state/summary",
    methods=["GET"],
    response_model=SharedStateSummary,
    description="Return state freshness without transferring the complete document.",
)
def shared_state_summary() -> SharedStateSummary:
    """Return state freshness without transferring the complete document.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return state_http.shared_state_summary()


@app.api_route(
    "/state",
    methods=["GET"],
    response_model=SharedStateSnapshot,
    description="Return the complete shared application state and revision guard.",
)
def shared_state() -> SharedStateSnapshot:
    """Return the complete shared application state and revision guard.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return state_http.shared_state()


@app.api_route(
    "/state/schema",
    methods=["GET"],
    description="Return backend-owned controls and constraints for manual state edits.",
)
def shared_state_editor_schema() -> dict[str, Any]:
    """Return backend-owned controls and constraints for manual state edits.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return state_http.shared_state_editor_schema()


@app.api_route(
    "/state/namespaces/{namespace}",
    methods=["PUT"],
    response_model=SharedStateSnapshot,
    description="Validate and replace only one namespace at the viewed revision.",
)
def replace_shared_state_namespace(
    namespace: str, request: SharedStateNamespaceReplaceRequest
) -> SharedStateSnapshot:
    """Validate and replace only one namespace at the viewed revision.

    Args:
        namespace: Validated namespace value.
        request: Validated request body.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return state_http.replace_shared_state_namespace(namespace, request)


@app.api_route(
    "/state",
    methods=["PUT"],
    response_model=SharedStateSnapshot,
    description=(
        "Manually replace shared state only when the viewed revision is current."
    ),
)
def replace_shared_state(request: SharedStateReplaceRequest) -> SharedStateSnapshot:
    """Manually replace shared state only when the viewed revision is current.

    Args:
        request: Validated request body.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return state_http.replace_shared_state(request)


@app.api_route(
    "/state/export",
    methods=["GET"],
    description="Download the current shared state as a JSON snapshot.",
)
def export_shared_state() -> Response:
    """Download the current shared state as a JSON snapshot.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return state_http.export_shared_state()


@app.api_route(
    "/library/refresh",
    methods=["POST"],
    response_model=CommandResult,
    description=(
        "Drop the cached library so the next request re-reads YourLibrary.json."
    ),
)
def refresh_library() -> CommandResult:
    """Drop the cached library so the next request re-reads YourLibrary.json.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return lookups_http.refresh_library()


@app.api_route(
    "/artists/stats",
    methods=["GET"],
    response_model=ArtistLibraryStats,
    description="Return live Liked Songs and Saved Albums counts for one artist.",
)
async def artist_stats(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    artist_id: Annotated[str | None, Query()] = None,
) -> ArtistLibraryStats:
    """Return live Liked Songs and Saved Albums counts for one artist.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        reference: Validated reference value.
        name: Validated name value.
        artist_id: Validated artist id value.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await lookups_http.artist_stats(client, reference, name, artist_id)


@app.api_route(
    "/albums/evaluation",
    methods=["GET"],
    response_model=AlbumEvaluation,
    description=(
        "Return a keep/remove decision from live Spotify album and liked state."
    ),
)
async def album_evaluation(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    album_id: Annotated[str | None, Query()] = None,
    artist: Annotated[str | None, Query()] = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Return a keep/remove decision from live Spotify album and liked state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        reference: Validated reference value.
        name: Validated name value.
        album_id: Validated album id value.
        artist: Validated artist value.
        threshold: Validated threshold value.

    Returns:
        The named feature response in its original HTTP representation.

    Raises:
        HTTPException: Input validation or Spotify observation fails.
    """
    request = lookups_http.album_request(reference, name, album_id, artist, threshold)
    catalog, membership = album_review_ports(client)
    try:
        review = await review_album(catalog, membership, request)
    except RequestException as exc:
        raise HTTPException(
            status_code=502, detail=lookups_http.SPOTIFY_UNAVAILABLE
        ) from exc
    return present_album(review)


@app.api_route(
    "/tracks/scrobbles",
    methods=["GET"],
    response_model=TrackScrobbleStatus,
    description="Return the latest Last.fm scrobble for one live Spotify track.",
)
async def track_scrobble_status(
    client: ClientDep,
    reference: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    track_id: Annotated[str | None, Query()] = None,
) -> TrackScrobbleStatus:
    """Return the latest Last.fm scrobble for one live Spotify track.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        reference: Validated reference value.
        name: Validated name value.
        track_id: Validated track id value.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await lookups_http.track_scrobble_status(client, reference, name, track_id)


@app.api_route(
    "/commands/monthly-routines",
    methods=["POST"],
    response_model=CommandResult,
    description="Run the full monthly routine (compare, convert, monthly).",
)
async def cmd_monthly_routines(client: ClientDep) -> CommandResult:
    """Run the full monthly routine (compare, convert, monthly).

    Args:
        client: Authenticated client supplied by the HTTP dependency.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_monthly_routines(client)


@app.api_route(
    "/commands/update-total-albums",
    methods=["POST"],
    response_model=CommandResult,
    description="Update the total album list.",
)
async def cmd_update_total_albums(
    client: ClientDep, just_update: bool = False
) -> CommandResult:
    """Update the total album list.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        just_update: Validated just update value.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_update_total_albums(client, just_update)


@app.api_route(
    "/commands/restore-your-library",
    methods=["POST"],
    response_model=CommandResult,
    description="Restore artists and tracks from the YourLibrary file.",
)
async def cmd_restore_your_library(client: ClientDep) -> CommandResult:
    """Restore artists and tracks from the YourLibrary file.

    Args:
        client: Authenticated client supplied by the HTTP dependency.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_restore_your_library(client)


@app.api_route(
    "/commands/compare-lib-files",
    methods=["POST"],
    response_model=CommandResult,
    description="Create the comparison between YourLibrary and the total-albums file.",
)
async def cmd_compare_lib_files() -> CommandResult:
    """Create the comparison between YourLibrary and the total-albums file.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_compare_lib_files()


@app.api_route(
    "/commands/analyse-comp",
    methods=["POST"],
    response_model=CommandResult,
    description="Analyse the saved comparison file against the live library.",
)
async def cmd_analyse_comp(client: ClientDep) -> CommandResult:
    """Analyse the saved comparison file against the live library.

    Args:
        client: Authenticated client supplied by the HTTP dependency.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_analyse_comp(client)


@app.api_route(
    "/commands/convert-lib",
    methods=["POST"],
    response_model=CommandResult,
    description="Convert the YourLibrary file into the total-albums file.",
)
async def cmd_convert_lib(client: ClientDep) -> CommandResult:
    """Convert the YourLibrary file into the total-albums file.

    Args:
        client: Authenticated client supplied by the HTTP dependency.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_convert_lib(client)


@app.api_route(
    "/commands/count-artists",
    methods=["GET"],
    response_model=CountResult,
    description="Count the artists in the YourLibrary file.",
)
async def cmd_count_artists() -> CountResult:
    """Count the artists in the YourLibrary file.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await library_commands_http.cmd_count_artists()


@app.api_route(
    "/commands/blast-from-the-past",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a background Friday-routine playlist update.",
)
async def cmd_blast_from_the_past(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a background Friday-routine playlist update.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        count: Validated count value.
        max_playlist_length: Validated max playlist length value.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await historical_http.cmd_blast_from_the_past(
        client, count, max_playlist_length, dry_run
    )


@app.api_route(
    "/commands/blast-from-the-past-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active playlist jobs so the web UI can reconnect after reload.",
)
def cmd_active_blast_jobs() -> list[BlastJobResult]:
    """Return active playlist jobs so the web UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return historical_http.cmd_active_blast_jobs()


@app.api_route(
    "/commands/blast-from-the-past-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress for one playlist job.",
)
def cmd_blast_job(job_id: str) -> BlastJobResult:
    """Return current progress for one playlist job.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return historical_http.cmd_blast_job(job_id)


@app.api_route(
    "/commands/blast-from-the-past-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Stop a Blast job at the next bounded network-operation boundary.",
)
def cmd_cancel_blast_job(job_id: str) -> BlastJobResult:
    """Stop a Blast job at the next bounded network-operation boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return historical_http.cmd_cancel_blast_job(job_id)


@app.api_route(
    "/commands/blast-from-the-past-artists",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an alphabetic dormant-artist recovery update.",
)
async def cmd_blast_from_the_past_artists(
    client: InteractiveClientDep,
    count: Annotated[int, Query(ge=1)] = blast_from_past_artists.DEFAULT_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an alphabetic dormant-artist recovery update.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        count: Validated count value.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await dormant_http.cmd_blast_from_the_past_artists(client, count, dry_run)


@app.api_route(
    "/commands/blast-from-the-past-artists-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return the active dormant-artist job for browser reconnection.",
)
def cmd_active_blast_artist_jobs() -> list[BlastJobResult]:
    """Return the active dormant-artist job for browser reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return dormant_http.cmd_active_blast_artist_jobs()


@app.api_route(
    "/commands/blast-from-the-past-artists-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress for one dormant-artist job.",
)
def cmd_blast_artist_job(job_id: str) -> BlastJobResult:
    """Return current progress for one dormant-artist job.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return dormant_http.cmd_blast_artist_job(job_id)


@app.api_route(
    "/commands/blast-from-the-past-artists-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Cancel dormant-artist recovery at the next safe boundary.",
)
def cmd_cancel_blast_artist_job(job_id: str) -> BlastJobResult:
    """Cancel dormant-artist recovery at the next safe boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return dormant_http.cmd_cancel_blast_artist_job(job_id)


@app.api_route(
    "/commands/daily-mind-radio",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a background Daily Mind Radio anniversary update.",
)
async def cmd_daily_mind_radio(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a background Daily Mind Radio anniversary update.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await daily_mind_radio_http.cmd_daily_mind_radio(client, dry_run)


@app.api_route(
    "/commands/daily-mind-radio-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Daily Mind Radio jobs for web reload reconnection.",
)
def cmd_active_daily_mind_radio_jobs() -> list[BlastJobResult]:
    """Return active Daily Mind Radio jobs for web reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return daily_mind_radio_http.cmd_active_daily_mind_radio_jobs()


@app.api_route(
    "/commands/daily-mind-radio-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress for one Daily Mind Radio job.",
)
def cmd_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Daily Mind Radio job.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return daily_mind_radio_http.cmd_daily_mind_radio_job(job_id)


@app.api_route(
    "/commands/daily-mind-radio-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Stop Daily Mind Radio at the next bounded network-operation boundary.",
)
def cmd_cancel_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Stop Daily Mind Radio at the next bounded network-operation boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return daily_mind_radio_http.cmd_cancel_daily_mind_radio_job(job_id)


@app.api_route(
    "/commands/found-art",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a background Found Art recommendation update.",
)
async def cmd_found_art(
    client: ClientDep, count: Annotated[int, Query(ge=1)] = found_art.DEFAULT_COUNT
) -> BlastJobResult:
    """Start a background Found Art recommendation update.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        count: Validated count value.

    Returns:
        A detached view of the registered job.
    """
    return await found_art_http.cmd_found_art(client, count)


@app.api_route(
    "/commands/found-art-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Found Art jobs for web reload reconnection.",
)
def cmd_active_found_art_jobs() -> list[BlastJobResult]:
    """Return active Found Art jobs for web reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return found_art_http.cmd_active_found_art_jobs()


@app.api_route(
    "/commands/found-art-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress for one Found Art job.",
)
def cmd_found_art_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Found Art job.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return found_art_http.cmd_found_art_job(job_id)


@app.api_route(
    "/commands/fill-sauvignon-from-lastfm",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start reconnectable Last.fm album discovery for Sauvignon.",
)
async def cmd_fill_sauvignon_from_lastfm(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    seed_count: Annotated[int, Query(ge=1)] = sauvignon.DEFAULT_SEED_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start reconnectable Last.fm album discovery for Sauvignon.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        count: Validated count value.
        max_playlist_length: Validated max playlist length value.
        seed_count: Validated seed count value.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await sauvignon_http.cmd_fill_sauvignon_from_lastfm(
        client, count, max_playlist_length, seed_count, dry_run
    )


@app.api_route(
    "/commands/fill-sauvignon-from-lastfm-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Sauvignon jobs so the UI can reconnect after reload.",
)
def cmd_active_sauvignon_jobs() -> list[BlastJobResult]:
    """Return active Sauvignon jobs so the UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return sauvignon_http.cmd_active_sauvignon_jobs()


@app.api_route(
    "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return Sauvignon progress and any pending album-edition choice.",
)
def cmd_sauvignon_job(job_id: str) -> BlastJobResult:
    """Return Sauvignon progress and any pending album-edition choice.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return sauvignon_http.cmd_sauvignon_job(job_id)


@app.api_route(
    "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit one ambiguous Spotify album edition, skip, or quit choice.",
)
def cmd_choose_sauvignon_album(
    job_id: str, request: SauvignonChoiceRequest
) -> BlastJobResult:
    """Submit one ambiguous Spotify album edition, skip, or quit choice.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return sauvignon_http.cmd_choose_sauvignon_album(job_id, request)


@app.api_route(
    "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Stop Sauvignon discovery at its next safe boundary.",
)
def cmd_cancel_sauvignon_job(job_id: str) -> BlastJobResult:
    """Stop Sauvignon discovery at its next safe boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return sauvignon_http.cmd_cancel_sauvignon_job(job_id)


@app.api_route(
    "/commands/fill-queue-from-lastfm",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start reconnectable Last.fm artist discovery for The Queue.",
)
async def cmd_fill_queue_from_lastfm(
    client: InteractiveClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
    seed_count: Annotated[int, Query(ge=1)] = the_queue.DEFAULT_SEED_COUNT,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start reconnectable Last.fm artist discovery for The Queue.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        count: Validated count value.
        max_playlist_length: Validated max playlist length value.
        seed_count: Validated seed count value.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await queue_fill_http.cmd_fill_queue_from_lastfm(
        client, count, max_playlist_length, seed_count, dry_run
    )


@app.api_route(
    "/commands/fill-queue-from-lastfm-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Queue fill jobs so the UI can reconnect after reload.",
)
def cmd_active_queue_fill_jobs() -> list[BlastJobResult]:
    """Return active Queue fill jobs so the UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return queue_fill_http.cmd_active_queue_fill_jobs()


@app.api_route(
    "/commands/fill-queue-from-lastfm-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return Queue fill progress and any pending artist mapping.",
)
def cmd_queue_fill_job(job_id: str) -> BlastJobResult:
    """Return Queue fill progress and any pending artist mapping.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_fill_http.cmd_queue_fill_job(job_id)


@app.api_route(
    "/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit one Spotify artist mapping, custom search, skip, or quit.",
)
def cmd_choose_queue_artist(job_id: str, request: QueueChoiceRequest) -> BlastJobResult:
    """Submit one Spotify artist mapping, custom search, skip, or quit.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return queue_fill_http.cmd_choose_queue_artist(job_id, request)


@app.api_route(
    "/commands/fill-queue-from-lastfm-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Stop Queue artist discovery at its next safe boundary.",
)
def cmd_cancel_queue_fill_job(job_id: str) -> BlastJobResult:
    """Stop Queue artist discovery at its next safe boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_fill_http.cmd_cancel_queue_fill_job(job_id)


@app.api_route(
    "/commands/flush-queue",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a reconnectable flush of the first ten Queue artists.",
)
async def cmd_flush_queue(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reconnectable flush of the first ten Queue artists.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await queue_flush_http.cmd_flush_queue(client, dry_run)


@app.api_route(
    "/commands/flush-queue-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Queue flush jobs for page reload reconnection.",
)
def cmd_active_queue_flush_jobs() -> list[BlastJobResult]:
    """Return active Queue flush jobs for page reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return queue_flush_http.cmd_active_queue_flush_jobs()


@app.api_route(
    "/commands/flush-queue-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current Queue flush progress and result details.",
)
def cmd_queue_flush_job(job_id: str) -> BlastJobResult:
    """Return current Queue flush progress and result details.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_flush_http.cmd_queue_flush_job(job_id)


@app.api_route(
    "/commands/flush-queue-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Stop a Queue flush while preserving its durable checkpoint.",
)
def cmd_cancel_queue_flush_job(job_id: str) -> BlastJobResult:
    """Stop a Queue flush while preserving its durable checkpoint.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_flush_http.cmd_cancel_queue_flush_job(job_id)


@app.api_route(
    "/commands/flush-new-kids",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an interactive New Kids flush with reconnectable web state.",
)
async def cmd_flush_new_kids(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive New Kids flush with reconnectable web state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await discovery_http.cmd_flush_new_kids(client, dry_run)


@app.api_route(
    "/commands/flush-new-kids-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active New Kids jobs so the web UI can reconnect after reload.",
)
def cmd_active_new_kids_jobs() -> list[BlastJobResult]:
    """Return active New Kids jobs so the web UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return discovery_http.cmd_active_new_kids_jobs()


@app.api_route(
    "/commands/flush-new-kids-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress and any pending New Kids choice.",
)
def cmd_new_kids_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending New Kids choice.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return discovery_http.cmd_new_kids_job(job_id)


@app.api_route(
    "/commands/flush-new-kids-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit one release or control choice to a waiting New Kids job.",
)
def cmd_choose_new_kids_release(
    job_id: str, request: NewKidsChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Kids job.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return discovery_http.cmd_choose_new_kids_release(job_id, request)


@app.api_route(
    "/commands/flush-new-kids-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next New Kids processing boundary.",
)
def cmd_cancel_new_kids_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Kids processing boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return discovery_http.cmd_cancel_new_kids_job(job_id)


@app.api_route(
    "/commands/flush-queue-2",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an interactive Queue 2 flush with reconnectable web state.",
)
async def cmd_flush_queue_2(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Queue 2 flush with reconnectable web state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await queue_2_http.cmd_flush_queue_2(client, dry_run)


@app.api_route(
    "/commands/flush-queue-2-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Queue 2 jobs so the web UI can reconnect after reload.",
)
def cmd_active_queue_2_jobs() -> list[BlastJobResult]:
    """Return active Queue 2 jobs so the web UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return queue_2_http.cmd_active_queue_2_jobs()


@app.api_route(
    "/commands/flush-queue-2-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress and any pending Queue 2 choice.",
)
def cmd_queue_2_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 2 choice.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_2_http.cmd_queue_2_job(job_id)


@app.api_route(
    "/commands/flush-queue-2-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit one release or control choice to a waiting Queue 2 job.",
)
def cmd_choose_queue_2_release(
    job_id: str, request: NewKidsChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting Queue 2 job.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return queue_2_http.cmd_choose_queue_2_release(job_id, request)


@app.api_route(
    "/commands/flush-queue-2-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next Queue 2 processing boundary.",
)
def cmd_cancel_queue_2_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 2 processing boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_2_http.cmd_cancel_queue_2_job(job_id)


@app.api_route(
    "/commands/flush-queue-3",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an interactive Queue 3 flush with reconnectable web state.",
)
async def cmd_flush_queue_3(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Queue 3 flush with reconnectable web state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await queue_3_http.cmd_flush_queue_3(client, dry_run)


@app.api_route(
    "/commands/import-queue-3-previous-year",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start the annual Queue 3 import without advancing existing artists.",
)
async def cmd_import_queue_3_previous_year(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start the annual Queue 3 import without advancing existing artists.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await queue_3_http.cmd_import_queue_3_previous_year(client, dry_run)


@app.api_route(
    "/commands/flush-queue-3-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Queue 3 jobs so the web UI can reconnect after reload.",
)
def cmd_active_queue_3_jobs() -> list[BlastJobResult]:
    """Return active Queue 3 jobs so the web UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return queue_3_http.cmd_active_queue_3_jobs()


@app.api_route(
    "/commands/flush-queue-3-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress and any pending Queue 3 choice.",
)
def cmd_queue_3_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 3 choice.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_3_http.cmd_queue_3_job(job_id)


@app.api_route(
    "/commands/flush-queue-3-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit one release, composer-playlist, or quit choice to Queue 3.",
)
def cmd_choose_queue_3(job_id: str, request: Queue3ChoiceRequest) -> BlastJobResult:
    """Submit one release, composer-playlist, or quit choice to Queue 3.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return queue_3_http.cmd_choose_queue_3(job_id, request)


@app.api_route(
    "/commands/flush-queue-3-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next Queue 3 processing boundary.",
)
def cmd_cancel_queue_3_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 3 processing boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return queue_3_http.cmd_cancel_queue_3_job(job_id)


@app.api_route(
    "/commands/flush-new-wine",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an interactive New Wine flush with reconnectable web state.",
)
async def cmd_flush_new_wine(
    client: InteractiveClientDep,
    dry_run: bool = True,
    no_discovery: bool = False,
    choose_album_endpoints: bool = False,
) -> BlastJobResult:
    """Start an interactive New Wine flush with reconnectable web state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.
        no_discovery: Validated no discovery value.
        choose_album_endpoints: Validated choose album endpoints value.

    Returns:
        A detached view of the registered job.
    """
    return await wine_http.cmd_flush_new_wine(
        client, dry_run, no_discovery, choose_album_endpoints
    )


@app.api_route(
    "/commands/flush-new-wine-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active New Wine jobs so the web UI can reconnect after reload.",
)
def cmd_active_new_wine_jobs() -> list[BlastJobResult]:
    """Return active New Wine jobs so the web UI can reconnect after reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return wine_http.cmd_active_new_wine_jobs()


@app.api_route(
    "/commands/flush-new-wine-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress and any pending choice for one New Wine job.",
)
def cmd_new_wine_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending choice for one New Wine job.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return wine_http.cmd_new_wine_job(job_id)


@app.api_route(
    "/commands/flush-new-wine-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit one release or control choice to a waiting New Wine job.",
)
def cmd_choose_new_wine_release(
    job_id: str, request: NewWineChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Wine job.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return wine_http.cmd_choose_new_wine_release(job_id, request)


@app.api_route(
    "/commands/flush-new-wine-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next New Wine processing boundary.",
)
def cmd_cancel_new_wine_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Wine processing boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return wine_http.cmd_cancel_new_wine_job(job_id)


@app.api_route(
    "/commands/flush-slow-listening",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an interactive Slow Listening flush with reconnectable state.",
)
async def cmd_flush_slow_listening(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Slow Listening flush with reconnectable state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await slow_listening_http.cmd_flush_slow_listening(client, dry_run)


@app.api_route(
    "/commands/flush-slow-listening-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Slow Listening jobs for page-reload reconnection.",
)
def cmd_active_slow_listening_jobs() -> list[BlastJobResult]:
    """Return active Slow Listening jobs for page-reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return slow_listening_http.cmd_active_slow_listening_jobs()


@app.api_route(
    "/commands/flush-slow-listening-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current progress and the pending Slow Listening choice.",
)
def cmd_slow_listening_job(job_id: str) -> BlastJobResult:
    """Return current progress and the pending Slow Listening choice.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return slow_listening_http.cmd_slow_listening_job(job_id)


@app.api_route(
    "/commands/flush-slow-listening-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit a candidate, release order, or completion acknowledgement.",
)
def cmd_choose_slow_listening_track(
    job_id: str, request: SlowListeningChoiceRequest
) -> BlastJobResult:
    """Submit a candidate, release order, or completion acknowledgement.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return slow_listening_http.cmd_choose_slow_listening_track(job_id, request)


@app.api_route(
    "/commands/flush-slow-listening-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next Slow Listening boundary.",
)
def cmd_cancel_slow_listening_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Slow Listening boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return slow_listening_http.cmd_cancel_slow_listening_job(job_id)


@app.api_route(
    "/commands/something-old",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description=(
        "Start an interactive Something Old selection with reconnectable state."
    ),
)
async def cmd_something_old(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start an interactive Something Old selection with reconnectable state.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await something_old_http.cmd_something_old(client, dry_run)


@app.api_route(
    "/commands/something-old-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Something Old jobs for page-reload reconnection.",
)
def cmd_active_something_old_jobs() -> list[BlastJobResult]:
    """Return active Something Old jobs for page-reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return something_old_http.cmd_active_something_old_jobs()


@app.api_route(
    "/commands/something-old-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current Something Old progress and any pending choice.",
)
def cmd_something_old_job(job_id: str) -> BlastJobResult:
    """Return current Something Old progress and any pending choice.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return something_old_http.cmd_something_old_job(job_id)


@app.api_route(
    "/commands/something-old-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit an exact artist, source mode, album/EP, or quit choice.",
)
def cmd_choose_something_old(
    job_id: str, request: SomethingOldChoiceRequest
) -> BlastJobResult:
    """Submit an exact artist, source mode, album/EP, or quit choice.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return something_old_http.cmd_choose_something_old(job_id, request)


@app.api_route(
    "/commands/something-old-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next Something Old boundary.",
)
def cmd_cancel_something_old_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Something Old boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return something_old_http.cmd_cancel_something_old_job(job_id)


@app.api_route(
    "/commands/check-new-releases",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a reconnectable release check for Last.fm's top artists.",
)
async def cmd_check_new_releases(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reconnectable release check for Last.fm's top artists.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await releases_http.cmd_check_new_releases(client, dry_run)


@app.api_route(
    "/commands/check-new-releases-state",
    methods=["GET"],
    response_model=ReleaseCheckStateSnapshot,
    description=(
        "Return restart state, omitting the payload when the browser is current."
    ),
)
async def cmd_release_check_state(
    known_fingerprint: str | None = None,
) -> ReleaseCheckStateSnapshot:
    """Return restart state, omitting the payload when the browser is current.

    Args:
        known_fingerprint: Validated known fingerprint value.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await releases_http.cmd_release_check_state(known_fingerprint)


@app.api_route(
    "/commands/check-new-releases-state",
    methods=["PUT"],
    response_model=ReleaseCheckStateSnapshot,
    description=(
        "Restore a newer browser mirror without overwriting concurrent progress."
    ),
)
async def cmd_restore_release_check_state(
    request: ReleaseCheckStateRestoreRequest,
) -> ReleaseCheckStateSnapshot:
    """Restore a newer browser mirror without overwriting concurrent progress.

    Args:
        request: Validated request body.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await releases_http.cmd_restore_release_check_state(request)


@app.api_route(
    "/commands/check-new-releases-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active release checks for page-reload reconnection.",
)
def cmd_active_release_check_jobs() -> list[BlastJobResult]:
    """Return active release checks for page-reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return releases_http.cmd_active_release_check_jobs()


@app.api_route(
    "/commands/check-new-releases-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return release-check progress and any pending interaction.",
)
def cmd_release_check_job(job_id: str) -> BlastJobResult:
    """Return release-check progress and any pending interaction.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return releases_http.cmd_release_check_job(job_id)


@app.api_route(
    "/commands/check-new-releases-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit an artist mapping, custom search, or release decision.",
)
def cmd_choose_release_check(
    job_id: str, request: ReleaseCheckChoiceRequest
) -> BlastJobResult:
    """Submit an artist mapping, custom search, or release decision.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return releases_http.cmd_choose_release_check(job_id, request)


@app.api_route(
    "/commands/check-new-releases-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next release-check boundary.",
)
def cmd_cancel_release_check_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next release-check boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return releases_http.cmd_cancel_release_check_job(job_id)


@app.api_route(
    "/commands/plan-discographies",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a reload-safe interactive discography planning job.",
)
async def cmd_plan_discographies(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reload-safe interactive discography planning job.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await discography_http.cmd_plan_discographies(client, dry_run)


@app.api_route(
    "/commands/plan-discographies-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active discography jobs for page-reload reconnection.",
)
def cmd_active_discography_jobs() -> list[BlastJobResult]:
    """Return active discography jobs for page-reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return discography_http.cmd_active_discography_jobs()


@app.api_route(
    "/commands/plan-discographies-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return discography progress and its current interaction.",
)
def cmd_discography_job(job_id: str) -> BlastJobResult:
    """Return discography progress and its current interaction.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return discography_http.cmd_discography_job(job_id)


@app.api_route(
    "/commands/plan-discographies-jobs/{job_id}/choice",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Submit a release checklist or final marker-removal decision.",
)
def cmd_choose_discography(
    job_id: str, request: DiscographyChoiceRequest
) -> BlastJobResult:
    """Submit a release checklist or final marker-removal decision.

    Args:
        job_id: Identity of the reconnectable job.
        request: Validated request body.

    Returns:
        A detached view of the registered job.
    """
    return discography_http.cmd_choose_discography(job_id, request)


@app.api_route(
    "/commands/plan-discographies-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next discography boundary.",
)
def cmd_cancel_discography_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next discography boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return discography_http.cmd_cancel_discography_job(job_id)


@app.api_route(
    "/commands/flush-requeue-for-a-dream",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a reconnectable Requeue for a Dream transition.",
)
async def cmd_flush_requeue_for_a_dream(
    client: InteractiveClientDep, dry_run: bool = True
) -> BlastJobResult:
    """Start a reconnectable Requeue for a Dream transition.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.

    Returns:
        A detached view of the registered job.
    """
    return await requeue_http.cmd_flush_requeue_for_a_dream(client, dry_run)


@app.api_route(
    "/commands/flush-requeue-for-a-dream-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Requeue for a Dream jobs after a page reload.",
)
def cmd_active_requeue_for_a_dream_jobs() -> list[BlastJobResult]:
    """Return active Requeue for a Dream jobs after a page reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return requeue_http.cmd_active_requeue_for_a_dream_jobs()


@app.api_route(
    "/commands/flush-requeue-for-a-dream-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return the current state and logs for one Requeue transition.",
)
def cmd_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one Requeue transition.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return requeue_http.cmd_requeue_for_a_dream_job(job_id)


@app.api_route(
    "/commands/flush-requeue-for-a-dream-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean stop at the next API or retry boundary.",
)
def cmd_cancel_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next API or retry boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return requeue_http.cmd_cancel_requeue_for_a_dream_job(job_id)


@app.api_route(
    "/commands/fill-palace-of-memory",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a reconnectable Palace fill or cursor-only adjustment.",
)
async def cmd_fill_palace_of_memory(
    client: InteractiveClientDep,
    dry_run: bool = True,
    alphabetical_start: str | None = None,
    set_alphabetical_cursor: int | None = Query(default=None, ge=1),
) -> BlastJobResult:
    """Start a reconnectable Palace fill or cursor-only adjustment.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.
        alphabetical_start: Validated alphabetical start value.
        set_alphabetical_cursor: Validated set alphabetical cursor value.

    Returns:
        A detached view of the registered job.
    """
    return await palace_http.cmd_fill_palace_of_memory(
        client, dry_run, alphabetical_start, set_alphabetical_cursor
    )


@app.api_route(
    "/commands/fill-palace-of-memory-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active Palace jobs after a page reload.",
)
def cmd_active_palace_of_memory_jobs() -> list[BlastJobResult]:
    """Return active Palace jobs after a page reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return palace_http.cmd_active_palace_of_memory_jobs()


@app.api_route(
    "/commands/fill-palace-of-memory-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return current Palace progress, results, and logs.",
)
def cmd_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Return current Palace progress, results, and logs.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return palace_http.cmd_palace_of_memory_job(job_id)


@app.api_route(
    "/commands/fill-palace-of-memory-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean Palace stop at the next API or retry boundary.",
)
def cmd_cancel_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Request a clean Palace stop at the next API or retry boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return palace_http.cmd_cancel_palace_of_memory_job(job_id)


@app.api_route(
    "/commands/update-scrobble-history",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a background refresh of the shared Last.fm scrobble record.",
)
async def cmd_update_scrobble_history(
    dry_run: bool = True, full_rebuild: bool = False
) -> BlastJobResult:
    """Start a background refresh of the shared Last.fm scrobble record.

    Args:
        dry_run: Preview changes using the existing routine contract.
        full_rebuild: Validated full rebuild value.

    Returns:
        A detached view of the registered job.
    """
    return await history_http.cmd_update_scrobble_history(dry_run, full_rebuild)


@app.api_route(
    "/library-mirrors/status",
    methods=["GET"],
    response_model=LibraryMirrorFilesStatus,
    description="Return durable update metadata for all canonical data files.",
)
def library_mirror_files_status() -> LibraryMirrorFilesStatus:
    """Return durable update metadata for all canonical data files.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return history_http.library_mirror_files_status()


@app.api_route(
    "/commands/update-scrobble-history-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Return active history refreshes for page-reload reconnection.",
)
def cmd_active_scrobble_history_jobs() -> list[BlastJobResult]:
    """Return active history refreshes for page-reload reconnection.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return history_http.cmd_active_scrobble_history_jobs()


@app.api_route(
    "/commands/update-scrobble-history-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return the current state and logs for one history refresh.",
)
def cmd_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one history refresh.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return history_http.cmd_scrobble_history_job(job_id)


@app.api_route(
    "/commands/update-scrobble-history-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Request a clean history stop before its next persistence boundary.",
)
def cmd_cancel_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Request a clean history stop before its next persistence boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return history_http.cmd_cancel_scrobble_history_job(job_id)


@app.api_route(
    "/commands/analyse-library-async",
    methods=["POST"],
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start an export-only ``*_async`` library analysis.",
)
async def cmd_analyse_library_async() -> AnalysisJobResult:
    """Start an export-only ``*_async`` library analysis.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await analysis_http.cmd_analyse_library_async()


@app.api_route(
    "/commands/analyse-library-sync",
    methods=["POST"],
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Start a live-only ``*_sync`` library analysis.",
)
async def cmd_analyse_library_sync(client: AnalysisClientDep) -> AnalysisJobResult:
    """Start a live-only ``*_sync`` library analysis.

    Args:
        client: Authenticated client supplied by the HTTP dependency.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await analysis_http.cmd_analyse_library_sync(client)


@app.api_route(
    "/commands/refresh-library-mirrors",
    methods=["POST"],
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Refresh canonical saved-album and liked-track mirrors from Spotify.",
)
async def cmd_refresh_library_mirrors(
    client: AnalysisClientDep, full_rebuild: bool = False
) -> AnalysisJobResult:
    """Refresh canonical saved-album and liked-track mirrors from Spotify.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        full_rebuild: Validated full rebuild value.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await analysis_http.cmd_refresh_library_mirrors(client, full_rebuild)


@app.api_route(
    "/commands/refresh-library-mirrors/{resource}",
    methods=["POST"],
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
    description="Refresh one canonical Spotify mirror with independent progress.",
)
async def cmd_refresh_library_mirror_resource(
    resource: library_analysis.ResourceName,
    client: AnalysisClientDep,
    full_rebuild: bool = False,
) -> AnalysisJobResult:
    """Refresh one canonical Spotify mirror with independent progress.

    Args:
        resource: Validated resource value.
        client: Authenticated client supplied by the HTTP dependency.
        full_rebuild: Validated full rebuild value.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return await analysis_http.cmd_refresh_library_mirror_resource(
        resource, client, full_rebuild
    )


@app.api_route(
    "/commands/library-analysis-jobs",
    methods=["GET"],
    response_model=list[AnalysisJobResult],
    description="Return active analyses so the web UI can reconnect after a reload.",
)
def cmd_active_library_analysis_jobs() -> list[AnalysisJobResult]:
    """Return active analyses so the web UI can reconnect after a reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return analysis_http.cmd_active_library_analysis_jobs()


@app.api_route(
    "/commands/library-analysis-jobs/{job_id}",
    methods=["GET"],
    response_model=AnalysisJobResult,
    description="Return current progress for one library analysis job.",
)
def cmd_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Return current progress for one library analysis job.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return analysis_http.cmd_library_analysis_job(job_id)


@app.api_route(
    "/commands/library-analysis-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=AnalysisJobResult,
    description="Request a clean stop at the next durable analysis boundary.",
)
def cmd_cancel_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Request a clean stop at the next durable analysis boundary.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return analysis_http.cmd_cancel_library_analysis_job(job_id)


@app.api_route(
    "/commands/new-year",
    methods=["POST"],
    response_model=BlastJobResult,
    status_code=202,
    description=(
        "Start all New Year's Routines for the previous completed calendar year."
    ),
)
async def cmd_new_year(
    client: ClientDep, dry_run: bool = True, year: int | None = None
) -> BlastJobResult:
    """Start all New Year's Routines for the previous completed calendar year.

    Args:
        client: Authenticated client supplied by the HTTP dependency.
        dry_run: Preview changes using the existing routine contract.
        year: Validated year value.

    Returns:
        A detached view of the registered job.
    """
    return await new_year_http.cmd_new_year(client, dry_run, year)


@app.api_route(
    "/commands/new-year-jobs",
    methods=["GET"],
    response_model=list[BlastJobResult],
    description="Reconnect to an active annual workflow after browser reload.",
)
def cmd_active_new_year_jobs() -> list[BlastJobResult]:
    """Reconnect to an active annual workflow after browser reload.

    Returns:
        The named feature response in its original HTTP representation.
    """
    return new_year_http.cmd_active_new_year_jobs()


@app.api_route(
    "/commands/new-year-jobs/{job_id}",
    methods=["GET"],
    response_model=BlastJobResult,
    description="Return annual progress, rankings, and logs.",
)
def cmd_new_year_job(job_id: str) -> BlastJobResult:
    """Return annual progress, rankings, and logs.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return new_year_http.cmd_new_year_job(job_id)


@app.api_route(
    "/commands/new-year-jobs/{job_id}/cancel",
    methods=["POST"],
    response_model=BlastJobResult,
    description="Cancel at the next boundary, retaining completed annual steps.",
)
def cmd_cancel_new_year_job(job_id: str) -> BlastJobResult:
    """Cancel at the next boundary, retaining completed annual steps.

    Args:
        job_id: Identity of the reconnectable job.

    Returns:
        A detached view of the registered job.
    """
    return new_year_http.cmd_cancel_new_year_job(job_id)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API with uvicorn (entry point for the ``spotify-api`` script)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


def __getattr__(name: str) -> object:
    """Resolve historical API imports at the external compatibility edge.

    Args:
        name: Historical client, model, constant or job-helper export.

    Returns:
        The original object owned by HTTP job wiring.

    Raises:
        AttributeError: The API never exported this name.
    """
    return getattr(jobs, name)
