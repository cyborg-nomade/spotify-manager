"""Original synchronous retry policy shared by library workflows and interfaces."""

import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from math import ceil

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Wait
from spotify_manager.application.retry_attempts import RetryAttempts


type Sleep = Wait


type Echo = Messages


TRANSIENT_SPOTIFY_STATUSES = {500, 502, 503, 504}
TRANSIENT_RETRY_DELAY_SECONDS = 5 * 60
TRANSIENT_MAX_ATTEMPTS = 3
RETRY_AFTER_SECONDS_PATTERN = re.compile(
    r"Retry will occur after:\s*(?P<seconds>\d+(?:\.\d+)?)\s*s",
    re.IGNORECASE,
)


class SpotifyRateLimitError(RuntimeError):
    """Raised when Spotify asks the client to retry later.

    Args:
        retry_after_seconds: Reported delay, when available.
    """

    def __init__(self, retry_after_seconds: int | None) -> None:
        """Store the reported delay without changing the original message.

        Args:
            retry_after_seconds: Reported delay, when available.
        """
        super().__init__("Spotify rate limit reached")
        self.retry_after_seconds = retry_after_seconds


class SpotifyTransientServerError(RuntimeError):
    """Raised when temporary failures exhaust the original retry limit.

    Args:
        http_status: Last HTTP status, or None for transport failures.
        operation: User-facing operation description.
        attempts: Number of attempts made.
    """

    def __init__(
        self,
        http_status: int | None,
        operation: str,
        attempts: int,
    ) -> None:
        """Retain failure details for the existing interface presenters.

        Args:
            http_status: Last HTTP status, when available.
            operation: User-facing operation description.
            attempts: Number of attempts made.
        """
        super().__init__("Spotify API temporarily unavailable")
        self.http_status = http_status
        self.operation = operation
        self.attempts = attempts


def parse_retry_after_seconds(value: object) -> int | None:
    """Parse a retry-after delay from a header or Spotipy retry message.

    Args:
        value: External header, message, or absent value.

    Returns:
        Nonnegative truncated seconds, or None for an unrecognized value.

    Raises:
        OverflowError: A numeric infinity cannot be converted to integer seconds.
    """
    if value is None:
        return None

    text = str(value)
    try:
        return max(0, int(float(text)))
    except ValueError:
        pass

    match = RETRY_AFTER_SECONDS_PATTERN.search(text)
    if match is None:
        return None

    return max(0, int(float(match.group("seconds"))))


def is_transient_spotify_error(exc: SpotifyException) -> bool:
    """Identify the original retryable HTTP statuses.

    Args:
        exc: Original Spotify exception.

    Returns:
        Whether its status belongs to the existing transient set.
    """
    return exc.http_status in TRANSIENT_SPOTIFY_STATUSES


def get_retry_after_seconds(exc: SpotifyException) -> int | None:
    """Read the rate-limit delay using the original header/message precedence.

    Args:
        exc: Original Spotify exception.

    Returns:
        Reported delay, or None for another status or an unavailable delay.
    """
    if exc.http_status != 429:
        return None

    retry_after = parse_retry_after_seconds(
        exc.headers.get("Retry-After") or exc.headers.get("retry-after")
    )
    if retry_after is not None:
        return retry_after

    for value in (exc.reason, exc.msg, str(exc)):
        retry_after = parse_retry_after_seconds(value)
        if retry_after is not None:
            return retry_after

    return None


def format_retry_delay(
    retry_after_seconds: int | None,
    now: datetime | None = None,
) -> str:
    """Format a retry delay with the original local timestamp and rounding.

    Args:
        retry_after_seconds: Reported delay, when available.
        now: Optional fixed timestamp; otherwise observe local time now.

    Returns:
        Original delay text, including the expected retry timestamp.
    """
    if retry_after_seconds is None:
        return "later"

    current_time = now or datetime.now().astimezone()
    retry_at = current_time + timedelta(seconds=retry_after_seconds)
    if retry_after_seconds < 60:
        seconds = max(1, ceil(retry_after_seconds))
        unit = "second" if seconds == 1 else "seconds"
        delay = f"in {seconds} {unit}"
    else:
        minutes = ceil(retry_after_seconds / 60)
        unit = "minute" if minutes == 1 else "minutes"
        delay = f"in {minutes} {unit}"
    return f"{delay} (at {retry_at.isoformat(timespec='seconds')})"


