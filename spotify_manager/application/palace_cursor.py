"""Coordinate manual Palace cursor updates after the original live mirror preflight."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.palace_effects import PalaceStateAccess
from spotify_manager.application.palace_mirror import SavedMirror
from spotify_manager.application.palace_values import AlphabeticalCursorUpdate
from spotify_manager.application.palace_values import PalaceOfMemoryConfigError
from spotify_manager.models.your_library import YourLibraryAlbum


class CursorAccess(Protocol):
    """Present cursor progress and persist complete cursor records."""

    def progress(self, message: str) -> None:
        """Present the current stage.

        Args:
            message: Visible stage text.
        """
        ...

    def state_access(self) -> PalaceStateAccess:
        """Resolve cursor authority at its original post-refresh boundary.

        Returns:
            Durable cursor store.
        """
        ...

    def cursor_payload(self, index: int, album: YourLibraryAlbum) -> dict[str, object]:
        """Observe the write clock and encode a complete cursor replacement.

        Args:
            index: Next zero-based position.
            album: Previously visited album.

        Returns:
            Complete replacement record.
        """
        ...


@dataclass(frozen=True)
class PalaceCursor:
    """Retain original preflight, authority and complete cursor replacement boundaries.

    Args:
        access: Progress, cursor store and write-clock observations.
        mirror: Named canonical live mirror stage.
    """

    access: CursorAccess
    mirror: SavedMirror

    async def update(self, position: int) -> AlphabeticalCursorUpdate:
        """Refresh live facts before validating and replacing the next manual position.

        Args:
            position: Original one-based requested cursor, retaining bool tolerance.

        Returns:
            Original next position, full saved album and live-refresh outcome.

        Raises:
            PalaceOfMemoryConfigError: Original position is outside the live mirror.
        """
        self.access.progress("Refreshing the saved-album mirror")
        albums, refresh = await self.mirror.run()
        if not 1 <= position <= len(albums):
            raise PalaceOfMemoryConfigError(
                f"Alphabetical cursor must be between 1 and {len(albums)}."
            )
        next_index = position - 1
        previous = albums[(next_index - 1) % len(albums)]
        state = self.access.state_access()
        await state.load()
        await state.save(self.access.cursor_payload(next_index, previous))
        return AlphabeticalCursorUpdate(next_index, albums[next_index], refresh)
