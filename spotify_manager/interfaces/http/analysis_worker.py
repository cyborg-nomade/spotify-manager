"""Feature-owned analysis callbacks and presentation for threaded execution."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from threading import Lock
from typing import cast

from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import AnalysisJob
from spotify_manager.interfaces.operations import analyse_library as analysis


type EventCallback = Callable[[str], None]
type EventSetter = Callable[[EventCallback | None], EventCallback | None]


def spotify_event_setter(spotify: Spotify | None) -> EventSetter | None:
    """Observe the optional original SDK event hook at its external boundary.

    Args:
        spotify: Existing caller-owned SDK client, or none for export analysis.

    Returns:
        The original callable hook, without acquiring or rebuilding a client.
    """
    setter = getattr(spotify, "set_event_callback", None)
    if not callable(setter):
        return None
    return cast(EventSetter, setter)


@dataclass
class AnalysisWorker:
    """Own one job's callbacks without local functions or duplicated state.

    Args:
        job: Original process-local handle and public progress view.
        lock: Original analysis registry lock.
        now: Caller-owned UTC clock, preserving the facade override seam.
        append: Existing accepted-log sink; invoked under the registry lock.
        mode: Original export, live analysis or mirror-refresh selection.
        spotify: Existing SDK client, required only for live operations.
        full_rebuild: Original mirror refresh option.
        mirror_resource: Optional original single-resource refresh selection.
    """

    job: AnalysisJob
    lock: Lock
    now: Callable[[], datetime]
    append: Callable[[AnalysisJob, str], None]
    mode: analysis.AnalysisMode
    spotify: Spotify | None
    full_rebuild: bool
    mirror_resource: analysis.ResourceName | None

    def start(self) -> None:
        """Publish the original running phase before binding SDK callbacks."""
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.now().isoformat()
            self.job.result.detail = "Analysis started"
            self.append(self.job, f"{self.mode.title()} analysis started.")

    def progress(
        self,
        resource: analysis.ResourceName,
        completed: int,
        total: int | None,
        progress_status: str,
    ) -> None:
        """Apply original resource progress and log only changed status text.

        Args:
            resource: Existing progress bucket, without creating missing buckets.
            completed: Original observed count.
            total: Optional original expected count.
            progress_status: Original display text.

        Raises:
            KeyError: The original view does not contain the requested resource.
        """
        with self.lock:
            progress = self.job.result.resources[resource]
            changed = progress.status != progress_status
            progress.completed = completed
            progress.total = total
            progress.status = progress_status
            self._running_detail(resource, progress_status)
            self._progress_log(resource, completed, total, progress_status, changed)

    def _running_detail(self, resource: str, progress_status: str) -> None:
        if self.job.result.status == "cancelling":
            return
        self.job.result.status = "running"
        self.job.result.detail = f"{resource.title()}: {progress_status}"

    def _progress_log(
        self,
        resource: str,
        completed: int,
        total: int | None,
        progress_status: str,
        changed: bool,
    ) -> None:
        if not changed:
            return
        count = str(completed)
        if total is not None:
            count = f"{completed} / {max(completed, total)}"
        self.append(self.job, f"{resource.title()}: {progress_status} ({count}).")

    def echo(self, line: str) -> None:
        """Accept one message while protecting waiting/cancellation detail.

        Args:
            line: Original routine or SDK event text, including empty text.
        """
        with self.lock:
            self.append(self.job, line)
            if self.job.result.status not in {"waiting", "cancelling"}:
                self.job.result.detail = line

    def retry_wait(self, notice: analysis.RetryNotice) -> bool:
        """Wait on this job's original cancellation signal and present retries.

        Args:
            notice: Original failure, operation, attempt and delay observation.

        Returns:
            Whether the original delay completed without cancellation.
        """
        retry_at = self.now() + timedelta(seconds=notice.delay_seconds)
        failure = _retry_failure(notice)
        self._waiting(notice, retry_at, failure)
        cancelled = self.job.cancel_event.wait(notice.delay_seconds)
        self._retry_finished(cancelled)
        return not cancelled

    def _waiting(
        self, notice: analysis.RetryNotice, retry_at: datetime, failure: str
    ) -> None:
        with self.lock:
            self.job.result.status = "waiting"
            self.job.result.retry_at = retry_at.isoformat()
            self.job.result.detail = (
                f"{failure}; retry {notice.attempt} while {notice.operation}"
            )
            self.append(
                self.job,
                f"Waiting until {retry_at.isoformat()} before retry "
                f"{notice.attempt} after {failure} "
                f"while {notice.operation}. Cancel to save and stop.",
            )

    def _retry_finished(self, cancelled: bool) -> None:
        with self.lock:
            self.job.result.retry_at = None
            if cancelled:
                return
            self.job.result.status = "running"
            self.job.result.detail = "Retrying Spotify request"
            self.append(self.job, "Retrying Spotify request now.")

    def execute(self) -> analysis.LibrarySyncSummary:
        """Dispatch the original mode with this job's explicit callbacks.

        Returns:
            The original accepted analysis summary.

        Raises:
            analysis.LibrarySyncError: A live mode lacks its original SDK client.
            analysis.LibraryAnalysisCancelledError: An existing safe boundary stops.
            analysis.SpotifyRateLimitError: The original routine pauses its progress.
        """
        if self.mode == "async":
            return analysis.analyse_library_async_routine(
                echo=self.echo,
                progress_callback=self.progress,
                cancel_check=self.job.cancel_event.is_set,
            )
        spotify = self._require_spotify()
        if self.mode == "sync":
            return self._analyse_live(spotify)
        if self.mirror_resource is None:
            return self._refresh_mirrors(spotify)
        return self._refresh_resource(spotify, self.mirror_resource)

    def _require_spotify(self) -> Spotify:
        if self.spotify is not None:
            return self.spotify
        operation = "live analysis" if self.mode == "sync" else "live mirror refresh"
        raise analysis.LibrarySyncError(
            f"A Spotify client is required for {operation}."
        )

    def _analyse_live(self, spotify: Spotify) -> analysis.LibrarySyncSummary:
        return analysis.analyse_library_sync_routine(
            spotify,
            echo=self.echo,
            progress_callback=self.progress,
            retry_wait=self.retry_wait,
            cancel_check=self.job.cancel_event.is_set,
        )

    def _refresh_mirrors(self, spotify: Spotify) -> analysis.LibrarySyncSummary:
        return analysis.refresh_live_library_mirrors_routine(
            spotify,
            echo=self.echo,
            progress_callback=self.progress,
            retry_wait=self.retry_wait,
            cancel_check=self.job.cancel_event.is_set,
            full_rebuild=self.full_rebuild,
        )

    def _refresh_resource(
        self, spotify: Spotify, resource: analysis.ResourceName
    ) -> analysis.LibrarySyncSummary:
        return analysis.refresh_live_library_resource_routine(
            spotify,
            resource,
            echo=self.echo,
            progress_callback=self.progress,
            retry_wait=self.retry_wait,
            cancel_check=self.job.cancel_event.is_set,
            full_rebuild=self.full_rebuild,
        )

    def cancelled(self, error: analysis.LibraryAnalysisCancelledError) -> None:
        """Present the original saved-progress cancellation outcome.

        Args:
            error: Original cancellation raised at a safe routine boundary.
        """
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = f"{error} Progress was saved."
            self.append(self.job, self.job.result.detail)

    def paused(self, error: analysis.SpotifyRateLimitError) -> None:
        """Present the original rate-limit pause and optional retry timestamp.

        Args:
            error: Original rate-limit observation, including an optional delay.
        """
        retry_at = None
        if error.retry_after_seconds is not None:
            retry_at = self.now() + timedelta(seconds=error.retry_after_seconds)
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.retry_at = retry_at.isoformat() if retry_at else None
            self.job.result.detail = "Spotify rate limit reached. Progress was saved."
            self.append(self.job, self.job.result.detail)

    def failed(self, error: analysis.LibrarySyncError) -> None:
        """Present the original anticipated analysis failure.

        Args:
            error: Original routine failure text.
        """
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(error)
            self.append(self.job, f"Analysis failed: {error}")

    def unexpected_failure(self, error: Exception) -> None:
        """Present an error caught by the retained outer worker boundary.

        Args:
            error: Unexpected routine error; classification stays at the facade.
        """
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected analysis error: {error}"
            self.append(self.job, self.job.result.detail)

    def completed(self, summary: analysis.LibrarySyncSummary) -> None:
        """Present the original successful summary and ordered resource logs.

        Args:
            summary: Original accepted routine result and backup identity.
        """
        with self.lock:
            self.job.result.status = "completed"
            self.job.result.detail = "Analysis completed"
            self.job.result.run_id = summary.run_id
            self.job.result.backup_dir = summary.backup_dir
            for resource in summary.resources:
                self.append(self.job, _resource_summary(resource))
            self.append(
                self.job,
                f"Analysis completed. Run {summary.run_id}; "
                f"backup {summary.backup_dir}.",
            )

    def finish(self) -> None:
        """Record original completion time after SDK callback restoration."""
        with self.lock:
            self.job.result.completed_at = self.now().isoformat()


def _retry_failure(notice: analysis.RetryNotice) -> str:
    if notice.http_status is None:
        return "Spotify connection interrupted"
    return f"Spotify HTTP {notice.http_status}"


def _resource_summary(resource: analysis.ResourceSyncSummary) -> str:
    return (
        f"{resource.resource.title()}: {resource.previous} -> "
        f"{resource.current} (+{resource.added}, "
        f"-{resource.removed}, skipped {resource.skipped})."
    )
