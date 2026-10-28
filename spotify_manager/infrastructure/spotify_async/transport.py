"""Pooled native Spotify HTTP with explicit per-attempt credential snapshots."""

import asyncio
from dataclasses import dataclass
from dataclasses import field

import httpx
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.spotify_async import AsyncWait
from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.infrastructure.cli_cancellation import INVOCATION_WAIT
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.infrastructure.spotify_async.credentials import Credentials
from spotify_manager.infrastructure.spotify_async.credentials import CredentialToken
from spotify_manager.infrastructure.spotify_async.requests import decode_response
from spotify_manager.infrastructure.spotify_async.requests import request_body
from spotify_manager.infrastructure.spotify_async.requests import request_url
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.infrastructure.spotify_async.retries import retry_connect
from spotify_manager.infrastructure.spotify_async.retries import retry_status
from spotify_manager.infrastructure.spotify_async.retries import transport_error


class AsyncSleep:
    """Wait for retry delays without occupying a worker thread."""

    async def sleep(self, seconds: float) -> None:
        """Await the selected delay.

        Args:
            seconds: Existing retry delay, including a zero adapter backoff.
        """
        if seconds:
            await INVOCATION_WAIT.sleep(seconds)


@dataclass
class RequestAttempts:
    """Keep original rotation and GET connection budgets local to one request.

    Args:
        attempted: Credential indices already tried by this request.
        connections: Completed outer GET connection retries.
        credential: Selected app retained across this request's connection retries.
    """

    attempted: set[int] = field(default_factory=set)
    connections: int = 0
    credential: int = 0


@dataclass
class NativeSpotifyTransport:
    """Own one loop's pooled HTTP client and credential states.

    Args:
        http: Caller-owned pooled native client, closed by this transport.
        credentials: Ordered OAuth/cache states.
        profile: Original selected adapter/connection retry profile.
        wait: Awaited delay owner.
        language: Original optional Accept-Language value.
        close_resources: Whether this transport owns the shared pool and credentials.
    """

    http: httpx.AsyncClient
    credentials: Credentials
    profile: RetryProfile = field(default_factory=RetryProfile)
    wait: AsyncWait = field(default_factory=AsyncSleep)
    language: str | None = None
    close_resources: bool = True
    _loop: asyncio.AbstractEventLoop = field(init=False, repr=False)
    _closing: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Bind the client to its construction loop before any I/O."""
        self._loop = asyncio.get_running_loop()

    def _check_owner(self) -> None:
        current = asyncio.get_running_loop()
        if self._closed:
            raise RuntimeError("Spotify transport is closed.")
        if self._loop is not current:
            raise RuntimeError("Spotify transport belongs to another event loop.")

    def retry_view(self, profile: RetryProfile) -> NativeSpotifyTransport:
        """Borrow the pool and refresh locks with independent rotation and retries.

        Args:
            profile: Original caller-specific request retry policy.

        Returns:
            A view whose cleanup leaves the underlying resources with this owner.

        Raises:
            RuntimeError: This owner is closing, closed or on another loop.
        """
        self._check_owner()
        if self._closing is not None:
            raise RuntimeError("Spotify transport is closing.")
        credentials = Credentials(self.credentials.entries, self.credentials.output)
        return NativeSpotifyTransport(
            self.http, credentials, profile, self.wait, self.language, False
        )

    async def request(self, request: SpotifyRequest) -> SpotifyJson:
        """Await a direct request with the original rotation and failure budgets.

        Args:
            request: Complete request values.

        Returns:
            Original decoded Spotify JSON.

        Raises:
            SpotifyException: Original terminal HTTP failure.
            RequestsConnectionError: Original terminal transport failure.
            RequestsTimeout: Original terminal timeout.
            RuntimeError: Closed or cross-loop use.
        """
        self._check_owner()
        if self._closing is not None:
            raise RuntimeError("Spotify transport is closing.")
        attempts = RequestAttempts(credential=self.credentials.active)
        while True:
            attempts.attempted.add(attempts.credential)
            try:
                token = await self.credentials.read(attempts.credential)
                return await self._request(request, token)
            except SpotifyException as error:
                await self._rate_limit(error, attempts)
            except (RequestsConnectionError, RequestsTimeout) as error:
                await self._connection_failure(request, attempts, error)

    async def _request(
        self, request: SpotifyRequest, token: CredentialToken
    ) -> SpotifyJson:
        headers = {
            "Authorization": f"Bearer {token.value}",
            "Content-Type": "application/json",
        }
        if self.language is not None:
            headers["Accept-Language"] = self.language
        wire = self.http.build_request(
            request.method,
            request_url(request),
            headers=headers,
            content=request_body(request),
        )
        response = await self._send(wire)
        return decode_response(response)

    async def _send(self, request: httpx.Request) -> httpx.Response:
        retry = self.profile.adapter()
        while True:
            try:
                response = await self.http.send(request)
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                retry = await retry_connect(retry, request, error, self.wait)
                continue
            except httpx.TransportError as error:
                raise transport_error(error) from error
            if not retry.is_retry(request.method, response.status_code):
                return response
            retry = await retry_status(retry, response, self.wait)

    async def _rate_limit(
        self, error: SpotifyException, attempts: RequestAttempts
    ) -> None:
        if error.http_status != 429:
            raise error
        index = attempts.credential
        label = self.credentials.entries[index].source.label
        self.credentials.output.echo(
            f"Spotify rate limit reached for credentials {label}."
        )
        if await self.credentials.rotate(index, attempts.attempted):
            attempts.credential = self.credentials.active
            return
        self.credentials.output.echo(
            "All configured Spotify credential sets are rate-limited or unavailable."
        )
        raise error

    async def _connection_failure(
        self,
        request: SpotifyRequest,
        attempts: RequestAttempts,
        error: RequestsConnectionError | RequestsTimeout,
    ) -> None:
        limit = min(self.profile.retries, 3)
        if request.method != "GET" or attempts.connections >= limit:
            raise error
        delay = 10 * (2**attempts.connections)
        attempts.connections += 1
        self.credentials.output.echo(
            f"Spotify connection interrupted; retrying in {delay} seconds "
            f"(attempt {attempts.connections + 1} of {limit + 1})."
        )
        await self.wait.sleep(delay)

    async def aclose(self) -> None:
        """Close owned resources on their original event loop.

        Raises:
            RuntimeError: Attempted cleanup on a different loop.
        """
        if self._closed:
            return
        self._check_owner()
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        await finish_blocking(self._closing)

    async def rotate_credentials(self) -> str:
        """Rotate explicitly on the owning loop without starting an HTTP request.

        Returns:
            Newly active credential label.

        Raises:
            RuntimeError: This transport is closed or belongs to another loop.
            SpotifyAppAuthenticationError: No alternate app is usable.
        """
        self._check_owner()
        if self._closed or self._closing is not None:
            raise RuntimeError("Spotify transport is closed.")
        return await self.credentials.manual_rotation()

    async def refresh_all_app_tokens(self) -> tuple[str, ...]:
        """Refresh each app on the loop that owns its credential locks.

        Returns:
            Original refreshed credential labels.

        Raises:
            RuntimeError: This transport is closed or belongs to another loop.
        """
        self._check_owner()
        if self._closed or self._closing is not None:
            raise RuntimeError("Spotify transport is closed.")
        return await self.credentials.refresh_all()

    async def _close(self) -> None:
        if not self.close_resources:
            self._closed = True
            return
        try:
            await self.http.aclose()
        finally:
            try:
                await self.credentials.close()
            finally:
                self._closed = True
