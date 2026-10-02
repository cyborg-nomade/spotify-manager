"""Original library-specific synchronous retry attempts, audits and wait decisions."""

from collections.abc import Callable
from dataclasses import dataclass

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException

from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import Echo
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import Sleep
from spotify_manager.domain.library_analysis import retry_delay
from spotify_manager.domain.library_analysis_values import LibraryAnalysisCancelledError
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import RetryNotice
from spotify_manager.domain.library_analysis_values import RetryWait
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.infrastructure.spotify.retry import get_retry_after_seconds


@dataclass(frozen=True)
class LibraryRetry:
    """Bind original retry audit, presenter, limits and caller-supplied waiting.

    Args:
        paths: Original independent output family.
        checkpoint: Original mutable accepted progress.
        files: Original ordered audit and clock boundaries.
        echo: Original retry presenter.
        wait: Original optional interactive retry decision.
        sleep: Original blocking default wait.
        base_seconds: Original first transient delay.
        max_seconds: Original maximum transient delay.
    """

    paths: LibraryAnalysisPaths
    checkpoint: Checkpoint
    files: AnalysisFiles
    echo: Echo
    wait: RetryWait | None
    sleep: Sleep
    base_seconds: int
    max_seconds: int

    def call[T](
        self,
        operation: Callable[[], T],
        description: str,
        max_attempts: int | None = None,
    ) -> T:
        """Retain original shared attempt counting across server/transport failures.

        Args:
            operation: Original selected Spotify request.
            description: Original visible operation label.
            max_attempts: Original optional maximum attempts.

        Returns:
            Original accepted response.

        Raises:
            LibrarySyncError: An original terminal request or bounded retry fails.
            SpotifyRateLimitError: The original request reports HTTP 429.
            LibraryAnalysisCancelledError: The original retry decision requests a pause.
        """
        attempt = 0
        while True:
            try:
                return operation()
            except SpotifyException as exc:
                _validate_spotify_failure(exc, description)
                attempt += 1
                _check_server_attempt(exc, attempt, description, max_attempts)
                self._server_wait(exc, attempt, description)
            except (RequestsConnectionError, RequestsTimeout) as exc:
                attempt += 1
                _check_transport_attempt(exc, attempt, description, max_attempts)
                self._transport_wait(exc, attempt, description)

    def _server_wait(
        self, error: SpotifyException, attempt: int, description: str
    ) -> None:
        delay = retry_delay(self.base_seconds, self.max_seconds, attempt)
        notice = RetryNotice(error.http_status, description, attempt, delay)
        self.files.event(
            self.paths,
            str(self.checkpoint["run_id"]),
            "server_retry_scheduled",
            http_status=error.http_status,
            operation=description,
            attempt=attempt,
            delay_seconds=delay,
        )
        self.echo(
            f"Spotify HTTP {error.http_status} while {description}; "
            f"retrying in {delay} seconds (attempt {attempt})."
        )
        self._wait(notice, error)

    def _transport_wait(
        self,
        error: RequestsConnectionError | RequestsTimeout,
        attempt: int,
        description: str,
    ) -> None:
        delay = retry_delay(self.base_seconds, self.max_seconds, attempt)
        notice = RetryNotice(None, description, attempt, delay)
        self.files.event(
            self.paths,
            str(self.checkpoint["run_id"]),
            "transport_retry_scheduled",
            error=type(error).__name__,
            operation=description,
            attempt=attempt,
            delay_seconds=delay,
        )
        self.echo(
            f"Spotify connection interrupted while {description}; "
            f"retrying in {delay} seconds (attempt {attempt})."
        )
        self._wait(notice, error)

    def _wait(self, notice: RetryNotice, error: BaseException) -> None:
        should_continue = (
            self.wait(notice)
            if self.wait is not None
            else _default_wait(notice.delay_seconds, self.sleep)
        )
        if not should_continue:
            raise LibraryAnalysisCancelledError(
                "Live analysis paused during a Spotify retry wait."
            ) from error


def _default_wait(delay: int, sleep: Sleep) -> bool:
    sleep(delay)
    return True


def _validate_spotify_failure(error: SpotifyException, description: str) -> None:
    if error.http_status == 429:
        raise SpotifyRateLimitError(get_retry_after_seconds(error)) from error
    if error.http_status is None or not 500 <= error.http_status <= 599:
        raise LibrarySyncError(
            f"Spotify request failed while {description} "
            f"(HTTP {error.http_status}): {error.msg}"
        ) from error


def _check_server_attempt(
    error: SpotifyException, attempt: int, description: str, maximum: int | None
) -> None:
    if maximum is not None and attempt >= maximum:
        raise LibrarySyncError(
            f"Spotify HTTP {error.http_status} persisted for {attempt} attempts "
            f"while {description}."
        ) from error


def _check_transport_attempt(
    error: RequestsConnectionError | RequestsTimeout,
    attempt: int,
    description: str,
    maximum: int | None,
) -> None:
    if maximum is not None and attempt >= maximum:
        raise LibrarySyncError(
            f"Spotify connection remained unavailable for {attempt} attempts "
            f"while {description}."
        ) from error
