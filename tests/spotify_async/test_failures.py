"""Exercise original HTTP/error, retry, rotation and ambiguous-write boundaries."""

import asyncio
from dataclasses import dataclass
from dataclasses import field

import httpx
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.spotify_async import HttpMethod
from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.client import SpotifyAppAuthenticationError
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from tests.spotify_async.memory import ResponseSpec
from tests.spotify_async.memory import SynchronousRecorder
from tests.spotify_async.memory import TokenMemory
from tests.spotify_async.memory import transport_memory


@pytest.mark.parametrize("status", [200, 201, 202, 204, 399, 600, 999])
@pytest.mark.parametrize(
    "text", ["", "not-json", "null", "[]", "[null, false]", '{"items": null}']
)
def test_success_payloads_are_not_silently_validated(status: int, text: str) -> None:
    """Keep original decoded values and successful invalid-JSON behavior.

    Args:
        status: Original successful status.
        text: Original response body.
    """
    asyncio.run(_success(status, text))


async def _success(status: int, text: str) -> None:
    import json

    memory = transport_memory([ResponseSpec(status, text=text)])
    try:
        result = await memory.transport.request(SpotifyRequest("GET", "me/"))
        try:
            expected = json.loads(text)
        except ValueError:
            expected = None
        assert result == expected
    finally:
        await memory.transport.aclose()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503, 504])
@pytest.mark.parametrize(
    "text", ['{"error":{"message":"bad","reason":"missing"}}', "bad gateway", ""]
)
def test_terminal_http_errors_preserve_fields(status: int, text: str) -> None:
    """Preserve status, message, reason and Retry-After without automatic 401 replay.

    Args:
        status: Terminal HTTP status.
        text: Original server error body.
    """
    asyncio.run(_terminal(status, text))


async def _terminal(status: int, text: str) -> None:
    memory = transport_memory(
        [ResponseSpec(status, text=text, headers={"Retry-After": "37"})],
        profile=RetryProfile(0, 0, (999,)),
    )
    try:
        with pytest.raises(SpotifyException) as caught:
            await memory.transport.request(SpotifyRequest("GET", "albums/abc"))
        expected = _synchronous_error(status, text)
        assert str(caught.value) == str(expected)
        assert caught.value.reason == expected.reason
        assert caught.value.headers.get("Retry-After") == "37"
        assert len(memory.http.requests) == 1
        assert memory.tokens[0].calls == [False]
    finally:
        await memory.transport.aclose()


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize("retries", [0, 1, 2, 3, 5])
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_status_retries_match_adapter_budget(
    method: HttpMethod, retries: int, status: int
) -> None:
    """Retain all four allowed methods and the SDK's exhaustion mapping.

    Args:
        method: Original operation method.
        retries: Original selected adapter limit.
        status: Retryable status.
    """
    asyncio.run(_status_budget(method, retries, status))


async def _status_budget(method: HttpMethod, retries: int, status: int) -> None:
    memory = transport_memory(
        [ResponseSpec(status)], profile=RetryProfile(retries, retries)
    )
    try:
        with pytest.raises(SpotifyException) as caught:
            await memory.transport.request(SpotifyRequest(method, "me/library"))
        assert caught.value.http_status == 429
        assert "Max Retries" in caught.value.msg
        assert len(memory.http.requests) == retries + 1
        assert memory.wait.delays == _adapter_delays(retries)
    finally:
        await memory.transport.aclose()


def _adapter_delays(retries: int) -> list[float]:
    delays = []
    for index in range(retries):
        delays.append(0 if index == 0 else 0.3 * 2**index)
    return delays


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("lost response"),
        httpx.ReadError("reset"),
        httpx.WriteError("lost write"),
    ],
)
def test_only_get_retries_after_ambiguous_transport_failures(
    method: HttpMethod, error: httpx.TransportError
) -> None:
    """Keep mutation responses ambiguous and preserve the bounded outer GET policy.

    Args:
        method: Original request method.
        error: Failure after connection establishment.
    """
    asyncio.run(_ambiguous(method, error))


async def _ambiguous(method: HttpMethod, error: httpx.TransportError) -> None:
    memory = transport_memory([ResponseSpec(error=error)], profile=RetryProfile(2, 2))
    try:
        with pytest.raises((RequestsConnectionError, RequestsTimeout)):
            await memory.transport.request(
                SpotifyRequest(
                    method, "playlists/abc/items", payload=["spotify:track:abc"]
                )
            )
        assert len(memory.http.requests) == (3 if method == "GET" else 1)
        assert memory.wait.delays == ([10, 20] if method == "GET" else [])
    finally:
        await memory.transport.aclose()


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("retries", [0, 1, 2])
def test_connect_retries_keep_both_original_budgets(
    method: HttpMethod, retries: int
) -> None:
    """Retain adapter connect attempts before outer GET retry limits.

    Args:
        method: Original operation.
        retries: Original adapter and outer connection limit.
    """
    asyncio.run(_connect(method, retries))


async def _connect(method: HttpMethod, retries: int) -> None:
    memory = transport_memory(
        [ResponseSpec(error=httpx.ConnectError("unreachable"))],
        profile=RetryProfile(retries, retries),
    )
    try:
        with pytest.raises(RequestsConnectionError):
            await memory.transport.request(SpotifyRequest(method, "me/"))
        outer = retries + 1 if method == "GET" else 1
        assert len(memory.http.requests) == (retries + 1) * outer
    finally:
        await memory.transport.aclose()