def format_retry_after(
    retry_after_seconds: int | None,
    now: datetime | None = None,
) -> str:
    """Format the existing retry instruction.

    Args:
        retry_after_seconds: Reported delay, when available.
        now: Optional fixed timestamp.

    Returns:
        Original user-facing retry instruction.
    """
    return f"try again {format_retry_delay(retry_after_seconds, now=now)}"


def format_transient_spotify_failure(exc: SpotifyTransientServerError) -> str:
    """Format an exhausted HTTP or connection retry for user-facing output.

    Args:
        exc: Failure details from the original retry policy.

    Returns:
        Original HTTP-specific or connection-specific failure text.
    """
    if exc.http_status is not None:
        return (
            f"Spotify API temporarily unavailable ({exc.http_status}) after "
            f"{exc.attempts} attempts while {exc.operation}"
        )
    return (
        f"Spotify connection remained unavailable after {exc.attempts} attempts "
        f"while {exc.operation}"
    )


@dataclass(frozen=True)
class _RetryPolicy:
    """Bound output, wait, fixed delay, and normalized attempt limit."""

    output: Echo
    wait: Sleep
    delay: int
    attempts: int


def _wait_or_raise(
    error: SpotifyException | RequestsConnectionError | RequestsTimeout,
    description: str,
    attempts: int,
    policy: _RetryPolicy,
) -> None:
    spotify_error = isinstance(error, SpotifyException)
    if spotify_error and not is_transient_spotify_error(error):
        handle_spotify_exception(error)
    status = error.http_status if isinstance(error, SpotifyException) else None
    if attempts >= policy.attempts:
        raise SpotifyTransientServerError(status, description, attempts) from error
    if spotify_error:
        prefix = f"Spotify API temporarily unavailable ({status})"
    else:
        prefix = "Spotify connection interrupted"
    policy.output.echo(
        f"{prefix} while {description}. Retrying {format_retry_delay(policy.delay)}."
    )
    policy.wait.sleep(policy.delay)


def handle_spotify_exception(exc: SpotifyException) -> None:
    """Translate rate limits and otherwise raise the original exception.

    Args:
        exc: Original Spotify exception.

    Raises:
        SpotifyRateLimitError: Spotify reports status 429.
        SpotifyException: Any other status retains the original exception.
    """
    retry_after_seconds = get_retry_after_seconds(exc)
    if exc.http_status == 429:
        raise SpotifyRateLimitError(retry_after_seconds) from exc
    raise exc


@dataclass(frozen=True)
class SpotifyRetries:
    """Own synchronous retry settings while callers execute requests directly.

    Args:
        output: Retry message owner.
        wait: Interruptible or blocking wait owner.
        delay: Fixed transient delay.
        maximum: Maximum attempts, clamped to one.
    """

    output: Echo
    wait: Sleep
    delay: int
    maximum: int

    def attempts(self, description: str) -> RetryAttempts:
        """Open the original retry boundary without receiving an operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes using the original classification and delay rules.
        """
        return RetryAttempts(self.failure_policy(description))

    def failure_policy(self, description: str) -> SpotifyAttemptPolicy:
        """Create independent failure state for one original retry boundary.

        Args:
            description: Original request description.

        Returns:
            Fresh bounded retry state.
        """
        policy = _RetryPolicy(self.output, self.wait, self.delay, max(1, self.maximum))
        return SpotifyAttemptPolicy(policy, description)


@dataclass
class SpotifyAttemptPolicy:
    """Classify failures and wait between directly executed Spotify requests.

    Args:
        settings: Original retry settings and external resources.
        description: Original request description.
        failures: Failed attempts in this boundary.
    """

    settings: _RetryPolicy
    description: str
    failures: int = 0

    def start(self) -> None:
        """Begin a retry boundary without an additional observation."""

    def accepted(self) -> None:
        """Accept the original request without an additional observation."""

    def failed(self, error: BaseException) -> bool:
        """Retry only the original Spotify and transport failures.

        Args:
            error: Original operation failure.

        Returns:
            Whether the original failure permits another attempt.

        Raises:
            SpotifyRateLimitError: Spotify asks the caller to pause.
            SpotifyTransientServerError: The original attempt limit is reached.
            SpotifyException: The original HTTP failure is not transient.
        """
        if not isinstance(
            error, (SpotifyException, RequestsConnectionError, RequestsTimeout)
        ):
            return False
        self.failures += 1
        _wait_or_raise(error, self.description, self.failures, self.settings)
        return True
