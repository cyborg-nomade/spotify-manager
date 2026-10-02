"""Explicit legacy file, interaction and catalog dependencies."""

from collections.abc import Callable
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

    def __call__(self, *values: object) -> None:
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


@dataclass(frozen=True)
class LegacyFiles:
    """Supply original mutable authorities and accepted publications.

    Args:
        albums: Legacy total-album read.
        control: Original control read.
        export: Original export read.
        comparison: Original unchecked comparison read.
        save_albums: Original album publication.
        save_control: Original control publication.
        save_stats: Original statistics publication.
        save_comparison: Original comparison publication.
    """

    albums: Callable[[], list[SimplifiedAlbum]]
    control: Callable[[], list[ControlFileItem]]
    export: Callable[[], YourLibraryFile]
    comparison: Callable[[], Comparison]
    save_albums: Callable[[list[SimplifiedAlbum]], None]
    save_control: Callable[[list[ControlFileItem]], None]
    save_stats: Callable[[StatsFileItem], None]
    save_comparison: Callable[[Comparison], None]


@dataclass(frozen=True)
class ConversionCatalog:
    """Bind legacy singleton membership and restoration effects.

    Args:
        contains: Original saved-album singleton query.
        enrich: Original album-model conversion.
        artist_saved: Original artist membership.
        track_saved: Original track membership.
        follow: Original artist save.
        like: Original track save.
        add_contains: Original addition membership seam.
    """

    contains: Callable[[str], object]
    enrich: Callable[[str], SimplifiedAlbum]
    artist_saved: Callable[[YourLibraryArtist], bool]
    track_saved: Callable[[YourLibraryTrack], bool]
    follow: Callable[[YourLibraryArtist], None]
    like: Callable[[YourLibraryTrack], None]
    add_contains: Callable[[str], object]


@dataclass(frozen=True)
class MonthlyActions:
    """Bind original public monthly stages without sharing hidden runtime state.

    Args:
        evaluate: Original control reconciliation.
        statistics: Original statistics stage.
        starting_index: Original cursor selection.
        append: Original monthly playlist execution.
    """

    evaluate: Callable[[list[ControlFileItem], list[SimplifiedAlbum]], bool]
    statistics: Callable[[list[ControlFileItem], list[SimplifiedAlbum]], bool]
    starting_index: Callable[[list[ControlFileItem], list[SimplifiedAlbum]], int]
    append: Callable[[list[ControlFileItem], list[SimplifiedAlbum], int], bool]


@dataclass(frozen=True)
class MonthlyPlaylist:
    """Supply legacy playlist stages and original selection boundary.

    Args:
        select: Original permissive monthly slice.
        create: Original clock-sensitive playlist creation.
        tracks: Original ordered tracks.
        append: Original ordered additions.
        save: Original control publication.
    """

    select: Callable[[list[SimplifiedAlbum], int], list[SimplifiedAlbum]]
    create: Callable[[], str]
    tracks: Callable[[SimplifiedAlbum], list[SimplifiedTrack]]
    append: Callable[[list[SimplifiedTrack], str], None]
    save: Callable[[list[ControlFileItem]], None]


@dataclass(frozen=True)
class AlbumRefresh:
    """Bind original raw paging, conversion and publication.

    Args:
        saved: Original initial saved-album page.
        recover: Original failed-next fallback read.
        next: Original next page.
        parse: Original saved-album conversion.
        load: Original incremental authority.
        save: Original accepted album publication.
        limit: Original live page-size observation.
    """

    saved: Callable[[int], Page]
    recover: Callable[[int], Page]
    next: Callable[[Page], Page]
    parse: Callable[[list[object]], list[SimplifiedAlbum]]
    load: Callable[[], list[SimplifiedAlbum]]
    save: Callable[[list[SimplifiedAlbum]], None]
    limit: Callable[[], int]


@dataclass(frozen=True)
class PlaylistClock:
    """Bind original independent clock observations and creation request.

    Args:
        now: Original naive local clock.
        create: Original named playlist request.
    """

    now: Callable[[], datetime]
    create: Callable[[str], object]


class FailureScope(Protocol):
    """Report original ordinary failures at an injected execution boundary."""

    failed: bool

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


type FailureFactory = Callable[[Echo], FailureScope]


@dataclass(frozen=True)
class TrackRead:
    """Bind original raw track paging, coercion, sorting and validation.

    Args:
        read: Original first album-track page.
        next: Original next track page.
        parse: Original truthy row coercion.
        sort: Original stable disc/track sort.
        validate: Original final model validation.
    """

    read: Callable[[str], Page]
    next: Callable[[Page], Page]
    parse: Callable[[list[object]], list[dict[str, object]]]
    sort: Callable[[list[dict[str, object]]], list[dict[str, object]]]
    validate: Callable[[list[dict[str, object]]], list[SimplifiedTrack]]
