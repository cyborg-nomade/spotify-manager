"""Original undo snapshots, manifest bytes and repeatable backed-up history reads."""

import shutil
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any
from typing import cast

from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.domain.library_analysis import model_diff
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import ResourceSyncSummary
from spotify_manager.models.stats import StatsReport


type Resources = dict[ResourceName, Sequence[LibraryModel]]


def backup_targets(paths: LibraryAnalysisPaths) -> dict[str, Path]:
    """Locate every original generated output affected by complete analysis.

    Args:
        paths: Original independent output family.

    Returns:
        Original ordered four-target mapping.
    """
    return {
        "albums": paths.albums_total,
        "tracks": paths.liked_tracks_total,
        "artists": paths.artists_total,
        "stats_history": paths.stats_history,
    }


def _snapshot_target(target: Path, backup_dir: Path, name: str) -> dict[str, object]:
    backup_name = f"{name}.before.json"
    existed = target.exists()
    if existed:
        shutil.copy2(target, backup_dir / backup_name)
    return {
        "target_name": target.name,
        "existed": existed,
        "backup_file": backup_name if existed else None,
    }


def _changes(
    previous: Sequence[LibraryModel], current: Sequence[LibraryModel]
) -> dict[str, object]:
    added, removed = model_diff(previous, current)
    return {
        "added": [item.model_dump() for item in added],
        "removed": [item.model_dump() for item in removed],
    }


def create_backup_manifest(
    paths: LibraryAnalysisPaths,
    run_id: str,
    previous: Resources,
    current: Resources,
    report: StatsReport,
    summaries: tuple[ResourceSyncSummary, ...],
    files: AnalysisFiles,
) -> Path:
    """Copy all original outputs before recording complete analysis differences.

    Args:
        paths: Original output family.
        run_id: Original sortable run identity.
        previous: Original complete pre-analysis models.
        current: Original sorted post-analysis models.
        report: Original complete analysis counts.
        summaries: Original ordered resource outcomes.
        files: Original file, clock and audit boundaries.

    Returns:
        Original accepted backup directory.
    """
    backup_dir = paths.backups_dir / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    targets: dict[str, dict[str, object]] = {}
    for name, target in backup_targets(paths).items():
        targets[name] = _snapshot_target(target, backup_dir, name)
    changes: dict[str, object] = {}
    names: tuple[ResourceName, ...] = ("albums", "tracks", "artists")
    for resource in names:
        changes[resource] = _changes(previous[resource], current[resource])
    manifest = {
        "version": 1,
        "run_id": run_id,
        "mode": paths.mode,
        "created_at": files.clock(),
        "targets": targets,
        "changes": changes,
        "stats_report": report.model_dump(),
        "summaries": [asdict(summary) for summary in summaries],
    }
    files.write(backup_dir / "manifest.json", manifest)
    files.event(paths, run_id, "backup_created", backup_dir=str(backup_dir))
    return backup_dir


def create_live_mirror_backup_manifest(
    paths: LibraryAnalysisPaths,
    run_id: str,
    previous: Resources,
    current: Resources,
    summaries: tuple[ResourceSyncSummary, ...],
    files: AnalysisFiles,
) -> Path:
    """Preserve original interleaved album/track copies and difference recording.

    Args:
        paths: Original canonical mirror output family.
        run_id: Original sortable run identity.
        previous: Original pre-refresh models.
        current: Original post-refresh models.
        summaries: Original ordered resource outcomes.
        files: Original file, clock and audit boundaries.

    Returns:
        Original accepted backup directory.
    """
    backup_dir = paths.backups_dir / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    targets: dict[str, dict[str, object]] = {}
    changes: dict[str, object] = {}
    names: tuple[ResourceName, ...] = ("albums", "tracks")
    for resource in names:
        target = backup_targets(paths)[resource]
        targets[resource] = _snapshot_target(target, backup_dir, resource)
        changes[resource] = _changes(previous[resource], current[resource])
    manifest = {
        "version": 1,
        "run_id": run_id,
        "mode": paths.mode,
        "created_at": files.clock(),
        "targets": targets,
        "changes": changes,
        "summaries": [asdict(summary) for summary in summaries],
    }
    files.write(backup_dir / "manifest.json", manifest)
    files.event(paths, run_id, "backup_created", backup_dir=str(backup_dir))
    return backup_dir


def create_resource_backup(
    paths: LibraryAnalysisPaths,
    run_id: str,
    resource: ResourceName,
    target: Path,
    previous: Sequence[LibraryModel],
    current: Sequence[LibraryModel],
    summary: ResourceSyncSummary,
    files: AnalysisFiles,
) -> Path:
    """Copy only the original requested canonical resource before publication.

    Args:
        paths: Original independent resource workspace.
        run_id: Original sortable run identity.
        resource: Original requested resource.
        target: Original canonical mirror location.
        previous: Original pre-refresh models.
        current: Original post-refresh models.
        summary: Original resource outcome.
        files: Original file, clock and audit boundaries.

    Returns:
        Original accepted backup directory.
    """
    backup_dir = paths.backups_dir / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    target_details = _snapshot_target(target, backup_dir, resource)
    added, removed = model_diff(previous, current)
    manifest = {
        "version": 1,
        "run_id": run_id,
        "mode": paths.mode,
        "created_at": files.clock(),
        "targets": {resource: target_details},
        "changes": {
            resource: {
                "added": [item.model_dump() for item in added],
                "removed": [item.model_dump() for item in removed],
            }
        },
        "summaries": [asdict(summary)],
    }
    files.write(backup_dir / "manifest.json", manifest)
    files.event(
        paths, run_id, "backup_created", backup_dir=str(backup_dir), resource=resource
    )
    return backup_dir


def pre_analysis_stats_history(
    paths: LibraryAnalysisPaths, backup_dir: Path, files: AnalysisFiles
) -> dict[str, object]:
    """Read original history from the backup so partial publication remains repeatable.

    Args:
        paths: Original independent output family.
        backup_dir: Original accepted backup location.
        files: Original file, clock and audit boundaries.

    Returns:
        Original unmodified pre-analysis history.

    Raises:
        LibrarySyncError: Original manifest or backed-up history is not an object.
    """
    manifest = files.read(backup_dir / "manifest.json")
    if not isinstance(manifest, dict):
        raise LibrarySyncError("The analysis backup manifest is invalid.")
    target = manifest["targets"]["stats_history"]
    if not target["existed"]:
        return {}
    raw = files.read(backup_dir / str(target["backup_file"]), default={})
    if not isinstance(raw, dict):
        raise LibrarySyncError("The backed-up stats history is invalid.")
    return cast(dict[str, object], raw)


def manifest_summaries(raw: object) -> tuple[ResourceSyncSummary, ...]:
    """Use the original permissive constructor at the unvalidated manifest boundary.

    Args:
        raw: Original unvalidated manifest summary array.

    Returns:
        Original ordered resource summaries.

    Raises:
        TypeError: Original native constructor or iteration rejects malformed input.
    """
    # Any is confined to the original permissive external constructor boundary.
    items = cast(list[dict[str, Any]], raw)
    return tuple(ResourceSyncSummary(**item) for item in items)


def resource_manifest_summary(raw: object) -> ResourceSyncSummary:
    """Preserve original first-summary indexing and permissive construction.

    Args:
        raw: Original unvalidated manifest summary array.

    Returns:
        Original first recorded resource outcome.

    Raises:
        IndexError: The original summary array is empty.
        TypeError: Original native indexing or construction rejects malformed input.
    """
    items = cast(list[dict[str, Any]], raw)
    return ResourceSyncSummary(**items[0])
