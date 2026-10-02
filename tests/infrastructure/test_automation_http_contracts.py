"""Verify original urllib requests, response lifetimes, retry waits and error causes."""

import ast
import io
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request

import pytest

from spotify_manager.application.automation_values import ApiError
from spotify_manager.application.automation_values import AutomationError
from spotify_manager.application.automation_values import DeadlineReachedError
from spotify_manager.infrastructure.automation_http import SpaceHttpClient
from spotify_manager.infrastructure.automation_records import artifact_updates


@dataclass
class Response:
    """Expose the original urllib success-response lifetime.

    Args:
        content: Original response bytes.
        status: Original successful HTTP status.
        closed: Whether the response lifetime has ended.
    """

    content: bytes
    status: int = 200
    closed: bool = False

    def read(self) -> bytes:
        """Read original bytes.

        Returns:
            Original complete body.
        """
        return self.content

    def __enter__(self) -> Response:
        """Open original response lifetime.

        Returns:
            This readable response.
        """
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: object,
    ) -> None:
        """Close the response even when original decoding fails.

        Args:
            kind: Original failure type.
            error: Original raised failure.
            traceback: Original traceback.
        """
        self.closed = True


@dataclass
class Transport:
    """Supply deterministic original HTTP observations and a controllable clock.

    Args:
        responses: Original raw bodies or narrowed transport failures.
        instant: Original UTC clock.
        requests: Original complete HTTP requests and timeouts.
        waits: Original accepted blocking delays.
        output: Original retry presentation.
        advance: Advance the clock after retry waits when testing deadlines.
        opened: Accepted readable responses.
    """

    responses: list[bytes | HTTPError | URLError | TimeoutError]
    instant: datetime = datetime(2026, 9, 24, tzinfo=UTC)
    requests: list[tuple[Request, int]] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    advance: bool = False
    opened: list[Response] = field(default_factory=list)

    def open(self, request: Request, *, timeout: int) -> Response:
        """Open one original request with its exact timeout.

        Args:
            request: Original authenticated request.
            timeout: Original transport timeout.

        Returns:
            Original readable response.

        Raises:
            HTTPError: The selected original status fails.
            URLError: The selected original connection fails.
            TimeoutError: The selected original request times out.
        """
        self.requests.append((request, timeout))
        raw = self.responses.pop(0)
        if isinstance(raw, BaseException):
            raise raw
        response = Response(raw)
        self.opened.append(response)
        return response

    def now(self) -> datetime:
        """Observe the original delayed clock.

        Returns:
            Current controlled UTC instant.
        """
        return self.instant

    def sleep(self, seconds: float) -> None:
        """Record original waits and optional deadline arrival.

        Args:
            seconds: Original accepted clipped wait.
        """
        self.waits.append(seconds)
        if self.advance:
            self.instant += timedelta(seconds=seconds)

    def client(self, remaining: int = 100) -> SpaceHttpClient:
        """Bind the original explicit transport, clock, wait and output seams.

        Args:
            remaining: Original maintenance duration.

        Returns:
            Independently constructed synchronous HTTP adapter.
        """
        return SpaceHttpClient(
            "https://space.test/base/",
            "hf-dummy",
            "automation-dummy",
            self.instant + timedelta(seconds=remaining),
            self.open,
            self.now,
            self.sleep,
            self.output.append,
        )


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "raw,expected",
    [(b"", {}), (b'{"status":"ok"}', {"status": "ok"}), (b"null", None), (b"[]", [])],
)
def test_original_request_contract(method: str, raw: bytes, expected: object) -> None:
    """Retain URL joining, credentials, empty POST bytes and response lifetime.

    Args:
        method: Original HTTP verb.
        raw: Original response body.
        expected: Original decoded value.
    """
    transport = Transport([raw])
    assert transport.client().request(method, "/health?q=yes") == expected
    request, timeout = transport.requests[0]
    assert request.full_url == "https://space.test/base/health?q=yes"
    assert request.get_method() == method and timeout == 60
    assert request.data == (b"" if method == "POST" else None)
    assert request.get_header("Authorization") == "Bearer hf-dummy"
    assert request.get_header("X-automation-token") == "automation-dummy"
    assert request.get_header("User-agent") == "spotify-manager-nightly-refresh/1"
    assert transport.opened[0].closed


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_original_transient_status_retries_after_decode(status: int) -> None:
    """Retain original decoded gateway retry and wait ordering.

    Args:
        status: Original retryable HTTP response.
    """
    error = HTTPError(
        "https://space.test",
        status,
        "failure",
        Message(),
        io.BytesIO(b"<html>gateway</html>"),
    )
    transport = Transport([error, b"{}"])
    assert transport.client().request("GET", "/health") == {}
    assert transport.waits == [20]
    assert transport.output == [f"Space returned HTTP {status}; retrying."]


