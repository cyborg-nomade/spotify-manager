"""Explicit legacy file, interaction and catalog dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol
from typing import TypedDict

from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


class Echo(Protocol):
    """Present original positional print arguments."""

    def echo(self, *values: object) -> None:
        """Deliver original visible values.

        Args:
            values: Original positional arguments.
        """
        ...


class ComparisonAlbum(TypedDict):
    """Original unchecked comparison identity and optional display metadata."""

    id: str


class Comparison(TypedDict):
    """Original comparison lists; runtime validation remains unchanged."""

    add: list[ComparisonAlbum]
    remove: list[ComparisonAlbum]


class Page(TypedDict):
    """Unchecked original SDK page view, preserving native boundary errors."""

    items: list[object]
    next: object
    offset: int
    total: int


class LegacyFiles(Protocol):
    """Supply original mutable authorities and accepted publications."""

    async def albums(self) -> list[SimplifiedAlbum]:
        """Legacy total-album read.

        Returns:
            Original boundary result.
        """
        ...

    async def control(self) -> list[ControlFileItem]:
        """Original control read.

        Returns:
            Original boundary result.
        """
        ...

    async def export(self) -> YourLibraryFile:
        """Original export read.

        Returns:
            Original boundary result.
        """
        ...

    async def comparison(self) -> Comparison:
        """Original unchecked comparison read.

        Returns:
            Original boundary result.
        """
        ...

    async def save_albums(self, albums: list[SimplifiedAlbum]) -> None:
        """Original album publication.

        Args:
            albums: Original albums.
        """
        ...

    async def save_control(self, control: list[ControlFileItem]) -> None:
        """Original control publication.

        Args:
            control: Original control.
        """
        ...

    async def save_stats(self, stats: StatsFileItem) -> None:
        """Original statistics publication.

        Args:
            stats: Original stats.
        """
        ...

    async def save_comparison(self, comparison: Comparison) -> None:
        """Original comparison publication.

        Args:
            comparison: Original comparison.
        """
        ...


class ConversionCatalog(Protocol):
    """Bind legacy singleton membership and restoration effects."""

    async def contains(self, identifier: str) -> object:
        """Original saved-album singleton query.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        ...

    async def enrich(self, identifier: str) -> SimplifiedAlbum:
        """Original album-model conversion.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        ...

    async def artist_saved(self, artist: YourLibraryArtist) -> bool:
        """Original artist membership.

        Args:
            artist: Original artist.

        Returns:
            Original boundary result.
        """
        ...

    async def track_saved(self, track: YourLibraryTrack) -> bool:
        """Original track membership.

        Args:
            track: Original track.

        Returns:
            Original boundary result.
        """
        ...

    async def follow(self, artist: YourLibraryArtist) -> None:
        """Original artist save.

        Args:
            artist: Original artist.
        """
        ...

    async def like(self, track: YourLibraryTrack) -> None:
        """Original track save.

        Args:
            track: Original track.
        """
        ...

    async def add_contains(self, identifier: str) -> object:
        """Original addition membership seam.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        ...


class ControlMembership(Protocol):
    """Read singleton saved-album membership for control decisions."""

    async def contains(self, identifier: str) -> object:
        """Read membership.

        Args:
            identifier: Album identity.

        Returns:
            Original permissive status.
        """
        ...


class ComparisonMembership(ControlMembership, Protocol):
    """Read original removal and addition membership observations."""

    async def add_contains(self, identifier: str) -> object:
        """Read addition membership.

        Args:
            identifier: Album identity.

        Returns:
            Original status.
        """
        ...


class MonthlyLimits(Protocol):
    """Observe live monthly selection settings at the selection boundary."""

    def count(self) -> int:
        """Observe the monthly album count.

        Returns:
            Configured slice size.
        """
        ...


