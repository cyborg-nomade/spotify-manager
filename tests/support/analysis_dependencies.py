"""Inject observed file operations into the explicit analysis dependency ports."""

from functools import partial

from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.infrastructure import library_analysis_backups as backups
from spotify_manager.infrastructure import library_analysis_files as files
from spotify_manager.routines import analyse_library as legacy


def observed_analysis_files() -> AnalysisFiles:
    """Bind original public file, audit and clock compatibility seams.

    Returns:
        Invocation dependencies preserving caller substitutions.
    """
    return AnalysisFiles(
        legacy.load_json,
        legacy.write_json_atomic,
        legacy.load_model_list,
        legacy.load_models_jsonl,
        legacy.write_models,
        legacy.append_models_jsonl,
        legacy.append_event,
        legacy.load_your_library,
        legacy.utc_now,
        legacy.new_run_id,
        legacy.export_fingerprint,
        files.reset_staging,
        files.remove,
        legacy.latest_export_artists,
    )


def observed_analysis_publication() -> AnalysisPublication:
    """Bind original undo, recovery and history-period compatibility seams.

    Returns:
        Complete ordered publication boundaries for an analysis invocation.
    """
    return AnalysisPublication(
        legacy.create_backup_manifest,
        legacy.create_live_mirror_backup_manifest,
        partial(backups.create_resource_backup, files=observed_analysis_files()),
        legacy.pre_analysis_stats_history,
        legacy.current_stats_history_key,
        backups.manifest_summaries,
        backups.resource_manifest_summary,
        legacy._live_resource_config,
    )
