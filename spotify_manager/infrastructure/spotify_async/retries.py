"""Reuse the synchronous urllib3 retry policy without its blocking HTTP adapter."""

from dataclasses import dataclass

import httpx
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ConnectTimeout as RequestsConnectTimeout
from requests.exceptions import ReadTimeout as RequestsReadTimeout
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException
from urllib3.exceptions import ConnectTimeoutError
from urllib3.exceptions import MaxRetryError
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry

from spotify_manager.application.ports.spotify_async import AsyncWait


@dataclass(frozen=True)
class RetryProfile:
    """Preserve independently selected transport and outer-read retry limits.

    Args:
        retries: Original total adapter retry count.
        status_retries: Original HTTP status retry limit.
        statuses: Original selected status list, including the disabled sentinel.
        backoff: Original urllib3 exponential backoff factor.
    """

    retries: int = 5
    status_retries: int = 5
    statuses: tuple[int, ...] = (500, 502, 503, 504)
    backoff: float = 0.3

    def adapter(self) -> Retry:
        """Create independent adapter state for one outer request attempt.

        Returns:
            Original urllib3 policy with Retry-After disabled at this layer.
        """
        return Retry(
            total=self.retries,
            connect=None,
            read=False,
            allowed_methods=frozenset({"GET", "POST", "PUT", "DELETE"}),
            status=self.status_retries,
            backoff_factor=self.backoff,
            status_forcelist=self.statuses,
            respect_retry_after_header=False,
        )


async def retry_status(
    retry: Retry, response: httpx.Response, wait: AsyncWait
) -> Retry:
    """Advance the same urllib3 status budget and backoff sequence.

    Args:
        retry: Current adapter attempt state.
        response: Retryable HTTP response.
        wait: Named asynchronous delay owner.

    Returns:
        Next adapter state.

    Raises:
        SpotifyException: Original SDK exhaustion mapping to HTTP 429.
    """
    try:
        updated = retry.increment(
            response.request.method,
            str(response.url),
            response=HTTPResponse(status=response.status_code),
        )
    except MaxRetryError as error:
        raise SpotifyException(
            429,
            -1,
            f"{response.url.raw_path.decode()}:\n Max Retries",
            reason=error.reason,
        ) from error
    await wait.sleep(updated.get_backoff_time())
    return updated


async def retry_connect(
    retry: Retry, request: httpx.Request, error: httpx.TransportError, wait: AsyncWait
) -> Retry:
    """Preserve adapter-level connect retries before the outer GET retry budget.

    Args:
        retry: Current independent adapter retry state.
        request: Failed HTTP request.
        error: Native connection failure.
        wait: Asynchronous backoff owner.

    Returns:
        Next adapter state.

    Raises:
        RequestsConnectionError: The original connection budget is exhausted.
    """
    try:
        updated = retry.increment(
            request.method, str(request.url), error=ConnectTimeoutError(str(error))
        )
    except MaxRetryError as exhausted:
        raise transport_error(error) from exhausted
    await wait.sleep(updated.get_backoff_time())
    return updated


def transport_error(
    error: httpx.TransportError,
) -> RequestsConnectionError | RequestsTimeout:
    """Retain the exception family consumed by existing routine retry policies.

    Args:
        error: Native transport failure.

    Returns:
        Compatible requests exception with the original failure as its cause.
    """
    if isinstance(error, httpx.ConnectTimeout):
        return RequestsConnectTimeout(str(error))
    if isinstance(error, httpx.ReadTimeout):
        return RequestsReadTimeout(str(error))
    if isinstance(error, httpx.TimeoutException):
        return RequestsTimeout(str(error))
    return RequestsConnectionError(str(error))
