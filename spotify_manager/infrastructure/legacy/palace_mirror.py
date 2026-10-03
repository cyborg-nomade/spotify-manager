"""Bind saved-mirror preflight to original live parsing, ordering and file effects."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_mirror import SavedAlbumPage
from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.infrastructure.library_models import album_from_saved_item
from spotify_manager.infrastructure.library_models import deduplicate_models
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import palace_of_memory as legacy
from spotify_manager.utils.sorting import album_sort_key


@dataclass(frozen=True)
class LegacySavedMirror:
    """Retain original canonical mirror and publication boundaries.

    Args:
        spotify: Original caller-owned client.
        path: Original canonical mirror location.
        backups: Original backup directory.
        log_path: Original preflight audit location.
        retry: Original caller-owned retry boundary.
        callback: Original optional paging presenter.
    """

    spotify: Spotify
    path: Path
    backups: Path
    log_path: Path
    retry: legacy.RetryCall
    callback: legacy.ProgressCallback | None

    def previous(self) -> tuple[YourLibraryAlbum, ...]:
        """Read the original mirror only when its canonical file exists.

        Returns:
            Original usable previous mirror or empty for a missing file.
        """
        from spotify_manager.routines.palace_of_memory import load_saved_albums

        return load_saved_albums(self.path) if self.path.exists() else ()

    def progress(self, message: str) -> None:
        """Retain original optional paging progress.

        Args:
            message: Original visible page stage.
        """
        if self.callback is not None:
            self.callback(message)

    def page(self, offset: int) -> SavedAlbumPage:
        """Read original raw saved rows and retain exact raw offset accounting.

        Args:
            offset: Original raw-row offset.

        Returns:
            Original usable models and continuation facts.

        Raises:
            PalaceOfMemoryDataError: The original live page shape is unusable.
        """
        from spotify_manager.routines.palace_of_memory import _read_saved_album_page

        response = self.retry(
            partial(_read_saved_album_page, self.spotify, offset),
            f"refreshing saved albums at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise PalaceOfMemoryDataError(
                f"Spotify returned an invalid saved-album page at offset {offset}."
            )
        albums = []
        for raw in response["items"]:
            album = album_from_saved_item(raw)
            if album is not None:
                albums.append(album)
        return SavedAlbumPage(
            tuple(albums), len(response["items"]), bool(response.get("next"))
        )

    def canonical(self, albums: list[YourLibraryAlbum]) -> tuple[YourLibraryAlbum, ...]:
        """Retain original newest-value deduplication and album-title collation.

        Args:
            albums: Original gathered usable models.

        Returns:
            Original canonical mirror order.
        """
        return tuple(
            sorted(
                deduplicate_models(albums),
                key=album_sort_key,
            )
        )

    def replace(self, albums: tuple[YourLibraryAlbum, ...]) -> str | None:
        """Retain original backup, atomic replacement and publication ordering.

        Args:
            albums: Original complete canonical replacement.

        Returns:
            Original backup location when a previous file exists.
        """
        from spotify_manager.routines.palace_of_memory import _replace_saved_albums

        return _replace_saved_albums(self.path, self.backups, albums)

    def clock(self) -> datetime:
        """Retain original independent UTC refresh completion timestamp.

        Returns:
            Original observed effective time.
        """
        return legacy.datetime.now(UTC)

    def audit(self, refresh: SavedAlbumRefresh) -> None:
        """Retain original unchanged-mirror and replaced-mirror preflight audits.

        Args:
            refresh: Original complete preflight facts.
        """
        from spotify_manager.routines.palace_of_memory import _append_refresh_log

        _append_refresh_log(self.log_path, refresh)
