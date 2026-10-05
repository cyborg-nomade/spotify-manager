"""Explicit callbacks and wire presentation for FoundArtWorker."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.presenters.collections import present_entries
from spotify_manager.interfaces.http.presenters.recommendations import (
    found_art_selection_result as _found_art_selection_result,
)
from spotify_manager.interfaces.operations import found_art as found_art


@dataclass(kw_only=True)
class FoundArtWorker:
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Invocation-owned context.
        job_id: Invocation-owned job id.
        spotify: Invocation-owned spotify.
        playlist_id: Invocation-owned playlist id.
        api_key: Invocation-owned api key.
        username: Invocation-owned username.
        count: Invocation-owned count.
        create_lastfm: Invocation-owned create lastfm.
        connection_failure: Invocation-owned connection failure.
    """

    context: PlaylistContext
    job_id: str
    spotify: Spotify
    playlist_id: str
    api_key: str
    username: str
    count: int
    connection_failure: str
    job: _BlastJob = field(init=False)
    lastfm: LastFmClient = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one Found Art web job and retain its complete trace."""
        self._start()
        try:
            summary = self._execute()
        except (found_art.FoundArtError, LastFmError, SpotifyException) as exc:
            self._failed(exc)
        except RequestException:
            self._connection_failed()
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
        with self.context.lock:
            self.job.result.detail = message
            self.context.append(self.job, message)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="found_art")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Found Art started"
            self.context.append(self.job, "Found Art started.")
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)
        self.lastfm = lastfm_client(
            LastFmCredentials(self.api_key, self.username), self.echo
        )

    def _execute(self) -> found_art.FoundArtSummary:
        summary = found_art.run_found_art(
            self.spotify,
            self.lastfm,
            self.playlist_id,
            count=self.count,
            progress_callback=self.echo,
        )
        return summary

    def _completed(self, summary: found_art.FoundArtSummary) -> None:
        results = present_entries(summary.results, _found_art_selection_result)
        with self.context.lock:
            self.job.result.status = "completed"
            self.job.result.requested_count = summary.requested_count
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = summary.added
            self.job.result.week_start = summary.week_start.isoformat()
            self.job.result.history_tracks = summary.history_tracks
            self.job.result.history_scrobbles = summary.history_scrobbles
            self.job.result.live_scrobbles_added = summary.live_scrobbles_added
            self.job.result.candidate_count = summary.candidate_count
            self.job.result.found_art_results = results
            self.job.result.detail = (
                f"Added {summary.added} of {summary.requested_count}"
                f" recommendations; playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = result.spotify_match or "no unliked qualifying match"
                self.context.append(
                    self.job,
                    f"{result.artist} - {result.track} -> {target} ({result.action}).",
                )
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.context.lock:
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _failed(
        self, exc: found_art.FoundArtError | LastFmError | SpotifyException
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Found Art failed: {exc}")

    def _connection_failed(self) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.context.append(self.job, self.job.result.detail)

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Found Art error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Found Art error: {exc}"
            self.context.append(self.job, self.job.result.detail)
