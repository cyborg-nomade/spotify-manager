"""Caller-owned mirror, history, catalog, cursor and accepted-effect seams."""

from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.palace_values import PalaceOfMemorySummary
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.palace_values import HistoricalAlbumSelection
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.models.your_library import YourLibraryAlbum


class PalaceStateAccess(Protocol):
    """Read original cursor authority and accept complete replacement checkpoints."""

    def load(self) -> dict[str, object]:
        """Read original complete durable cursor facts.

        Returns:
            Original mutable cursor namespace.
        """

    def save(self, payload: dict[str, object], /) -> object:
        """Accept original complete cursor replacement.

        Args:
            payload: Original next-position facts.

        Returns:
            Original storage acknowledgment, ignored by the runner.
        """


class PalaceEffects(Protocol):
    """Original live authority, catalog reads, presentation and persistence."""

    def progress(self, message: str) -> None:
        """Present original optional stage text.

        Args:
            message: Original visible stage.
        """

    def refresh(self) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
        """Refresh original canonical live mirror even in preview.

        Returns:
            Original complete saved facts and publication result.
        """

    def state_access(self) -> PalaceStateAccess:
        """Resolve original caller-owned durable cursor access.

        Returns:
            Original namespace or explicit legacy-path boundary.
        """

    def start_index(
        self,
        albums: tuple[YourLibraryAlbum, ...],
        manual: str | None,
        state: dict[str, object],
    ) -> int:
        """Resolve original manual reference or validated durable cursor facts.

        Args:
            albums: Refreshed canonical mirror.
            manual: Original optional user reference.
            state: Original loaded cursor document.

        Returns:
            Original selected zero-based position.
        """

    def historical(
        self,
    ) -> tuple[datetime, date, int, tuple[HistoricalAlbumSelection, ...]]:
        """Gather original history and Random.org selection facts.

        Returns:
            Original timestamp, cutoff, eligible count and selected albums.
        """

    def playlist(self, recheck: bool) -> PlaylistState:
        """Read original initial or final live membership authority.

        Args:
            recheck: Whether this is the final pre-write live check.

        Returns:
            Original valid complete destination facts.
        """

    def first_track(self, album: SpotifyAlbum) -> SpotifyFirstTrack:
        """Read the original first playable marker without reordering the response.

        Args:
            album: Original resolved release.

        Returns:
            Original complete first marker.
        """

    def search(self, artist: str, album: str) -> SpotifyAlbum | None:
        """Search only after the original saved-edition policy finds no match.

        Args:
            artist: Original expected artist spelling.
            album: Original expected historical title.

        Returns:
            Original qualified remote release or none.
        """

    def append(self, pending: tuple[SpotifyFirstTrack, ...]) -> None:
        """Accept the original retry-wrapped distinct marker append.

        Args:
            pending: Original pending markers in selection order.
        """

    def echo(self, message: str) -> None:
        """Present original accepted-append confirmation.

        Args:
            message: Original completion text.
        """

    def cursor_payload(
        self, next_index: int, last: YourLibraryAlbum
    ) -> dict[str, object]:
        """Build original replacement cursor with its independent write timestamp.

        Args:
            next_index: Original next mirror position.
            last: Original last selected saved album.

        Returns:
            Original complete replacement namespace.
        """

    def audit(self, summary: PalaceOfMemorySummary) -> None:
        """Accept original real-run audit after the cursor checkpoint.

        Args:
            summary: Original complete selected outcome.
        """
