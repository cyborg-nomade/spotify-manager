"""Own the optional SDK event subscription at its compatibility boundary."""

from collections.abc import Callable
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.client.events import SPOTIFY_MESSAGES
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.infrastructure.spotify_compat import LegacySpotifyClient


type EventSetter = Callable[[Messages | None], Messages | None]


@dataclass
class SpotifyEvents:
    """Subscribe and restore the exact hook observed at the original SDK boundary.

    Args:
        spotify: Original SDK client, absent for export-only analysis.
    """

    spotify: Spotify | AsyncSpotify | None
    _setter: EventSetter | None = field(init=False, repr=False)
    _previous: Messages | None = field(default=None, init=False, repr=False)
    _token: Token[Messages | None] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture the optional dynamic SDK method once, retaining binding timing."""
        if isinstance(self.spotify, AsyncSpotify):
            self._setter = None
            return
        observed = self.spotify
        if isinstance(observed, LegacySpotifyClient):
            observed = observed.source
        setter = getattr(observed, "set_event_callback", None)
        self._setter = cast(EventSetter, setter) if callable(setter) else None

    def subscribe(self, output: Messages) -> None:
        """Subscribe the invoking interface's named message owner.

        Args:
            output: Original message observer for this invocation.
        """
        if isinstance(self.spotify, AsyncSpotify):
            self._token = SPOTIFY_MESSAGES.set(output)
        elif self._setter is not None:
            self._previous = self._setter(output)

    def restore(self) -> None:
        """Restore the original observer using the same captured SDK method."""
        if self._token is not None:
            SPOTIFY_MESSAGES.reset(self._token)
            self._token = None
        elif self._setter is not None:
            self._setter(self._previous)
