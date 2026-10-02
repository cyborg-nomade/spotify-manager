"""Original catalog pagination and raw lookup-record conversion boundaries."""

from collections.abc import Callable
from typing import cast

from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.domain.lookup_selection import is_primary_credit
from spotify_manager.domain.lookup_values import SpotifyLookupResponseError
from spotify_manager.infrastructure import lookup_records as records


def all_items(
    next_page: Callable[[object], object], page: object
) -> list[dict[str, object]]:
    """Collect original object rows while validating each page and continuation.

    Args:
        next_page: Original caller-owned continuation request.
        page: Original first response.

    Returns:
        Original object rows in raw encounter order.

    Raises:
        SpotifyLookupResponseError: Original shape or empty-next guard fails.
    """
    result: list[dict[str, object]] = []
    while True:
        facts = records.page(page, "Spotify returned invalid paginated track data.")
        result.extend(_object_rows(facts.rows))
        if not facts.next:
            return result
        if not facts.rows:
            raise SpotifyLookupResponseError(
                "Spotify returned an empty track page with a next link."
            )
        page = next_page(page)


def _object_rows(rows: list[object]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(cast(dict[str, object], row))
    return result


def primary_ids(rows: list[object], artist: str) -> list[str]:
    """Read original qualified row identities in encounter order.

    Args:
        rows: Original unchecked catalog rows.
        artist: Original resolved primary-artist identity.

    Returns:
        Original nonempty first-credit identities.
    """
    result = []
    for raw in rows:
        if not isinstance(raw, dict) or not is_primary_credit(
            records.primary_artist_id(raw), artist
        ):
            continue
        identifier = str(raw.get("id") or "").strip()
        if identifier:
            result.append(identifier)
    return result


def releases(read: Callable[[int], object], artist: str) -> list[str]:
    """Read original raw-offset release pages without collapsing row counts.

    Args:
        read: Original explicit-offset read.
        artist: Original primary identity.

    Returns:
        Original unique qualified release identities in first encounter order.

    Raises:
        SpotifyLookupResponseError: Original shape or empty-next guard fails.
    """
    identifiers: dict[str, None] = {}
    offset = 0
    while True:
        facts = records.page(
            read(offset), "Spotify returned invalid artist release data."
        )
        for identifier in primary_ids(facts.rows, artist):
            identifiers[identifier] = None
        if not facts.next:
            return list(identifiers)
        if not facts.rows:
            raise SpotifyLookupResponseError(
                "Spotify returned an empty artist release page with a next link."
            )
        offset += len(facts.rows)


def primary_tracks(
    read: Callable[[list[str]], object],
    next_page: Callable[[object], object],
    artist: str,
    release_ids: list[str],
    batch_size: int,
) -> list[str]:
    """Read original ordered album batches and their dependent track pages.

    Args:
        read: Original album batch request.
        next_page: Original track continuation.
        artist: Original primary identity.
        release_ids: Original release encounter order.
        batch_size: Original album batch size.

    Returns:
        Original unique qualified track identities.
    """
    identifiers: dict[str, None] = {}
    for start in range(0, len(release_ids), batch_size):
        albums = records.album_batch(read(release_ids[start : start + batch_size]))
        _collect_album_tracks(albums, next_page, artist, identifiers)
    return list(identifiers)


def _collect_album_tracks(
    albums: list[object],
    next_page: Callable[[object], object],
    artist: str,
    identifiers: dict[str, None],
) -> None:
    for album in albums:
        if not isinstance(album, dict):
            continue
        track_ids = album_primary_tracks(album.get("tracks"), next_page, artist)
        for identifier in track_ids:
            identifiers[identifier] = None


def album_primary_tracks(
    page: object, next_page: Callable[[object], object], artist: str
) -> list[str]:
    """Read original track pages with their distinct empty-next error label.

    Args:
        page: Original embedded first track page.
        next_page: Original continuation.
        artist: Original resolved primary identity.

    Returns:
        Original qualified identities, including repeated rows.

    Raises:
        SpotifyLookupResponseError: Original shape or empty-next guard fails.
    """
    result = []
    while True:
        facts = records.page(page, "Spotify returned invalid album track data.")
        result.extend(primary_ids(facts.rows, artist))
        if not facts.next:
            return result
        if not facts.rows:
            raise SpotifyLookupResponseError(
                "Spotify returned an empty album track page with a next link."
            )
        page = next_page(page)


def minimize_tracks(
    rows: list[dict[str, object]], identifier: str
) -> list[LookupTrack]:
    """Validate original display fields after all track pages have been read.

    Args:
        rows: Original complete object track rows.
        identifier: Original requested album identity.

    Returns:
        Original minimized cache records.
    """
    result = []
    for row in rows:
        result.append(records.minimized_track(row, identifier))
    return result
