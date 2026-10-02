"""Coordinate original Palace live-mirror paging and conditional publication."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.models.your_library import YourLibraryAlbum


@dataclass(frozen=True)
class SavedAlbumPage:
    """Complete original parsed rows and raw-page continuation facts.

    Args:
        albums: Original usable converted models in raw row order.
        rows: Original raw row count, including unusable rows.
        has_next: Original next-link truthiness.
    """

    albums: tuple[YourLibraryAlbum, ...]
    rows: int
    has_next: bool


class SavedMirrorEffects(Protocol):
    """Original live rows, mirror authority, replacement and preflight audit seams."""

    def previous(self) -> tuple[YourLibraryAlbum, ...]:
        """Read original usable existing mirror, or empty when it is missing.

        Returns:
            Original complete previous mirror facts.
        """

    def progress(self, message: str) -> None:
        """Present original optional paging progress.

        Args:
            message: Original visible page stage.
        """

    def page(self, offset: int) -> SavedAlbumPage:
        """Read and parse original live rows through caller-owned retry semantics.

        Args:
            offset: Original raw-row offset.

        Returns:
            Original parsed rows and continuation facts.
        """

    def canonical(self, albums: list[YourLibraryAlbum]) -> tuple[YourLibraryAlbum, ...]:
        """Apply original newest-value deduplication and canonical collation.

        Args:
            albums: Original gathered usable models.

        Returns:
            Original canonical ordered mirror.
        """

    def replace(self, albums: tuple[YourLibraryAlbum, ...]) -> str | None:
        """Back up and replace the original mirror before publication acknowledgment.

        Args:
            albums: Original complete canonical replacement.

        Returns:
            Original backup path when a previous file exists.
        """

    def clock(self) -> datetime:
        """Read original independent completion time after replacement.

        Returns:
            Original UTC preflight completion timestamp.
        """

    def audit(self, refresh: SavedAlbumRefresh) -> None:
        """Accept the original preflight audit, including unchanged mirrors.

        Args:
            refresh: Original complete refresh facts.
        """


@dataclass(frozen=True)
class SavedMirror:
    """Gather complete live authority before publishing an original canonical mirror.

    Args:
        effects: Original read, ordering, replacement and audit seams.
        minimum: Original minimum usable mirror size.
    """

    effects: SavedMirrorEffects
    minimum: int = 5

    def run(self) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
        """Refresh original live rows and publish only changed canonical facts.

        Returns:
            Original canonical mirror and complete preflight result.

        Raises:
            PalaceOfMemoryDataError: Live paging or usable population is invalid.
            PalaceOfMemoryStateError: Original replacement or audit fails.
        """
        previous = self._previous()
        albums, skipped = self._gather()
        current = self.effects.canonical(albums)
        if len(current) < self.minimum:
            raise PalaceOfMemoryDataError(
                f"Spotify returned fewer than {self.minimum} saved albums."
            )
        changed = previous != current
        backup = self.effects.replace(current) if changed else None
        before = {album.spotify_id for album in previous}
        after = {album.spotify_id for album in current}
        refresh = SavedAlbumRefresh(
            self.effects.clock(),
            len(previous),
            len(current),
            len(after - before),
            len(before - after),
            skipped,
            changed,
            backup,
        )
        self.effects.audit(refresh)
        return current, refresh

    def _previous(self) -> tuple[YourLibraryAlbum, ...]:
        try:
            return self.effects.previous()
        except PalaceOfMemoryDataError:
            return ()

    def _gather(self) -> tuple[list[YourLibraryAlbum], int]:
        albums: list[YourLibraryAlbum] = []
        skipped = 0
        offset = 0
        while True:
            self.effects.progress(f"Refreshing saved albums at offset {offset}")
            page = self.effects.page(offset)
            albums.extend(page.albums)
            skipped += page.rows - len(page.albums)
            offset += page.rows
            if not page.rows and page.has_next:
                raise PalaceOfMemoryDataError(
                    "Spotify returned an empty saved-album page with a next link."
                )
            if not page.rows or not page.has_next:
                return albums, skipped
