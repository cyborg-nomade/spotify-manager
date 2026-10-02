"""Complete export/live analyses and independent canonical resource refreshes."""

from typing import cast

from spotify_manager.application import library_analysis_artists as artists
from spotify_manager.application import library_analysis_offsets as offsets
from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_export import prepare_export_resource
from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.application.library_analysis_publication import finalize_analysis
from spotify_manager.application.library_analysis_publication import finalize_mirrors
from spotify_manager.application.library_analysis_publication import finalize_resource
from spotify_manager.domain.library_analysis_values import LibrarySyncSummary
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import (
    _FollowedArtistsEndpointUnavailableError,
)
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key
from spotify_manager.utils.sorting import track_sort_key


def analyse_export(
    session: AnalysisSession, publication: AnalysisPublication
) -> LibrarySyncSummary:
    """Build original offline export mirrors without reading the live library.

    Args:
        session: Original independent export analysis invocation.
        publication: Original ordered output and undo boundaries.

    Returns:
        Original completed export analysis outcome.
    """
    if session.checkpoint["status"] == "finalizing":
        paths = session.paths
        albums = session.files.models(paths.stage("albums"), YourLibraryAlbum)
        tracks = session.files.models(paths.stage("tracks"), YourLibraryTrack)
        followed = session.files.models(paths.stage("artists"), YourLibraryArtist)
        return finalize_analysis(session, publication, albums, tracks, followed)
    library = session.files.export(session.paths)
    albums = prepare_export_resource(
        session, "albums", library.albums, YourLibraryAlbum, album_sort_key
    )
    tracks = prepare_export_resource(
        session, "tracks", library.tracks, YourLibraryTrack, track_sort_key
    )
    followed = prepare_export_resource(
        session, "artists", library.artists, YourLibraryArtist, artist_sort_key
    )
    return finalize_analysis(session, publication, albums, tracks, followed)


def analyse_live(
    session: AnalysisSession, publication: AnalysisPublication
) -> LibrarySyncSummary:
    """Gather original complete live-only sources before publishing sync mirrors.

    Args:
        session: Original independent live analysis invocation.
        publication: Original ordered output and undo boundaries.

    Returns:
        Original completed live-only analysis outcome.
    """
    if session.checkpoint["status"] != "finalizing":
        for resource in ("albums", "tracks"):
            refresh_offset(session, resource, True)
        artists.scan_initial(session)
        artists.reconcile(session)
    paths = session.paths
    albums = session.files.staged(paths.stage("albums"), YourLibraryAlbum)
    tracks = session.files.staged(paths.stage("tracks"), YourLibraryTrack)
    followed = session.files.staged(paths.stage("artists"), YourLibraryArtist)
    return finalize_analysis(session, publication, albums, tracks, followed)


def refresh_offset(
    session: AnalysisSession, resource: offsets.OffsetResource, full: bool
) -> None:
    """Select original full-scan or incremental-seed behavior before reconciliation.

    Args:
        session: Original live analysis invocation.
        resource: Original saved-resource identity.
        full: Original explicit full rebuild choice.
    """
    if full:
        offsets.scan_initial(session, resource)
    else:
        offsets.seed_incremental(session, resource)
    offsets.reconcile(session, resource)


def refresh_mirrors(
    session: AnalysisSession, publication: AnalysisPublication, full: bool
) -> LibrarySyncSummary:
    """Refresh original canonical albums and tracks without publishing other files.

    Args:
        session: Original canonical mirror invocation.
        publication: Original ordered output and undo boundaries.
        full: Original explicit full rebuild choice.

    Returns:
        Original completed two-mirror outcome.
    """
    if session.checkpoint["status"] != "finalizing":
        for resource in ("albums", "tracks"):
            refresh_offset(session, resource, full)
    albums = session.files.staged(session.paths.stage("albums"), YourLibraryAlbum)
    tracks = session.files.staged(session.paths.stage("tracks"), YourLibraryTrack)
    return finalize_mirrors(session, publication, albums, tracks)


def refresh_resource(
    session: AnalysisSession,
    publication: AnalysisPublication,
    resource: ResourceName,
    full: bool,
) -> LibrarySyncSummary:
    """Refresh exactly the original requested canonical resource and workspace.

    Args:
        session: Original independently scoped resource invocation.
        publication: Original ordered output and undo boundaries.
        resource: Original requested resource identity.
        full: Original explicit full rebuild choice.

    Returns:
        Original completed one-resource outcome.
    """
    if session.checkpoint["status"] == "finalizing":
        _target, model_type, _sort_key = publication.config(session.paths, resource)
    else:
        model_type = _refresh_resource(session, resource, full)
    models = session.files.staged(session.paths.stage(resource), model_type)
    return finalize_resource(session, publication, resource, models)


def _refresh_resource(
    session: AnalysisSession, resource: ResourceName, full: bool
) -> type[YourLibraryAlbum | YourLibraryTrack | YourLibraryArtist]:
    if resource in {"albums", "tracks"}:
        refresh_offset(session, cast(offsets.OffsetResource, resource), full)
        return YourLibraryAlbum if resource == "albums" else YourLibraryTrack
    _refresh_artists(session, full)
    return YourLibraryArtist


def _refresh_artists(session: AnalysisSession, full: bool) -> None:
    if not full:
        artists.prepare_verification(
            session,
            full_rebuild=False,
            reason="using the fast incremental candidate refresh",
        )
        artists.verify(session)
        return
    state = session.checkpoint["resources"]["artists"]
    if state["status"] != "verifying_fallback":
        _discover_artists(session)
    if state["status"] == "verifying_fallback":
        artists.verify(session)
        return
    artists.reconcile(session)


def _discover_artists(session: AnalysisSession) -> None:
    try:
        artists.scan_initial(session)
    except _FollowedArtistsEndpointUnavailableError as exc:
        artists.prepare_verification(session, full_rebuild=True, reason=str(exc))
