"""Explicit raw catalog, cache and history boundaries for original lookups."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.models.your_library import YourLibraryFile


class LookupTrack(TypedDict):
    """Unchecked original minimized track fields; validation remains at presentation."""

    id: str | None
    name: str
    uri: str


@dataclass(frozen=True)
class LookupPage:
    """Original validated container with unchecked row values.

    Args:
        rows: Every original raw row, including non-objects.
        next: Original next-link value without new validation.
    """

    rows: list[object]
    next: object


@dataclass(frozen=True)
class CachedTracks:
    """Supply original cache authority and delayed client acquisition.

    Args:
        load: Original unchecked cache read.
        save: Original complete cache publication.
        fetch: Original lazy client selection and complete track read.
    """

    load: Callable[[], dict[str, list[LookupTrack]]]
    save: Callable[[dict[str, list[LookupTrack]]], None]
    fetch: Callable[[str], list[LookupTrack]]


@dataclass(frozen=True)
class LocalAlbumLookup:
    """Supply original local authority and cached-track stage.

    Args:
        library: Original export read.
        tracks: Original complete cache/API track stage.
    """

    library: Callable[[], YourLibraryFile]
    tracks: Callable[[str], tuple[list[LookupTrack], bool]]


@dataclass(frozen=True)
class ArtistLookup:
    """Supply original direct and search identity observations.

    Args:
        direct: Original direct read with its 404 translation.
        search: Original exact-search candidate observations.
    """

    direct: Callable[[str], tuple[str, str] | None]
    search: Callable[[str], list[tuple[str, str]]]


@dataclass(frozen=True)
class AlbumLookup:
    """Supply original direct and search album observations.

    Args:
        direct: Original direct read with its shape and 404 translation.
        search: Original ordered search candidates.
    """

    direct: Callable[[str], LiveAlbumCandidate]
    search: Callable[[str, str | None], list[LiveAlbumCandidate]]


@dataclass(frozen=True)
class TrackLookup:
    """Supply original direct and search track observations.

    Args:
        direct: Original direct read with its shape and 404 translation.
        search: Original ordered search candidates.
    """

    direct: Callable[[str], ResolvedTrack]
    search: Callable[[str], list[ResolvedTrack]]
