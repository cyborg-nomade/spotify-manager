"""Explicit callbacks and wire presentation for NewYearWorker."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from threading import Lock

from spotipy import Spotify

from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import new_year as new_year
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class NewYearWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        year: Explicit year input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        create_lastfm: Explicit create lastfm input or adapter boundary.
        configuration: Explicit configuration input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _playlist_job_retry: Explicit playlist job retry input or adapter boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    year: int | None
    dry_run: bool
    create_lastfm: Callable[..., LastFmClient]
    configuration: Callable[[], Settings]
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _playlist_job_retry: Callable[
        [_BlastJob, Callable[[str], None]], blast_from_past.RetryCall
    ]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)

    def run(self) -> None:
        """Run the annual workflow through the shared routine and job registry."""
        self._start()
        try:
            self._execute()
        except (
            scrobble_history.ScrobbleHistoryCancelledError,
            blast_from_past.BlastFromPastCancelledError,
        ) as exc:
            self._cancelled(exc)
        except Exception as exc:
            self._unexpected_failure(exc)
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
        self.job = self.lookup(self.job_id, command="new_year")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()

    def _execute(self) -> None:
        configuration = self.configuration()
        key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
        result = new_year.run_new_year(
            self.spotify,
            self.create_lastfm(key, username, event_callback=self.echo),
            configuration,
            year=self.year,
            dry_run=self.dry_run,
            echo=self.echo,
            cancel_check=self.job.cancel_event.is_set,
            retry_call=self._playlist_job_retry(self.job, self.echo),
        )
        with self.lock:
            self.job.result.new_year_result = result
            self.job.result.status = "completed"

    def _finish(self) -> None:
        with self.lock:
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(
        self,
        exc: scrobble_history.ScrobbleHistoryCancelledError
        | blast_from_past.BlastFromPastCancelledError,
    ) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = str(exc)

    def _unexpected_failure(self, exc: Exception) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, str(exc))
