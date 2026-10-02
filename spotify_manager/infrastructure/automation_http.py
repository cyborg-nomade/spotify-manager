"""Original authenticated urllib boundary with explicit clocks and bounded retries."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request

from spotify_manager.application.automation_values import REQUEST_RETRY_SECONDS
from spotify_manager.application.automation_values import TRANSIENT_HTTP_STATUSES
from spotify_manager.application.automation_values import ApiError
from spotify_manager.application.automation_values import AutomationError
from spotify_manager.application.automation_values import DeadlineReachedError
from spotify_manager.infrastructure.automation_records import decode_response


class HttpResponse(Protocol):
    """Expose original response status, body and context-managed lifetime."""

    status: int

    def read(self) -> bytes:
        """Read the original complete response body.

        Returns:
            Original response bytes.
        """
        ...

    def __enter__(self) -> HttpResponse:
        """Enter the original urllib response lifetime.

        Returns:
            Original readable response.
        """
        ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: object,
    ) -> None:
        """Close the original response lifetime.

        Args:
            kind: Original failure class.
            error: Original raised failure.
            traceback: Original traceback.
        """
        ...


class OpenResponse(Protocol):
    """Supply the original urllib opener without global transport ownership."""

    def __call__(self, request: Request, *, timeout: int) -> HttpResponse:
        """Open the original timed HTTP request.

        Args:
            request: Original authenticated request.
            timeout: Original socket timeout in seconds.

        Returns:
            Original context-managed response.
        """
        ...


class SpaceHttpClient:
    """Own original synchronous HTTP observations and maintenance time bounds.

    Args:
        space_url: Original normalized Space URL.
        hf_token: Original private Space access token.
        automation_token: Original API automation credential.
        deadline: Original maintenance boundary.
        opener: Original urllib transport seam.
        now: Original delayed UTC clock.
        sleep: Original blocking wait.
        emit: Original retry presentation.
    """

    def __init__(
        self,
        space_url: str,
        hf_token: str,
        automation_token: str,
        deadline: datetime,
        opener: OpenResponse,
        now: Callable[[], datetime],
        sleep: Callable[[float], None],
        emit: Callable[[str], None],
    ) -> None:
        """Bind original request and lifetime dependencies.

        Args:
            space_url: Original Space URL.
            hf_token: Original private access token.
            automation_token: Original automation credential.
            deadline: Original maintenance boundary.
            opener: Original HTTP transport.
            now: Original clock observation.
            sleep: Original wait boundary.
            emit: Original retry output.
        """
        self.space_url = space_url
        self.deadline = deadline
        self.headers = {
            "Authorization": f"Bearer {hf_token}",
            "X-Automation-Token": automation_token,
            "User-Agent": "spotify-manager-nightly-refresh/1",
        }
        self._opener = opener
        self._now = now
        self._sleep = sleep
        self._emit = emit

    def remaining_seconds(self) -> float:
        """Observe the original signed maintenance time remaining.

        Returns:
            Seconds between the original deadline and delayed clock observation.
        """
        return (self.deadline - self._now()).total_seconds()

    def sleep(self, seconds: int) -> None:
        """Retain original maintenance clipping even during cancellation grace.

        Args:
            seconds: Original requested retry or polling delay.

        Raises:
            DeadlineReachedError: The original maintenance boundary has arrived.
        """
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise DeadlineReachedError("The 05:00 Berlin maintenance deadline arrived.")
        self._sleep(min(seconds, remaining))

    def request(
        self,
        method: str,
        path: str,
        *,
        retry_transient: bool = True,
        deadline: datetime | None = None,
    ) -> object:
        """Issue the original JSON request with bounded gateway and transport retries.

        Args:
            method: Original HTTP verb.
            path: Original path including query.
            retry_transient: Original retry permission.
            deadline: Original optional cancellation grace boundary.

        Returns:
            Original unvalidated decoded JSON.

        Raises:
            DeadlineReachedError: The original request boundary has arrived.
            ApiError: Original non-retried HTTP status fails.
            AutomationError: Original transport or success decoding fails.
        """
        boundary = deadline or self.deadline
        while self._now() < boundary:
            try:
                return self._attempt(method, path, retry_transient)
            except _RetryRequestError:
                continue
        raise DeadlineReachedError(
            "The maintenance deadline arrived during an API call."
        )

    def _attempt(self, method: str, path: str, retry: bool) -> object:
        request = Request(
            urljoin(self.space_url, path.lstrip("/")),
            method=method,
            headers=self.headers,
            data=b"" if method == "POST" else None,
        )
        try:
            return self._read(request, path)
        except HTTPError as error:
            self._handle_http(error, retry)
        except (TimeoutError, URLError) as error:
            if not retry:
                raise AutomationError(f"Could not reach the Space: {error}") from error
            self._emit("Space connection interrupted; retrying.")
            self.sleep(REQUEST_RETRY_SECONDS)
        raise _RetryRequestError

    def _read(self, request: Request, path: str) -> object:
        with self._opener(request, timeout=60) as response:
            return _decode_success(response, path)

    def _handle_http(self, error: HTTPError, retry: bool) -> None:
        payload = _http_error_payload(error)
        if retry and error.code in TRANSIENT_HTTP_STATUSES:
            self._emit(f"Space returned HTTP {error.code}; retrying.")
            self.sleep(REQUEST_RETRY_SECONDS)
            return
        raise ApiError(error.code, payload) from error


def _decode_success(response: HttpResponse, path: str) -> object:
    try:
        return decode_response(response.read())
    except AutomationError as error:
        raise AutomationError(
            f"Space returned non-JSON HTTP {response.status} for {path}; "
            "check HF_SPACE_TOKEN access to the private Space."
        ) from error


def _http_error_payload(error: HTTPError) -> object:
    try:
        return decode_response(error.read())
    except AutomationError:
        return {
            "detail": "Non-JSON response from the Space gateway; "
            "check HF_SPACE_TOKEN access to the private Space."
        }


class _RetryRequestError(RuntimeError):
    """Continue the original bounded request loop after its accepted retry wait."""
