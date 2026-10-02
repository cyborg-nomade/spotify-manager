"""Original analysis undo selection and ordered managed-file restoration."""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.domain.library_analysis_values import LibrarySyncRestoreError
from spotify_manager.infrastructure.library_analysis_backups import backup_targets


def restore_library_sync(
    run_id: str,
    candidates: list[LibraryAnalysisPaths],
    files: AnalysisFiles,
    publish: Callable[[Path, str], None],
) -> tuple[str, ...]:
    """Restore original known targets from the first matching original backup family.

    Args:
        run_id: Original requested sortable run identity.
        candidates: Original ordered explicit or conventional output families.
        files: Original JSON and audit boundaries.
        publish: Original accepted managed-file publication boundary.

    Returns:
        Original restored target filenames in manifest encounter order.

    Raises:
        LibrarySyncRestoreError: Original run id, manifest or backup is unusable.
    """
    if not run_id or any(part in run_id for part in ("/", "\\", "..")):
        raise LibrarySyncRestoreError("Invalid library-analysis run id.")
    paths, backup_dir, manifest = _find_backup(run_id, candidates, files)
    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        raise LibrarySyncRestoreError("The backup manifest has no target list.")
    current_targets = backup_targets(paths)
    restored: list[str] = []
    for name, details in targets.items():
        if name not in current_targets or not isinstance(details, dict):
            continue
        target = current_targets[name]
        _restore_target(run_id, backup_dir, target, details, publish)
        restored.append(target.name)
    files.event(paths, run_id, "run_restored", restored_files=restored)
    return tuple(restored)


def _find_backup(
    run_id: str,
    candidates: list[LibraryAnalysisPaths],
    files: AnalysisFiles,
) -> tuple[LibraryAnalysisPaths, Path, dict[str, object]]:
    for paths in candidates:
        possible_dir = paths.backups_dir / run_id
        raw = files.read(possible_dir / "manifest.json")
        if isinstance(raw, dict) and raw.get("run_id") == run_id:
            return paths, possible_dir, cast(dict[str, object], raw)
    raise LibrarySyncRestoreError(f"No valid backup found for run {run_id}.")


def _restore_target(
    run_id: str,
    backup_dir: Path,
    target: Path,
    details: dict[str, object],
    publish: Callable[[Path, str], None],
) -> None:
    if not details.get("existed"):
        target.unlink(missing_ok=True)
        return
    backup_file = backup_dir / str(details["backup_file"])
    if not backup_file.exists():
        raise LibrarySyncRestoreError(f"Backup file missing for {target.name}.")
    temporary = target.with_suffix(f"{target.suffix}.restore")
    shutil.copy2(backup_file, temporary)
    temporary.replace(target)
    publish(target, f"restore analysis {run_id}")
