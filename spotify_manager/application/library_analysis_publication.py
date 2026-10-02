"""Repeatable publication of completed mirrors after accepted undo snapshots."""

from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_records import sort_resources
from spotify_manager.application.library_analysis_records import (
    stats_report_for_analysis,
)
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.application.library_analysis_values import ResourceConfig
from spotify_manager.domain.library_analysis import deduplicate_models
from spotify_manager.domain.library_analysis import resource_summary
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import LibrarySyncSummary
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import ResourceSyncSummary
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import track_sort_key


type Resources = dict[ResourceName, Sequence[LibraryModel]]


@dataclass(frozen=True)
class AnalysisPublication:
    """Bind original undo storage, permissive recovery parsing and history period.

    Args:
        analysis_backup: Original complete analysis undo boundary.
        mirror_backup: Original two-mirror undo boundary.
        resource_backup: Original independent one-resource undo boundary.
        history: Original backed-up pre-analysis history read.
        period: Original stats-history period observation.
        summaries: Original permissive manifest summary parsing.
        resource_summary: Original first-summary parsing.
        config: Original resource path/model/order selection.
    """

    analysis_backup: Callable[
        [
            LibraryAnalysisPaths,
            str,
            Resources,
            Resources,
            StatsReport,
            tuple[ResourceSyncSummary, ...],
        ],
        Path,
    ]
    mirror_backup: Callable[
        [
            LibraryAnalysisPaths,
            str,
            Resources,
            Resources,
            tuple[ResourceSyncSummary, ...],
        ],
        Path,
    ]
    resource_backup: Callable[
        [
            LibraryAnalysisPaths,
            str,
            ResourceName,
            Path,
            Sequence[LibraryModel],
            Sequence[LibraryModel],
            ResourceSyncSummary,
        ],
        Path,
    ]
    history: Callable[[LibraryAnalysisPaths, Path], dict[str, object]]
    period: Callable[[], str]
    summaries: Callable[[object], tuple[ResourceSyncSummary, ...]]
    resource_summary: Callable[[object], ResourceSyncSummary]
    config: Callable[[LibraryAnalysisPaths, ResourceName], ResourceConfig]


def finalize_analysis(
    session: AnalysisSession,
    publication: AnalysisPublication,
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
) -> LibrarySyncSummary:
    """Publish full analysis in original album, track, artist, history order.

    Args:
        session: Original analysis invocation.
        publication: Original undo and recovery boundaries.
        albums: Original accepted staged albums.
        tracks: Original accepted staged tracks.
        artists: Original accepted staged artists.

    Returns:
        Original complete analysis outcome.
    """
    albums, tracks, artists = sort_resources(albums, tracks, artists)
    current: Resources = {"albums": albums, "tracks": tracks, "artists": artists}
    backup_dir, report, summaries = _analysis_backup(session, publication, current)
    session.files.publish(session.paths.albums_total, albums)
    session.files.publish(session.paths.liked_tracks_total, tracks)
    session.files.publish(session.paths.artists_total, artists)
    history = publication.history(session.paths, backup_dir)
    history[publication.period()] = report.model_dump()
    session.files.write(session.paths.stats_history, history)
    return complete_publication(session, backup_dir, summaries)


def _analysis_backup(
    session: AnalysisSession, publication: AnalysisPublication, current: Resources
) -> tuple[Path, StatsReport, tuple[ResourceSyncSummary, ...]]:
    if session.checkpoint["status"] == "finalizing":
        backup_dir, manifest = _resume_manifest(
            session, "The analysis backup manifest is invalid."
        )
        report = StatsReport.model_validate(manifest["stats_report"])
        return backup_dir, report, publication.summaries(manifest["summaries"])
    paths = session.paths
    albums = session.files.models(paths.albums_total, YourLibraryAlbum)
    tracks = session.files.models(paths.liked_tracks_total, YourLibraryTrack)
    artists = session.files.models(paths.artists_total, YourLibraryArtist)
    previous: Resources = {"albums": albums, "tracks": tracks, "artists": artists}
    report = stats_report_for_analysis(
        albums,
        cast(list[YourLibraryAlbum], current["albums"]),
        tracks,
        cast(list[YourLibraryTrack], current["tracks"]),
        artists,
        cast(list[YourLibraryArtist], current["artists"]),
    )
    source = "YourLibrary.json" if paths.mode == "async" else "live_api"
    summaries = _summaries(
        session, previous, current, source, ("albums", "tracks", "artists")
    )
    backup_dir = publication.analysis_backup(
        paths, str(session.checkpoint["run_id"]), previous, current, report, summaries
    )
    _begin_publication(session, backup_dir)
    return backup_dir, report, summaries


def _summaries(
    session: AnalysisSession,
    previous: Resources,
    current: Resources,
    source: str,
    resources: tuple[ResourceName, ...],
) -> tuple[ResourceSyncSummary, ...]:
    summaries: list[ResourceSyncSummary] = []
    for resource in resources:
        skipped = int(session.checkpoint["resources"][resource].get("skipped", 0))
        summaries.append(
            resource_summary(
                resource, source, previous[resource], current[resource], skipped
            )
        )
    return tuple(summaries)


