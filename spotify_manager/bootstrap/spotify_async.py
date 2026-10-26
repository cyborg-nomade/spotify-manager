"""Construct one loop-owned native Spotify runtime; activate callers in Item 9."""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from types import TracebackType

import httpx

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.client.events import SpotifyOutput
from spotify_manager.infrastructure.spotify_async.blocking import BlockingOAuth
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.infrastructure.spotify_async.credentials import Credential
from spotify_manager.infrastructure.spotify_async.credentials import Credentials
from spotify_manager.infrastructure.spotify_async.oauth import OAuthProvisioner
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.infrastructure.spotify_async.transport import (
    NativeSpotifyTransport,
)
from spotify_manager.settings import Settings


@dataclass(frozen=True)
class SpotifyRuntimeOptions:
    """Group transport capacity and the original selected retry profile.

    Args:
        retries: Original caller-selected retry settings.
        connections: Maximum pooled Spotify connections; a capacity, not a quota.
        oauth_workers: Maximum simultaneous blocking SDK/cache operations.
        interactive: Original caller's permission for interactive rotation.
    """

    retries: RetryProfile = field(default_factory=RetryProfile)
    connections: int = 10
    oauth_workers: int = 2
    interactive: bool = False

    def __post_init__(self) -> None:
        """Reject invalid resource capacities before constructing any sessions."""
        if self.connections < 1 or self.oauth_workers < 1:
            raise ValueError("Spotify resource capacities must be positive.")


@dataclass
class AsyncSpotifyRuntime:
    """Own the native client from one async entry boundary through cleanup.

    Args:
        configuration: Original settings with isolated OAuth cache locations.
        options: Capacity and retry settings.
        output: Invocation-owned diagnostic output.
    """

    configuration: Settings = field(repr=False)
    options: SpotifyRuntimeOptions = field(default_factory=SpotifyRuntimeOptions)
    output: Messages | None = None
    _transport: NativeSpotifyTransport | None = field(
        default=None, init=False, repr=False
    )

    async def __aenter__(self) -> AsyncSpotify:
        """Build OAuth resources off-loop and return the named native adapter.

        Returns:
            Client owned by this async context.

        Raises:
            RuntimeError: This runtime is already entered.
        """
        if self._transport is not None:
            raise RuntimeError("Spotify runtime cannot be entered twice.")
        blocking = BlockingOAuth(asyncio.Semaphore(self.options.oauth_workers))
        provisioner = OAuthProvisioner(self.configuration, self.options.interactive)
        sources = await blocking.open_sources(provisioner)
        entries = []
        for source in sources:
            entries.append(Credential(source, blocking))
        credentials = Credentials(tuple(entries), SpotifyOutput(self.output))
        try:
            http = _http_client(self.options)
        except ValueError, OSError, ImportError:
            await credentials.close()
            raise
        self._transport = NativeSpotifyTransport(
            http, credentials, self.options.retries
        )
        return AsyncSpotify(self._transport)

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close HTTP and OAuth resources before leaving their event loop.

        Args:
            kind: Original context failure type.
            error: Original context failure.
            traceback: Original context traceback.
        """
        if self._transport is not None:
            await self._transport.aclose()


def _http_client(options: SpotifyRuntimeOptions) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=10,
        follow_redirects=True,
        limits=httpx.Limits(
            max_connections=options.connections,
            max_keepalive_connections=options.connections,
        ),
    )
