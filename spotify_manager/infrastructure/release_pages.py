"""Preserve synchronous catalog, release-track and playlist paging contracts."""

from datetime import date
from typing import Protocol
from typing import cast

from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.domain.release_check import release_date_interval
from spotify_manager.domain.release_check_values import PlaylistEntry
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.infrastructure.release_check_catalog import parse_playlist_entry
from spotify_manager.infrastructure.release_check_catalog import parse_release
from spotify_manager.infrastructure.release_check_catalog import parse_track


class CatalogPageReader(Protocol):
    """Read release-catalog pages at explicit offsets."""

    async def read(self, offset: int) -> object:
        """Read a catalog page.

        Args:
            offset: Raw row offset.

        Returns:
            Unvalidated transport response.
        """
        ...


class TrackPageReader(Protocol):
    """Read release-track pages with explicit offsets and limits."""

    async def read(self, offset: int, limit: int) -> object:
        """Read a track page.

        Args:
            offset: Raw row offset.
            limit: Original first-only or complete page size.

        Returns:
            Unvalidated transport response.
        """
        ...


class MissingReleaseTracksError(RuntimeError):
    """The original release-track endpoint returned a missing-resource response."""


def _page(response: object, kind: str, name: str) -> dict[str, object]:
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise ReleaseCheckSpotifyError(
            f"Spotify returned invalid {kind} data for {name}."
        )
    return cast(dict[str, object], response)


def _items(response: dict[str, object]) -> list[object]:
    return cast(list[object], response["items"])


def _retain_releases(
    items: list[object],
    releases: dict[str, ReleaseCandidate],
    artist_id: str,
    start: date,
) -> None:
    for raw in items:
        candidate = parse_release(raw, artist_id)
        if candidate is None:
            continue
        interval = release_date_interval(candidate)
        if interval is not None and interval[1] >= start:
            releases[candidate.spotify_id] = candidate


def _release_order(
    release: ReleaseCandidate,
) -> tuple[tuple[date, date], str, str, str]:
    return (
        release_date_interval(release) or (date.max, date.max),
        release.release_type,
        release.name.casefold(),
        release.spotify_id,
    )


async def load_catalog_pages(
    pages: CatalogPageReader,
    name: str,
    artist_id: str,
    start: date,
) -> tuple[ReleaseCandidate, ...]:
    """Scan every catalog page and retain qualifying metadata by release identity.

    Args:
        pages: Named retry-wrapped transport page reader.
        name: Original artist display name used in errors.
        artist_id: Original resolved primary-artist identity.
        start: Original inclusive date boundary.

    Returns:
        Qualified observations sorted by date, kind, title and identity.

    Raises:
        ReleaseCheckSpotifyError: A page is malformed or empty with continuation.
    """
    releases: dict[str, ReleaseCandidate] = {}
    offset = 0
    while True:
        response = _page((await pages.read(offset)), "release", name)
        items = _items(response)
        _retain_releases(items, releases, artist_id, start)
        offset += len(items)
        if not response.get("next"):
            return tuple(sorted(releases.values(), key=_release_order))
        if not items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty release page for {name}."
            )


def _retain_tracks(
    items: list[object],
    tracks: list[ReleaseTrack],
) -> None:
    for raw in items:
        track = parse_track(raw, len(tracks) + 1)
        if track is not None:
            tracks.append(track)


def _track_order(track: ReleaseTrack) -> tuple[int, int]:
    return track.disc_number, track.track_number


async def load_track_pages(
    pages: TrackPageReader,
    name: str,
    first_only: bool,
    page_limit: int,
) -> tuple[ReleaseTrack, ...]:
    """Read playable release markers, retaining original first-only and 404 rules.

    Args:
        pages: Named retry-wrapped transport page reader.
        name: Original release display name used in errors.
        first_only: Original single-page first-marker request.
        page_limit: Original full-track page limit.

    Returns:
        Disc/track-ordered markers, or empty if any page reports a missing release.

    Raises:
        ReleaseCheckSpotifyError: A page is malformed or empty with continuation.
    """
    tracks: list[ReleaseTrack] = []
    offset = 0
    limit = 1 if first_only else page_limit
    while True:
        response = await _optional_track_page(pages, offset, limit, name)
        if response is None:
            return ()
        items = _items(response)
        _retain_tracks(items, tracks)
        if first_only or not response.get("next"):
            return tuple(sorted(tracks, key=_track_order))
        offset += len(items)
        if not items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty track page for {name}."
            )


def _retain_entries(
    items: list[object],
    entries: list[PlaylistEntry],
    name: str,
) -> None:
    for raw in items:
        entry = parse_playlist_entry(raw)
        if entry is None:
            raise ReleaseCheckSpotifyError(
                f"Playlist {name} contains an item that cannot be preserved safely."
            )
        entries.append(entry)


def _has_playlist_page(response: dict[str, object], offset: int) -> bool:
    total = response.get("total")
    has_more = bool(response.get("next"))
    if isinstance(total, int):
        has_more = has_more or offset < total
    return has_more


async def load_playlist_pages(
    pages: CatalogPageReader,
    name: str,
) -> tuple[PlaylistEntry, ...]:
    """Preserve every playlist item and follow either continuation or integer totals.

    Args:
        pages: Named retry-wrapped transport page reader.
        name: Original playlist identity used in errors.

    Returns:
        Every decoded original item in page order.

    Raises:
        ReleaseCheckSpotifyError: A page or item cannot be safely preserved.
    """
    entries: list[PlaylistEntry] = []
    offset = 0
    while True:
        response = _page((await pages.read(offset)), "playlist", name)
        items = _items(response)
        _retain_entries(items, entries, name)
        offset += len(items)
        if not _has_playlist_page(response, offset):
            return tuple(entries)
        if not items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty playlist page for {name}."
            )


async def _optional_track_page(
    pages: TrackPageReader, offset: int, limit: int, name: str
) -> dict[str, object] | None:
    try:
        return _page((await pages.read(offset, limit)), "track", name)
    except MissingReleaseTracksError:
        return None
