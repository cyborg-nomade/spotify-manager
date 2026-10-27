"""Coordinate cache refresh per credential without locking Spotify request I/O."""

import asyncio
from dataclasses import dataclass
from dataclasses import field

from requests.exceptions import RequestException
from spotipy.oauth2 import SpotifyOauthError

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.client import SpotifyAppAuthenticationError
from spotify_manager.infrastructure.spotify_async.blocking import BlockingOAuth
from spotify_manager.infrastructure.spotify_async.blocking import TokenSource


AUTH_FAILURES = (
    SpotifyAppAuthenticationError,
    SpotifyOauthError,
    RequestException,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    EOFError,
)


@dataclass
class Credential:
    """Serialize only one credential's cache lookup and refresh.

    Args:
        source: Isolated OAuth/cache owner.
        blocking: Bounded off-loop execution owner.
    """

    source: TokenSource
    blocking: BlockingOAuth
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def token(self) -> str:
        """Read a token after preceding refreshes have published their cache.

        Returns:
            Current access token.
        """
        async with self.lock:
            return await self.blocking.token(self.source)

    async def refresh(self) -> None:
        """Complete rotation refresh before publishing this app as active."""
        async with self.lock:
            await self.blocking.refresh(self.source)

    async def close(self) -> None:
        """Finish outstanding cache work before closing its session."""
        async with self.lock:
            await self.blocking.close(self.source)


@dataclass(frozen=True)
class CredentialToken:
    """Snapshot the credential used by one request attempt.

    Args:
        index: Original ordered credential index.
        label: Non-secret app label.
        value: Access token, excluded from representation.
    """

    index: int
    label: str
    value: str = field(repr=False)


@dataclass
class Credentials:
    """Retain rotation order while leaving unrelated requests free to overlap.

    Args:
        entries: Configured credential states in original order.
        output: Existing safe diagnostic owner.
    """

    entries: tuple[Credential, ...]
    output: Messages
    active: int = field(default=0, init=False)
    rotation: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        """Reject an empty configuration before attempting any requests."""
        if not self.entries:
            raise ValueError("At least one labeled Spotify auth manager is required.")

    async def read(self, index: int) -> CredentialToken:
        """Read the request's selected credential without locking HTTP I/O.

        Args:
            index: Credential selected by this request's original rotation sequence.

        Returns:
            Stable credential snapshot for this attempt.
        """
        entry = self.entries[index]
        return CredentialToken(index, entry.source.label, await entry.token())

    async def rotate(self, previous: int, attempted: set[int]) -> bool:
        """Activate the next usable untried credential after an observed 429.

        Args:
            previous: Credential index that received the rate limit.
            attempted: Credential indices already attempted by this invocation.

        Returns:
            Whether a refreshed alternate is available.
        """
        async with self.rotation:
            if self.active != previous and self.active not in attempted:
                attempted.add(self.active)
                return True
            return await self._next(attempted)

    async def _next(self, attempted: set[int]) -> bool:
        for distance in range(1, len(self.entries) + 1):
            index = (self.active + distance) % len(self.entries)
            if index in attempted:
                continue
            attempted.add(index)
            if await self._activate(index):
                return True
        return False

    async def _activate(self, index: int) -> bool:
        entry = self.entries[index]
        label = entry.source.label
        self.output.echo(
            f"Switching Spotify credentials to {label} and refreshing its token."
        )
        try:
            await entry.refresh()
        except SpotifyAppAuthenticationError as error:
            self.output.echo(str(error))
            return False
        except AUTH_FAILURES:
            self.output.echo(
                f"Spotify credentials {label} could not refresh; "
                "trying the next configured app."
            )
            return False
        self.active = index
        self.output.echo(f"Spotify requests now use credentials {label}.")
        return True

    async def close(self) -> None:
        """Close each credential after its pending refresh completes."""
        pending = []
        for entry in self.entries:
            pending.append(entry.close())
        results = await asyncio.gather(*pending, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
