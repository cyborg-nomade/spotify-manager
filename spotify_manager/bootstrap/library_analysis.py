"""Bind original file seams and synchronous Spotify reads for library analysis."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep
from typing import cast

from spotipy import Spotify

from spotify_manager.application.library_analysis_effects import AnalysisCatalog
from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_effects import OffsetRead
from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.application.library_analysis_values import CancelCheck
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import Echo
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import ProgressCallback
from spotify_manager.application.library_analysis_values import Sleep
from spotify_manager.application.library_analysis_values import resource_config
from spotify_manager.bootstrap.library_data import publish_managed_path
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import RetryWait
from spotify_manager.infrastructure import library_analysis_backups as backups
from spotify_manager.infrastructure import library_analysis_files as files
from spotify_manager.infrastructure.library_analysis_retry import LibraryRetry
from spotify_manager.infrastructure.library_models import album_from_saved_item
from spotify_manager.infrastructure.library_records import current_stats_history_key


@dataclass(frozen=True)
class AnalysisResources:
    """Own caller-supplied synchronous resources and original retry configuration.

    Args:
        spotify: Original caller-owned client or none for offline preparation.
        paths: Original independent output family.
        checkpoint: Original mutable progress mapping.
        echo: Original presenter.
        retry_wait: Original optional interactive retry decision.
        sleep: Original blocking wait.
        retry_base_seconds: Original initial transient delay.
        retry_max_seconds: Original capped transient delay.
    """

    spotify: Spotify | None
    paths: LibraryAnalysisPaths
    checkpoint: Checkpoint
    echo: Echo
    retry_wait: RetryWait | None
    sleep: Sleep
    retry_base_seconds: int
    retry_max_seconds: int

    def retry[T](
        self,
        operation: Callable[[], T],
        description: str,
        max_attempts: int | None = None,
    ) -> T:
        """Preserve the original public retry seam for every live operation.

        Args:
            operation: Original selected live request.
            description: Original visible label.
            max_attempts: Original optional bounded retry count.

        Returns:
            Original accepted response.
        """
        retry = LibraryRetry(
            self.paths,
            self.checkpoint,
            analysis_files(),
            self.echo,
            self.retry_wait,
            self.sleep,
            self.retry_base_seconds,
            self.retry_max_seconds,
        )
        return retry.call(operation, description, max_attempts)

    def offset(self, resource: ResourceName, initial: bool) -> OffsetRead:
        """Select the original method at its original durable scan boundary.

        Args:
            resource: Original saved-resource identity.
            initial: Whether this is the initial monotonic scan.

        Returns:
            Original selected caller-owned method.
        """
        from spotify_manager.routines.analyse_library import _initial_offset_reader
        from spotify_manager.routines.analyse_library import _reconcile_offset_reader

        spotify = cast(Spotify, self.spotify)
        if initial:
            return cast(OffsetRead, _initial_offset_reader(spotify, resource))
        return cast(OffsetRead, _reconcile_offset_reader(spotify, resource))

    def artists(self, after: str | None) -> object:
        """Read the original cursor scan with immediate endpoint fallback.

        Args:
            after: Original stored cursor or none.

        Returns:
            Original unvalidated cursor page.
        """
        from spotify_manager.routines.analyse_library import fetch_followed_artists_page

        return fetch_followed_artists_page(cast(Spotify, self.spotify), after)

    def reconcile_artists(self, after: str | None) -> object:
        """Read the original reconciliation cursor page.

        Args:
            after: Original current pass cursor or none.

        Returns:
            Original unvalidated cursor page.
        """
        from spotify_manager.routines.analyse_library import _reconcile_artist_page

        return _reconcile_artist_page(cast(Spotify, self.spotify), after)

    def following(self, identities: list[str]) -> object:
        """Read original complete live follow verification facts.

        Args:
            identities: Original ordered candidate batch.

        Returns:
            Original unvalidated follow statuses.
        """
        from spotify_manager.routines.analyse_library import _following_artists

        return _following_artists(cast(Spotify, self.spotify), identities)


def analysis_files() -> AnalysisFiles:
    """Bind original public file, audit and clock compatibility seams.

    Returns:
        Invocation dependencies preserving caller substitutions.
    """
    return AnalysisFiles(
        files.load_json,
        files.write_json_atomic,
        partial(files.load_model_list, read=files.load_json),
        files.load_models_jsonl,
        partial(files.write_models, write=files.write_json_atomic, publish=_publish),
        files.append_models_jsonl,
        partial(files.append_event, _utc_now),
        partial(files.load_your_library, read=files.load_json),
        _utc_now,
        _run_id,
        files.export_fingerprint,
        files.reset_staging,
        files.remove,
        partial(
            files.latest_export_artists,
            load=partial(files.load_your_library, read=files.load_json),
        ),
    )


def analysis_publication() -> AnalysisPublication:
    """Bind original undo, recovery and history-period compatibility seams.

    Returns:
        Complete ordered publication boundaries for an analysis invocation.
    """
    return AnalysisPublication(
        partial(backups.create_backup_manifest, files=analysis_files()),
        partial(backups.create_live_mirror_backup_manifest, files=analysis_files()),
        partial(backups.create_resource_backup, files=analysis_files()),
        partial(backups.pre_analysis_stats_history, files=analysis_files()),
        current_stats_history_key,
        backups.manifest_summaries,
        backups.resource_manifest_summary,
        resource_config,
    )


def analysis_session(
    paths: LibraryAnalysisPaths,
    checkpoint: Checkpoint,
    spotify: Spotify | None = None,
    echo: Echo = print,
    progress: ProgressCallback | None = None,
    retry_wait: RetryWait | None = None,
    cancel_check: CancelCheck | None = None,
    sleep: Sleep = default_sleep,
    retry_base_seconds: int = 10,
    retry_max_seconds: int = 1800,
) -> AnalysisSession:
    """Bind one original public invocation to independently injected stages.

    Args:
        paths: Original output family.
        checkpoint: Original mutable progress.
        spotify: Original caller-owned live client.
        echo: Original presenter.
        progress: Original resource-level progress.
        retry_wait: Original interactive retry decision.
        cancel_check: Original durable cancellation observation.
        sleep: Original blocking retry wait.
        retry_base_seconds: Original first transient delay.
        retry_max_seconds: Original maximum transient delay.

    Returns:
        Complete application session with no singleton resolution in inner code.
    """
    resources = AnalysisResources(
        spotify,
        paths,
        checkpoint,
        echo,
        retry_wait,
        sleep,
        retry_base_seconds,
        retry_max_seconds,
    )
    catalog = AnalysisCatalog(
        resources.offset,
        resources.artists,
        resources.reconcile_artists,
        resources.following,
        album_from_saved_item,
        files.track_from_saved_item,
        files.artist_from_api_item,
        files.page_items,
        files.followed_artist_page_items,
    )
    return AnalysisSession(
        paths,
        checkpoint,
        analysis_files(),
        catalog,
        resources.retry,
        echo,
        progress,
        cancel_check,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _publish(path: Path, source: str) -> None:
    publish_managed_path(path, source=source)
