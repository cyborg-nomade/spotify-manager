"""Named HTTP, credential and wait owners for native transport tests."""

import asyncio
import json
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import httpx
import requests

from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.client.events import SpotifyOutput
from spotify_manager.infrastructure.spotify_async.blocking import BlockingOAuth
from spotify_manager.infrastructure.spotify_async.credentials import Credential
from spotify_manager.infrastructure.spotify_async.credentials import Credentials
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.infrastructure.spotify_async.transport import (
    NativeSpotifyTransport,
)


@dataclass
class TokenMemory:
    """Own one test credential without reading a cache.

    Args:
        label: Non-secret app label.
        failure: Optional original force-refresh failure.
    """

    label: str = "primary"
    failure: Exception | None = None
    calls: list[bool] = field(default_factory=list, init=False)
    closed: bool = field(default=False, init=False)

    def token(self) -> str:
        """Record one token read after credential selection.

        Returns:
            Non-secret deterministic token.
        """
        self.calls.append(False)
        return self.label + "-token"

    def refresh(self) -> None:
        """Record the original force-refresh boundary.

        Raises:
            Exception: Configured original authentication failure.
        """
        self.calls.append(True)
        if self.failure is not None:
            raise self.failure

    def close(self) -> None:
        """Record session cleanup."""
        self.closed = True


@dataclass
class WaitMemory:
    """Record delays without sleeping or consulting a clock."""

    delays: list[float] = field(default_factory=list)

    async def sleep(self, seconds: float) -> None:
        """Accept an original retry delay.

        Args:
            seconds: Selected backoff.
        """
        self.delays.append(seconds)


@dataclass
class OutputMemory:
    """Record non-secret diagnostic events."""

    lines: list[str] = field(default_factory=list)

    def echo(self, message: str) -> None:
        """Record a complete event.

        Args:
            message: Original diagnostic.
        """
        self.lines.append(message)


@dataclass(frozen=True)
class ResponseSpec:
    """Describe one mocked response or transport failure.

    Args:
        status: Original response status.
        payload: JSON response data.
        text: Optional raw body overriding JSON.
        headers: Original response headers.
        error: Optional native transport failure.
    """

    status: int = 200
    payload: SpotifyJson = None
    text: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    error: httpx.TransportError | None = None


def _successful_responses() -> list[ResponseSpec]:
    return [ResponseSpec()]


@dataclass
class HttpMemory:
    """Serve scripted responses through HTTPX's required external test hook.

    Args:
        responses: Response sequence, repeating its last entry.
    """

    responses: list[ResponseSpec] = field(default_factory=_successful_responses)
    requests: list[httpx.Request] = field(default_factory=list, init=False)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        """Handle HTTPX MockTransport's required callable interface.

        Args:
            request: Actual prepared native HTTP request.

        Returns:
            Scripted response.

        Raises:
            httpx.TransportError: Original scripted transport failure.
        """
        index = min(len(self.requests), len(self.responses) - 1)
        self.requests.append(request)
        response = self.responses[index]
        if response.error is not None:
            raise response.error
        if response.text is not None:
            return httpx.Response(
                response.status, text=response.text, headers=response.headers
            )
        return httpx.Response(
            response.status, json=response.payload, headers=response.headers
        )


@dataclass
class TransportMemory:
    """Group the actual native client and observable external resources.

    Args:
        transport: Real transport under test.
        http: HTTP request/response observations.
        tokens: Original credential sources.
        wait: Retry delay observations.
        output: Diagnostic observations.
    """

    transport: NativeSpotifyTransport
    http: HttpMemory
    tokens: tuple[TokenMemory, ...]
    wait: WaitMemory
    output: OutputMemory


def transport_memory(
    responses: list[ResponseSpec] | None = None,
    tokens: tuple[TokenMemory, ...] | None = None,
    profile: RetryProfile | None = None,
    http: HttpMemory | None = None,
) -> TransportMemory:
    """Construct real HTTPX/credential resources against named in-memory edges.

    Args:
        responses: Scripted HTTP outcomes.
        tokens: Original ordered credential sources.
        profile: Original selected retry policy.
        http: Optional named HTTP responder.

    Returns:
        Transport and all observations; caller closes the transport.
    """
    http = http or HttpMemory(responses or [ResponseSpec()])
    sources = tokens or (TokenMemory(),)
    blocking = BlockingOAuth(asyncio.Semaphore(2))
    entries = []
    for source in sources:
        entries.append(Credential(source, blocking))
    output = OutputMemory()
    credentials = Credentials(tuple(entries), SpotifyOutput(output))
    # HTTPX MockTransport explicitly requires a request-handler function.
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(http.handle), follow_redirects=True
    )
    wait = WaitMemory()
    native = NativeSpotifyTransport(
        client, credentials, profile or RetryProfile(), wait
    )
    return TransportMemory(native, http, sources, wait, output)


class SynchronousRecorder(requests.Session):
    """Record the installed SDK's fully prepared Requests contracts."""

    def __init__(self, response: ResponseSpec | None = None) -> None:
        """Initialize a session that performs no socket operations.

        Args:
            response: Original SDK response, defaulting to a successful object.
        """
        super().__init__()
        self.response = response or ResponseSpec(payload={"contract": True})
        self.observed: requests.PreparedRequest | None = None

    def request(
        self, method: str, url: str | bytes, *args: Any, **kwargs: Any
    ) -> requests.Response:
        """Prepare the SDK's original request without sending it.

        Args:
            method: Original SDK method.
            url: Original SDK URL.
            *args: External Requests positional options.
            **kwargs: External Requests call boundary.

        Returns:
            Successful JSON response with the original prepared request attached.
        """
        request = requests.Request(
            method,
            url,
            headers=kwargs.get("headers"),
            data=kwargs.get("data"),
            params=kwargs.get("params"),
        ).prepare()
        self.observed = request
        response = requests.Response()
        response.status_code = self.response.status
        response.headers.update(self.response.headers)
        response._content = (
            self.response.text.encode()
            if self.response.text is not None
            else json.dumps(self.response.payload).encode()
        )
        response.request = request
        response.url = str(request.url)
        return response