def _begin_publication(session: AnalysisSession, backup_dir: Path) -> None:
    session.checkpoint["status"] = "finalizing"
    session.checkpoint["backup_dir"] = str(backup_dir)
    session.save()


def _resume_manifest(
    session: AnalysisSession, error: str
) -> tuple[Path, dict[str, object]]:
    backup_dir = Path(str(session.checkpoint["backup_dir"]))
    manifest = session.files.read(backup_dir / "manifest.json")
    if not isinstance(manifest, dict):
        raise LibrarySyncError(error)
    return backup_dir, cast(dict[str, object], manifest)


def finalize_mirrors(
    session: AnalysisSession,
    publication: AnalysisPublication,
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
) -> LibrarySyncSummary:
    """Publish only the original canonical album and track outputs.

    Args:
        session: Original canonical mirror invocation.
        publication: Original undo and recovery boundaries.
        albums: Original accepted staged albums.
        tracks: Original accepted staged tracks.

    Returns:
        Original complete two-resource outcome.
    """
    albums = sorted(deduplicate_models(albums), key=album_sort_key)
    tracks = sorted(deduplicate_models(tracks), key=track_sort_key)
    current: Resources = {"albums": albums, "tracks": tracks}
    backup_dir, summaries = _mirror_backup(session, publication, current)
    session.files.publish(session.paths.albums_total, albums)
    session.files.publish(session.paths.liked_tracks_total, tracks)
    return complete_publication(session, backup_dir, summaries)


def _mirror_backup(
    session: AnalysisSession, publication: AnalysisPublication, current: Resources
) -> tuple[Path, tuple[ResourceSyncSummary, ...]]:
    if session.checkpoint["status"] == "finalizing":
        backup_dir, manifest = _resume_manifest(
            session, "The live-mirror backup manifest is invalid."
        )
        return backup_dir, publication.summaries(manifest["summaries"])
    previous: Resources = {
        "albums": session.files.models(session.paths.albums_total, YourLibraryAlbum),
        "tracks": session.files.models(
            session.paths.liked_tracks_total, YourLibraryTrack
        ),
    }
    summaries = _summaries(session, previous, current, "live_api", ("albums", "tracks"))
    backup_dir = publication.mirror_backup(
        session.paths, str(session.checkpoint["run_id"]), previous, current, summaries
    )
    _begin_publication(session, backup_dir)
    return backup_dir, summaries


def finalize_resource(
    session: AnalysisSession,
    publication: AnalysisPublication,
    resource: ResourceName,
    models: list[LibraryModel],
) -> LibrarySyncSummary:
    """Publish exactly one requested canonical mirror after its undo snapshot.

    Args:
        session: Original independent resource invocation.
        publication: Original undo and recovery boundaries.
        resource: Original requested resource identity.
        models: Original complete accepted staging models.

    Returns:
        Original one-resource analysis outcome.
    """
    target, model_type, sort_key = publication.config(session.paths, resource)
    current = sorted(deduplicate_models(models), key=sort_key)
    backup_dir, summary = _resource_backup(
        session, publication, resource, target, model_type, current
    )
    session.files.publish(target, current)
    return complete_publication(session, backup_dir, (summary,))


def _resource_backup(
    session: AnalysisSession,
    publication: AnalysisPublication,
    resource: ResourceName,
    target: Path,
    model_type: type[LibraryModel],
    current: list[LibraryModel],
) -> tuple[Path, ResourceSyncSummary]:
    if session.checkpoint["status"] == "finalizing":
        backup_dir, manifest = _resume_manifest(
            session, "The live-mirror backup manifest is invalid."
        )
        return backup_dir, publication.resource_summary(manifest["summaries"])
    previous = session.files.models(target, model_type)
    state = session.checkpoint["resources"][resource]
    source = str(state.get("source") or "live_api")
    summary = resource_summary(
        resource, source, previous, current, int(state.get("skipped", 0))
    )
    backup_dir = publication.resource_backup(
        session.paths,
        str(session.checkpoint["run_id"]),
        resource,
        target,
        previous,
        current,
        summary,
    )
    _begin_publication(session, backup_dir)
    return backup_dir, summary


def complete_publication(
    session: AnalysisSession,
    backup_dir: Path,
    summaries: tuple[ResourceSyncSummary, ...],
) -> LibrarySyncSummary:
    """Accept original completion after all requested outputs are published.

    Args:
        session: Original analysis invocation.
        backup_dir: Original accepted undo snapshot.
        summaries: Original ordered resource outcomes.

    Returns:
        Original completed analysis result.
    """
    session.checkpoint["status"] = "complete"
    session.checkpoint["completed_at"] = session.files.clock()
    session.save()
    session.event(
        "run_completed",
        backup_dir=str(backup_dir),
        summaries=[asdict(summary) for summary in summaries],
    )
    return LibrarySyncSummary(
        str(session.checkpoint["run_id"]),
        session.paths.mode,
        str(backup_dir),
        summaries,
    )
