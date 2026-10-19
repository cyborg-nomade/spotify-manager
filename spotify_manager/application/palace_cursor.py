"""Coordinate manual Palace cursor updates after the original live mirror preflight."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.palace_effects import PalaceStateAccess
from spotify_manager.application.palace_mirror import SavedMirror
from spotify_manager.application.palace_values import AlphabeticalCursorUpdate
from spotify_manager.application.palace_values import PalaceOfMemoryConfigError
from spotify_manager.models.your_library import YourLibraryAlbum


@dataclass(frozen=True)
class PalaceCursor:
    """Retain original preflight, authority and complete cursor replacement boundaries.

    Args:
        progress: Original optional stage presentation adapter.
        mirror: Named canonical live mirror stage.
        state: Original durable cursor authority resolver.
        record: Original complete next-position serialization and write clock.
    """

    progress: Callable[[str], None]
    mirror: SavedMirror
    state: Callable[[], PalaceStateAccess]
    record: Callable[[int, YourLibraryAlbum], dict[str, object]]

    def update(self, position: int) -> AlphabeticalCursorUpdate:
        """Refresh live facts before validating and replacing the next manual position.

        Args:
            position: Original one-based requested cursor, retaining bool tolerance.

        Returns:
            Original next position, full saved album and live-refresh outcome.

        Raises:
            PalaceOfMemoryConfigError: Original position is outside the live mirror.
        """
        self.progress("Refreshing the saved-album mirror")
        albums, refresh = self.mirror.run()
        if not 1 <= position <= len(albums):
            raise PalaceOfMemoryConfigError(
                f"Alphabetical cursor must be between 1 and {len(albums)}."
            )
        next_index = position - 1
        previous = albums[(next_index - 1) % len(albums)]
        state = self.state()
        state.load()
        state.save(self.record(next_index, previous))
        return AlphabeticalCursorUpdate(next_index, albums[next_index], refresh)
