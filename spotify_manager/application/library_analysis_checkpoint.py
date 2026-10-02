"""Original permissive checkpoint compatibility, fresh identities and resumption."""

from typing import cast

from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import ResourceState
from spotify_manager.domain.library_analysis_values import MirrorRefreshMode


def pending_resource() -> ResourceState:
    """Create the original ordered pending-resource fields.

    Returns:
        Original fresh resource progress mapping.
    """
    return {
        "status": "pending",
        "offset": 0,
        "after": None,
        "total": None,
        "pages": 0,
        "skipped": 0,
        "stable_passes": 0,
    }


def new_checkpoint(
    files: AnalysisFiles,
    paths: LibraryAnalysisPaths,
    mirror_refresh_mode: MirrorRefreshMode | None = None,
) -> Checkpoint:
    """Observe original clocks before adding mode-specific source compatibility.

    Args:
        files: Original file and clock boundaries.
        paths: Original independent output family.
        mirror_refresh_mode: Original optional rebuild choice.

    Returns:
        Original ordered fresh checkpoint mapping.
    """
    checkpoint: Checkpoint = {
        "version": 1,
        "mode": paths.mode,
        "run_id": files.run_id(),
        "status": "running",
        "created_at": files.clock(),
        "resources": {},
    }
    for resource in ("albums", "tracks", "artists"):
        checkpoint["resources"][resource] = pending_resource()
    if paths.mode == "async":
        checkpoint["export_fingerprint"] = files.fingerprint(paths.your_library)
    if paths.mode == "mirrors":
        checkpoint["mirror_refresh_mode"] = mirror_refresh_mode or "incremental"
    return checkpoint


def load_or_create_checkpoint(
    files: AnalysisFiles,
    paths: LibraryAnalysisPaths,
    mirror_refresh_mode: MirrorRefreshMode | None = None,
) -> Checkpoint:
    """Resume the same original shallow-compatible mapping, retaining unknown fields.

    Args:
        files: Original file and clock boundaries.
        paths: Original independent output family.
        mirror_refresh_mode: Original optional rebuild choice.

    Returns:
        Original accepted resumable or fresh checkpoint.
    """
    raw = files.read(paths.checkpoint)
    if _compatible(files, paths, raw, mirror_refresh_mode):
        checkpoint = cast(Checkpoint, raw)
        files.event(paths, str(checkpoint["run_id"]), "run_resumed")
        return checkpoint
    files.reset_staging(paths.staging_dir)
    checkpoint = new_checkpoint(files, paths, mirror_refresh_mode)
    files.write(paths.checkpoint, checkpoint)
    files.event(paths, str(checkpoint["run_id"]), "run_started")
    return checkpoint


def _compatible(
    files: AnalysisFiles,
    paths: LibraryAnalysisPaths,
    raw: object,
    refresh: MirrorRefreshMode | None,
) -> bool:
    if not isinstance(raw, dict):
        return False
    compatible = raw.get("version") == 1 and raw.get("mode") == paths.mode
    compatible = compatible and raw.get("status") != "complete"
    if compatible and paths.mode == "async":
        compatible = raw.get("export_fingerprint") == files.fingerprint(
            paths.your_library
        )
    if compatible and paths.mode == "mirrors":
        compatible = raw.get("mirror_refresh_mode") == (refresh or "incremental")
    return compatible
