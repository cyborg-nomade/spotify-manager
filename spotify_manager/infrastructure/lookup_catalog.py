"""Original catalog pagination and raw lookup-record conversion boundaries."""

from typing import Protocol
from typing import cast

from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.domain.lookup_selection import is_primary_credit
from spotify_manager.domain.lookup_values import SpotifyLookupResponseError
from spotify_manager.infrastructure import lookup_records as records


class LookupPages(Protocol):
    """Read catalog pages through explicit transport methods."""

    async def next_object(self, page: object) -> object:
        """Read object continuation.

        Args:
            page: Previous page.

        Returns:
            Next response.
        """
        ...

    async def release_page(self, artist: str, offset: int) -> object:
        """Read an artist release page.

        Args:
            artist: Primary identity.
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        ...

    async def albums(self, identifiers: list[str]) -> object:
        """Read an album batch.

        Args:
            identifiers: Ordered release identities.

        Returns:
            Unvalidated response.
        """
        ...

    async def next_tracks(self, page: object) -> object:
        """Read embedded album-track continuation.

        Args:
            page: Previous page.

        Returns:
            Next response.
        """
        ...


async def all_items(pages: LookupPages, page: object) -> list[dict[str, object]]:
    """Collect original object rows while validating each page and continuation.

    Args:
        pages: Named catalog page reader.
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
        page = await pages.next_object(page)


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


async def releases(pages: LookupPages, artist: str) -> list[str]:
    """Read original raw-offset release pages without collapsing row counts.

    Args:
        pages: Named catalog page reader.
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
            (await pages.release_page(artist, offset)),
            "Spotify returned invalid artist release data.",
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


async def primary_tracks(
    pages: LookupPages,
    artist: str,
    release_ids: list[str],
    batch_size: int,
) -> list[str]:
    """Read original ordered album batches and their dependent track pages.

    Args:
        pages: Named album and track page reader.
        artist: Original primary identity.
        release_ids: Original release encounter order.
        batch_size: Original album batch size.

    Returns:
        Original unique qualified track identities.
    """
    identifiers: dict[str, None] = {}
    for start in range(0, len(release_ids), batch_size):
        albums = records.album_batch(
            await pages.albums(release_ids[start : start + batch_size])
        )
        await collect_album_tracks(albums, pages, artist, identifiers)
    return list(identifiers)


async def collect_album_tracks(
    albums: list[object],
    pages: LookupPages,
    artist: str,
    identifiers: dict[str, None],
) -> None:
    """Decode accepted album rows and follow each dependent page in encounter order.

    Args:
        albums: Accepted raw rows from one original album batch.
        pages: Explicit dependent track-page reader.
        artist: Primary artist whose track IDs are being collected.
        identifiers: Ordered unique IDs updated after each complete album.

    Raises:
        SpotifyLookupResponseError: A dependent track page is malformed.
    """
    for album in albums:
        if not isinstance(album, dict):
            continue
        track_ids = await album_primary_tracks(album.get("tracks"), pages, artist)
        for identifier in track_ids:
            identifiers[identifier] = None


async def album_primary_tracks(
    page: object, pages: LookupPages, artist: str
) -> list[str]:
    """Read original track pages with their distinct empty-next error label.

    Args:
        page: Original embedded first track page.
        pages: Named track page reader.
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
        page = await pages.next_tracks(page)


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
