"""Explicit callbacks and wire presentation for ScrobbleHistoryWorker."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.infrastructure.lastfm_async import (
    AsyncLastFmClient as LastFmClient,
)
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history


@dataclass(kw_only=True)
class ScrobbleHistoryWorker:
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Invocation-owned context.
        job_id: Invocation-owned job id.
        api_key: Invocation-owned api key.
        username: Invocation-owned username.
        dry_run: Invocation-owned dry run.
        full_rebuild: Invocation-owned full rebuild.
        create_lastfm: Invocation-owned create lastfm.

    Attributes:
        job: Resolved reconnectable job state.
    """

    context: PlaylistContext
    job_id: str
    api_key: str
    username: str
    dry_run: bool
    full_rebuild: bool
    job: _BlastJob = field(init=False)
    lastfm: LastFmClient = field(init=False)

    async def run(self) -> None:
        """Refresh the shared Last.fm record as a reconnectable web job."""
        self._start()
        try:
            summary = await self._execute()
        except scrobble_history.ScrobbleHistoryCancelledError as exc:
            self._cancelled(exc)
        except (scrobble_history.ScrobbleHistoryError, LastFmError) as exc:
            self._failed(exc)
        except Exception as exc:
            self._unexpected_failure(exc)
        else:
            self._completed(summary)
        finally:
            self._finish()

    def echo(self, message: str) -> None:
        """Present a routine message using this job's original log sink.

        Args:
            message: Original routine-supplied message.
        """
        scrobble_history.check_cancel(self.job.cancel_event)
        with self.context.lock:
            self.job.result.detail = message
            self.context.append(self.job, message)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="update_scrobble_history")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Last.fm scrobble history update started"
            self.context.append(
                self.job,
                "Last.fm scrobble history update started in dry-run mode."
                if self.dry_run
                else "Last.fm scrobble history update started.",
            )
        self.lastfm = lastfm_client(
            LastFmCredentials(self.api_key, self.username), self
        )

    async def _execute(self) -> scrobble_history.ScrobbleHistorySummary:
        summary = await scrobble_history.refresh_scrobble_history(
            self.lastfm,
            expected_username=self.username,
            dry_run=self.dry_run,
            full_rebuild=self.full_rebuild,
            progress_callback=self,
            cancel_check=self.job.cancel_event,
        )
        return summary

    def _completed(self, summary: scrobble_history.ScrobbleHistorySummary) -> None:
        with self.context.lock:
            self.job.result.status = "completed"
            self.job.result.history_export_scrobbles = summary.export_scrobbles
            self.job.result.history_legacy_scrobbles_added = (
                summary.legacy_scrobbles_added
            )
            self.job.result.live_scrobbles_added = summary.live_scrobbles_added
            self.job.result.history_scrobbles = summary.total_scrobbles
            self.job.result.history_persisted = summary.persisted
            self.job.result.history_backup_path = (
                str(summary.backup_path) if summary.backup_path else None
            )
            if summary.dry_run:
                self.job.result.detail = (
                    "Dry run complete; the canonical Last.fm history was unchanged."
                )
            elif summary.persisted:
                self.job.result.detail = "Last.fm scrobble history updated safely."
            else:
                self.job.result.detail = "Last.fm scrobble history was already current."
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        with self.context.lock:
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self, exc: scrobble_history.ScrobbleHistoryCancelledError) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = str(exc)
            self.context.append(self.job, self.job.result.detail)

    def _failed(self, exc: scrobble_history.ScrobbleHistoryError | LastFmError) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Scrobble history update failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected scrobble history update error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected scrobble history update error: {exc}"
            self.context.append(self.job, self.job.result.detail)