def test_rate_limits_preserve_rotation_and_return_success() -> None:
    """Rotate primary, app5, app6 in original order without sleeping for 429."""
    asyncio.run(_rotation())


async def _rotation() -> None:
    tokens = (TokenMemory(), TokenMemory("app5"), TokenMemory("app6"))
    memory = transport_memory(
        [ResponseSpec(429), ResponseSpec(429), ResponseSpec(200, {"ok": True})], tokens
    )
    try:
        assert await memory.transport.request(SpotifyRequest("GET", "me/")) == {
            "ok": True
        }
        assert [
            request.headers["authorization"] for request in memory.http.requests
        ] == ["Bearer primary-token", "Bearer app5-token", "Bearer app6-token"]
        assert tokens[1].calls == [True, False]
        assert tokens[2].calls == [True, False]
        assert memory.wait.delays == []
    finally:
        await memory.transport.aclose()


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("refresh failed"),
        SpotifyAppAuthenticationError("no cache"),
        KeyError("malformed token"),
        TypeError("malformed token"),
        AttributeError("malformed token"),
        EOFError("closed interactive input"),
    ],
)
def test_failed_rotation_skips_unusable_credentials(failure: Exception) -> None:
    """Skip each unusable app without repeating its HTTP request.

    Args:
        failure: Original credential refresh failure.
    """
    asyncio.run(_failed_rotation(failure))


async def _failed_rotation(failure: Exception) -> None:
    tokens = (TokenMemory(), TokenMemory("app5", failure), TokenMemory("app6"))
    memory = transport_memory(
        [ResponseSpec(429), ResponseSpec(payload={"ok": True})], tokens
    )
    try:
        assert await memory.transport.request(SpotifyRequest("GET", "me/")) == {
            "ok": True
        }
        assert len(memory.http.requests) == 2
        assert tokens[1].calls == [True]
        assert tokens[2].calls == [True, False]
    finally:
        await memory.transport.aclose()


def test_all_apps_rate_limited_preserves_final_retry_after() -> None:
    """Return the final response's case-insensitive header after ordered exhaustion."""
    asyncio.run(_exhausted())


async def _exhausted() -> None:
    memory = transport_memory(
        [
            ResponseSpec(429, headers={"Retry-After": "9"}),
            ResponseSpec(429, headers={"Retry-After": "37"}),
        ],
        (TokenMemory(), TokenMemory("app5")),
    )
    try:
        with pytest.raises(SpotifyException) as caught:
            await memory.transport.request(SpotifyRequest("GET", "me/"))
        assert len(memory.http.requests) == 2
        assert caught.value.headers.get("Retry-After") == "37"
        assert (
            memory.output.lines[-1]
            == "All configured Spotify credential sets are rate-limited or unavailable."
        )
    finally:
        await memory.transport.aclose()


def _synchronous_error(status: int, text: str) -> SpotifyException:
    session = SynchronousRecorder(
        ResponseSpec(status, text=text, headers={"Retry-After": "37"})
    )
    baseline = Spotify(auth="primary-token", requests_session=session)
    try:
        with pytest.raises(SpotifyException) as expected:
            baseline._get("albums/abc")
        return expected.value
    finally:
        session.close()


@dataclass
class InterruptedToken(TokenMemory):
    """Simulate connection loss inside SDK token acquisition before any API call.

    Args:
        interruptions: Remaining OAuth connection failures.
        error: Original SDK network exception.
    """

    interruptions: int = 1
    error: Exception = field(default_factory=RequestsTimeout)

    def token(self) -> str:
        """Read a token after the configured OAuth network failures.

        Returns:
            Current deterministic access token.

        Raises:
            Exception: Configured original SDK network failure.
        """
        result = super().token()
        if self.interruptions > 0:
            self.interruptions -= 1
            raise self.error
        return result


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize(
    "error", [RequestsConnectionError("OAuth reset"), RequestsTimeout("OAuth timeout")]
)
def test_oauth_network_failure_uses_the_original_outer_method_retry_profile(
    method: HttpMethod, error: Exception
) -> None:
    """Include token acquisition inside the same interrupted-request boundary.

    Args:
        method: Original API operation.
        error: Original SDK authentication transport failure.
    """
    asyncio.run(_oauth_interruption(method, error))


async def _oauth_interruption(method: HttpMethod, error: Exception) -> None:
    source = InterruptedToken(error=error)
    memory = transport_memory(
        [ResponseSpec(payload={"ok": True})], (source,), RetryProfile(2, 2)
    )
    try:
        if method == "GET":
            assert await memory.transport.request(SpotifyRequest(method, "me/")) == {
                "ok": True
            }
            assert source.calls == [False, False]
            assert memory.wait.delays == [10]
            assert len(memory.http.requests) == 1
            return
        with pytest.raises(type(error)) as caught:
            await memory.transport.request(SpotifyRequest(method, "me/library"))
        assert caught.value is error
        assert source.calls == [False]
        assert memory.http.requests == []
        assert memory.wait.delays == []
    finally:
        await memory.transport.aclose()