@pytest.mark.parametrize("status", [404, 409, 429])
@pytest.mark.parametrize("raw", [b'{"detail":"missing"}', b"<html>gateway</html>"])
def test_original_http_failure_keeps_status_and_cause(status: int, raw: bytes) -> None:
    """Keep original explicit HTTP cause and gateway fallback diagnostics.

    Args:
        status: Original non-retried HTTP response.
        raw: Original response body.
    """
    error = HTTPError(
        "https://space.test", status, "failure", Message(), io.BytesIO(raw)
    )
    transport = Transport([error])
    with pytest.raises(ApiError) as raised:
        transport.client().request("POST", "/cancel", retry_transient=False)
    assert raised.value.status == status and raised.value.__cause__ is error
    assert transport.waits == []


@pytest.mark.parametrize("failure", [TimeoutError("timeout"), URLError("offline")])
@pytest.mark.parametrize("retry", [True, False])
def test_original_connection_retry_contract(
    failure: TimeoutError | URLError, retry: bool
) -> None:
    """Retain original transport retries and explicit unretried failure causes.

    Args:
        failure: Original narrowed transport failure.
        retry: Original retry permission.
    """
    transport = Transport([failure, b"{}"])
    if not retry:
        with pytest.raises(AutomationError) as raised:
            transport.client().request("GET", "/health", retry_transient=False)
        assert raised.value.__cause__ is failure
        return
    assert transport.client().request("GET", "/health") == {}
    assert transport.waits == [20]
    assert transport.output == ["Space connection interrupted; retrying."]


def test_non_json_success_closes_response_and_preserves_nested_cause() -> None:
    """Retain success-decode diagnostics and both original cause levels."""
    transport = Transport([b"html"])
    with pytest.raises(
        AutomationError, match="non-JSON HTTP 200 for /health"
    ) as raised:
        transport.client().request("GET", "/health")
    assert isinstance(raised.value.__cause__, AutomationError)
    assert transport.opened[0].closed


def test_original_maintenance_clipping_and_expired_request() -> None:
    """Clip retry waits to the original deadline and reject expired observations."""
    transport = Transport([TimeoutError("offline")], advance=True)
    with pytest.raises(DeadlineReachedError, match="during an API call"):
        transport.client(remaining=5).request("GET", "/health")
    assert transport.waits == [5]
    with pytest.raises(DeadlineReachedError, match="05:00 Berlin"):
        transport.client(remaining=0).sleep(20)
    with pytest.raises(DeadlineReachedError, match="during an API call"):
        transport.client(remaining=0).request("GET", "/health")


def test_cancellation_grace_overrides_request_boundary() -> None:
    """Permit the original cancellation request after maintenance ends."""
    transport = Transport([b"{}"])
    client = transport.client(remaining=0)
    assert (
        client.request(
            "POST", "/cancel", deadline=transport.instant + timedelta(minutes=3)
        )
        == {}
    )


def test_artifact_codec_ignores_unknown_absent_naive_and_invalid_rows() -> None:
    """Retain last valid aware observations without tightening ignored metadata."""
    files: list[object] = [
        None,
        {},
        {"exists": True, "filename": "unknown"},
        {"exists": True, "filename": "artists_total.json", "updated_at": 5},
        {"exists": True, "filename": "artists_total.json", "updated_at": "bad"},
        {"exists": True, "filename": "artists_total.json", "updated_at": "2026-09-24"},
        {
            "exists": True,
            "filename": "artists_total.json",
            "updated_at": "2026-09-24T01:00:00+01:00",
        },
    ]
    assert artifact_updates({"files": files}) == {
        "artists_total.json": datetime(2026, 9, 24, tzinfo=UTC)
    }
    assert artifact_updates({}) is None


def test_nightly_entry_point_remains_standard_library_and_python_313_compatible() -> (
    None
):
    """Import the operational entry point without installed application dependencies."""
    root = Path(__file__).parents[2]
    files = [root / ".github/scripts/nightly_refresh.py"]
    for folder in ("application", "infrastructure", "domain"):
        files.extend((root / "spotify_manager" / folder).glob("automation*.py"))
    for path in files:
        ast.parse(path.read_text(), feature_version=(3, 13))
    result = subprocess.run(
        [sys.executable, "-S", str(files[0]), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--scheduled" in result.stdout and "--check-only" in result.stdout
