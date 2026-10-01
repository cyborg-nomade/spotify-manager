"""Preserve synchronous catalog, release-track and playlist paging contracts."""

from collections.abc import Callable
from datetime import date
from typing import cast

from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.domain.release_check import release_date_interval
from spotify_manager.domain.release_check_values import PlaylistEntry
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


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
    parse: Callable[[object, str], ReleaseCandidate | None],
    artist_id: str,
    start: date,
) -> None:
    for raw in items:
        candidate = parse(raw, artist_id)
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


def load_catalog_pages(
    read: Callable[[int], object],
    parse: Callable[[object, str], ReleaseCandidate | None],
    name: str,
    artist_id: str,
    start: date,
) -> tuple[ReleaseCandidate, ...]:
    """Scan every catalog page and retain qualifying metadata by release identity.

    Args:
        read: Original retry-wrapped page read at an ordered offset.
        parse: Original tolerant primary-artist release decoder.
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
        response = _page(read(offset), "release", name)
        items = _items(response)
        _retain_releases(items, releases, parse, artist_id, start)
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
    parse: Callable[[object, int], ReleaseTrack | None],
) -> None:
    for raw in items:
        track = parse(raw, len(tracks) + 1)
        if track is not None:
            tracks.append(track)


def _track_order(track: ReleaseTrack) -> tuple[int, int]:
    return track.disc_number, track.track_number


def load_track_pages(
    read: Callable[[int, int], object],
    parse: Callable[[object, int], ReleaseTrack | None],
    name: str,
    first_only: bool,
    page_limit: int,
) -> tuple[ReleaseTrack, ...]:
    """Read playable release markers, retaining original first-only and 404 rules.

    Args:
        read: Original retry-wrapped read taking offset and page limit.
        parse: Original tolerant playable-marker decoder.
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
        try:
            response = _page(read(offset, limit), "track", name)
        except MissingReleaseTracksError:
            return ()
        items = _items(response)
        _retain_tracks(items, tracks, parse)
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
    parse: Callable[[object], PlaylistEntry | None],
    name: str,
) -> None:
    for raw in items:
        entry = parse(raw)
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


def load_playlist_pages(
    read: Callable[[int], object],
    parse: Callable[[object], PlaylistEntry | None],
    name: str,
) -> tuple[PlaylistEntry, ...]:
    """Preserve every playlist item and follow either continuation or integer totals.

    Args:
        read: Original retry-wrapped page read at an ordered offset.
        parse: Original URI-preserving playlist decoder.
        name: Original playlist identity used in errors.

    Returns:
        Every decoded original item in page order.

    Raises:
        ReleaseCheckSpotifyError: A page or item cannot be safely preserved.
    """
    entries: list[PlaylistEntry] = []
    offset = 0
    while True:
        response = _page(read(offset), "playlist", name)
        items = _items(response)
        _retain_entries(items, entries, parse, name)
        offset += len(items)
        if not _has_playlist_page(response, offset):
            return tuple(entries)
        if not items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty playlist page for {name}."
            )
