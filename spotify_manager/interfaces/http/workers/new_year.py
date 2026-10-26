"""Explicit callbacks and wire presentation for NewYearWorker."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC

from spotipy import Spotify

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.playlist_retry import PlaylistRetry
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import new_year as new_year
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history


@dataclass(kw_only=True)
class NewYearWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Job id supplied by the caller.
        spotify: Caller-owned Spotify client.
        year: Year supplied by the caller.
        dry_run: Whether to preview without durable writes.
        context: Shared job lock, clock and presentation context.
        job: Mutable job record owned by this worker.
    """

    job_id: str
    spotify: Spotify
    year: int | None
    dry_run: bool
    context: PlaylistContext
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
        scrobble_history.check_cancel(self.job.cancel_event)
        with self.context.lock:
            self.job.result.detail = message
            self.context.append(self.job, message)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="new_year")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()

    def _execute(self) -> None:
        configuration = self.context.settings.load()
        key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
        result = new_year.run_new_year(
            self.spotify,
            lastfm_client(LastFmCredentials(key, username), self),
            configuration,
            year=self.year,
            dry_run=self.dry_run,
            echo=self,
            cancel_check=self.job.cancel_event,
            retry_call=PlaylistRetry(self.job, self),
        )
        with self.context.lock:
            self.job.result.new_year_result = result
            self.job.result.status = "completed"

    def _finish(self) -> None:
        with self.context.lock:
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(
        self,
        exc: scrobble_history.ScrobbleHistoryCancelledError
        | blast_from_past.BlastFromPastCancelledError,
    ) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = str(exc)

    def _unexpected_failure(self, exc: Exception) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, str(exc))
