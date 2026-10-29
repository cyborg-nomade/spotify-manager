"""Keep synchronous Python client creation at its original cache-miss boundary."""

from dataclasses import dataclass
from typing import cast

from spotipy import Spotify

from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.infrastructure.lookup_resources import ClientFactory
from spotify_manager.infrastructure.lookup_resources import NativeClientFactory
from spotify_manager.infrastructure.spotify_compat import legacy_spotify


@dataclass(frozen=True)
class PythonClientFactory:
    """Adapt a caller-owned factory without acquiring or closing its client early.

    Args:
        source: Original synchronous Python client factory.
    """

    source: ClientFactory | NativeClientFactory

    def __bool__(self) -> bool:
        """Preserve the original missing-client fallback decision.

        Returns:
            Original factory truthiness.
        """
        return bool(self.source)

    def client(self) -> SpotifyClient:
        """Observe the original factory only when cache lookup requires it.

        Returns:
            Awaitable SDK calls with the original caller's session ownership.
        """
        return legacy_spotify(cast(Spotify, self.source.client()))