class PlaylistWrites(Protocol):
    """Accept ordered playlist additions through the original request seams."""

    async def single(self, identifier: str, uris: list[str]) -> None:
        """Accept a small addition, including an empty list.

        Args:
            identifier: Destination playlist.
            uris: Ordered tracks.
        """
        ...

    async def batch(self, identifier: str, uris: list[str]) -> None:
        """Accept one hundred-track batch.

        Args:
            identifier: Destination playlist.
            uris: Ordered tracks.
        """
        ...


@dataclass(frozen=True)
class MonthlyPlaylist:
    """Provide cohesive external resources for direct playlist stages.

    Args:
        clock: Playlist creation and clock observations.
        tracks: Track pages and record decoding.
        writes: Playlist additions.
        files: Control-file publication.
        limits: Deferred selection settings.
    """

    clock: PlaylistClock
    tracks: TrackRead
    writes: PlaylistWrites
    files: LegacyFiles
    limits: MonthlyLimits


@dataclass(frozen=True)
class MonthlyActions:
    """Supply external resources for the fixed monthly application sequence.

    Args:
        catalog: Control membership reader.
        playlist: Monthly playlist resources.
    """

    catalog: ControlMembership
    playlist: MonthlyPlaylist


class ComparisonMetadata(Protocol):
    """Read comparison display metadata for one identity."""

    async def enrich(self, identifier: str) -> ComparisonAlbum:
        """Read and present metadata.

        Args:
            identifier: Album identity.

        Returns:
            Original comparison metadata.
        """
        ...


class AlbumRefresh(Protocol):
    """Bind original raw paging, conversion and publication."""

    async def saved(self, offset: int) -> Page:
        """Original initial saved-album page.

        Args:
            offset: Original offset.

        Returns:
            Original boundary result.
        """
        ...

    async def recover(self, offset: int) -> Page:
        """Original failed-next fallback read.

        Args:
            offset: Original offset.

        Returns:
            Original boundary result.
        """
        ...

    async def next(self, page: Page) -> Page:
        """Original next page.

        Args:
            page: Original page.

        Returns:
            Original boundary result.
        """
        ...

    def parse(self, rows: list[object]) -> list[SimplifiedAlbum]:
        """Original saved-album conversion.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        ...

    async def load(self) -> list[SimplifiedAlbum]:
        """Original incremental authority.

        Returns:
            Original boundary result.
        """
        ...

    async def save(self, albums: list[SimplifiedAlbum]) -> None:
        """Original accepted album publication.

        Args:
            albums: Original albums.
        """
        ...

    def limit(self) -> int:
        """Original live page-size observation.

        Returns:
            Original boundary result.
        """
        ...


class PlaylistClock(Protocol):
    """Bind original independent clock observations and creation request."""

    def now(self) -> datetime:
        """Original naive local clock.

        Returns:
            Original boundary result.
        """
        ...

    async def create(self, name: str) -> object:
        """Original named playlist request.

        Args:
            name: Original name.

        Returns:
            Original boundary result.
        """
        ...


class FailureScope(Protocol):
    """Report original ordinary failures at an injected execution boundary."""

    failed: bool
    error: Exception | None

    def __enter__(self) -> FailureScope:
        """Enter an original attempt.

        Returns:
            Mutable failure observation.
        """
        ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Apply the original ordinary-error reporting policy.

        Args:
            kind: Original failure type.
            error: Original failure.
            traceback: Original traceback.

        Returns:
            Whether the original failure is suppressed.
        """
        ...


class TrackRead(Protocol):
    """Bind original raw track paging, coercion, sorting and validation."""

    async def read(self, identifier: str) -> Page:
        """Original first album-track page.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        ...

    async def next(self, page: Page) -> Page:
        """Original next track page.

        Args:
            page: Original page.

        Returns:
            Original boundary result.
        """
        ...

    def parse(self, rows: list[object]) -> list[dict[str, object]]:
        """Original truthy row coercion.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        ...

    def sort(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """Original stable disc/track sort.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        ...

    def validate(self, rows: list[dict[str, object]]) -> list[SimplifiedTrack]:
        """Original final model validation.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        ...
