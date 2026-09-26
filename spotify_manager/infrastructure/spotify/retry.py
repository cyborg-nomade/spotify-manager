"""Original synchronous retry policy shared by library workflows and interfaces."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from math import ceil

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException


type Echo = Callable[[str], None]
type Sleep = Callable[[float], None]

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
    """Bound retry callbacks, fixed delay, and normalized attempt limit."""

    echo: Echo
    sleep: Sleep
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
    policy.echo(
        f"{prefix} while {description}. Retrying {format_retry_delay(policy.delay)}."
    )
    policy.sleep(policy.delay)


def retry_spotify_server_errors[T](
    operation: Callable[[], T],
    description: str,
    echo: Echo,
    sleep: Sleep,
    retry_delay_seconds: int,
    max_attempts: int,
) -> T:
    """Retry temporary Spotify failures using the original operation-level policy.

    Args:
        operation: Original observation or effect to attempt.
        description: Existing user-facing operation description.
        echo: Existing retry message sink.
        sleep: Caller-owned retry wait and cancellation boundary.
        retry_delay_seconds: Original fixed wait duration.
        max_attempts: Original attempt limit, clamped to at least one.

    Returns:
        The successful operation's unchanged result.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyTransientServerError: Temporary failures exhaust the attempt limit.
        SpotifyException: A non-transient Spotify failure occurs.
    """
    attempts = 0
    policy = _RetryPolicy(echo, sleep, retry_delay_seconds, max(1, max_attempts))
    while True:
        attempts += 1
        try:
            return operation()
        except (SpotifyException, RequestsConnectionError, RequestsTimeout) as exc:
            _wait_or_raise(exc, description, attempts, policy)


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
