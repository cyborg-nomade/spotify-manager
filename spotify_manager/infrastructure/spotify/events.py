"""Own the optional SDK event subscription at its compatibility boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotipy import Spotify

from spotify_manager.application.ports.runtime import Messages


type EventSetter = Callable[[Messages | None], Messages | None]


@dataclass
class SpotifyEvents:
    """Subscribe and restore the exact hook observed at the original SDK boundary.

    Args:
        spotify: Original SDK client, absent for export-only analysis.
    """

    spotify: Spotify | None
    _setter: EventSetter | None = field(init=False, repr=False)
    _previous: Messages | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture the optional dynamic SDK method once, retaining binding timing."""
        setter = getattr(self.spotify, "set_event_callback", None)
        self._setter = cast(EventSetter, setter) if callable(setter) else None

    def subscribe(self, output: Messages) -> None:
        """Subscribe the invoking interface's named message owner.

        Args:
            output: Original message observer for this invocation.
        """
        if self._setter is not None:
            self._previous = self._setter(output)

    def restore(self) -> None:
        """Restore the original observer using the same captured SDK method."""
        if self._setter is not None:
            self._setter(self._previous)
