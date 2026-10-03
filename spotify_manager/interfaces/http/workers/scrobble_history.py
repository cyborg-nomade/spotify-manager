"""Explicit callbacks and wire presentation for ScrobbleHistoryWorker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from threading import Lock

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history


@dataclass(kw_only=True)
class ScrobbleHistoryWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        api_key: Explicit api key input or adapter boundary.
        username: Explicit username input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        full_rebuild: Explicit full rebuild input or adapter boundary.
        create_lastfm: Explicit create lastfm input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    api_key: str
    username: str
    dry_run: bool
    full_rebuild: bool
    create_lastfm: Callable[..., LastFmClient]
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    lastfm: LastFmClient = field(init=False)

    def run(self) -> None:
        """Refresh the shared Last.fm record as a reconnectable web job."""
        self._start()
        try:
            summary = self._execute()
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
        scrobble_history.check_cancel(self.job.cancel_event.is_set)
        with self.lock:
            self.job.result.detail = message
            self.append(self.job, message)

    def _start(self) -> None:
        self.job = self.lookup(self.job_id, command="update_scrobble_history")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Last.fm scrobble history update started"
            self.append(
                self.job,
                "Last.fm scrobble history update started in dry-run mode."
                if self.dry_run
                else "Last.fm scrobble history update started.",
            )
        self.lastfm = self.create_lastfm(
            self.api_key, self.username, event_callback=self.echo
        )

    def _execute(self) -> scrobble_history.ScrobbleHistorySummary:
        summary = scrobble_history.refresh_scrobble_history(
            self.lastfm,
            expected_username=self.username,
            dry_run=self.dry_run,
            full_rebuild=self.full_rebuild,
            progress_callback=self.echo,
            cancel_check=self.job.cancel_event.is_set,
        )
        return summary

    def _completed(self, summary: scrobble_history.ScrobbleHistorySummary) -> None:
        with self.lock:
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
            self.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        with self.lock:
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self, exc: scrobble_history.ScrobbleHistoryCancelledError) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = str(exc)
            self.append(self.job, self.job.result.detail)

    def _failed(self, exc: scrobble_history.ScrobbleHistoryError | LastFmError) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Scrobble history update failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected scrobble history update error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected scrobble history update error: {exc}"
            self.append(self.job, self.job.result.detail)
