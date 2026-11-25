"""Use the modern Spotify routes for owned playlist reads and single writes."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Protocol
from typing import cast

import httpx
from spotipy.exceptions import SpotifyException

from spotify_manager.application.listening_export import PlaylistServiceUnavailableError
from spotify_manager.application.listening_export import PlaylistWriteRejectedError
from spotify_manager.application.ports.spotify_async import QueryValue
from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.domain.listening_export import ExportTarget
from spotify_manager.domain.listening_export import PlaylistExportConflictError
from spotify_manager.domain.listening_export import SpotifyDestination
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify


_PLAYLIST_ID = re.compile(r"[A-Za-z0-9]{22}")
_PLAYLIST_PAGE = 50
_DETAIL = "id,name,owner(id),public,snapshot_id,items(total),tracks(total)"
_REJECTED = {400, 401, 403, 404, 422}


class PlaylistClientOwner(Protocol):
    """Provide the configured Spotify client on the web lifespan loop."""

    async def client(self) -> AsyncSpotify:
        """Return the shared Spotify client."""
        ...


class SpotifyPlaylistGateway:
    """Read editable owned playlists and reconcile mutations without blind replay."""

    def __init__(self, owner: PlaylistClientOwner) -> None:
        """Bind the existing runtime-owned Spotify client.

        Args:
            owner: Owner of the configured Spotify client and credentials.
        """
        self._owner = owner

    async def account(self) -> str:
        """Return the authenticated Spotify account ID."""
        return _required_text(await self._get("me"), "id")

    async def destination(self, identity: str) -> SpotifyDestination:
        """Read the current definitive playlist version and owner."""
        return _playlist(await self._get(f"playlists/{identity}", {"fields": _DETAIL}))

    async def locate_created(
        self, account: str, marker: str
    ) -> SpotifyDestination | None:
        """Find a privately created playlist by its internal creation reference."""
        match = None
        async for record in self._owned(account):
            if record.get("description") != marker:
                continue
            if match is not None:
                raise PlaylistExportConflictError(
                    "Spotify returned two playlists for this export."
                )
            match = _required_text(record, "id")
        return await self.destination(match) if match else None

    async def create(
        self, target: ExportTarget, marker: str
    ) -> SpotifyDestination | None:
        """Create a private playlist and return its acknowledged current state."""
        result = await self._write(
            "me/playlists",
            {"name": target.name, "public": False, "description": marker},
        )
        if result is None:
            return None
        try:
            return _playlist(result)
        except PlaylistServiceUnavailableError:
            return None

    async def append(self, playlist: str, uris: tuple[str, ...]) -> str | None:
        """Append only once and return the Spotify acknowledgment if present."""
        result = await self._write(f"playlists/{playlist}/items", {"uris": list(uris)})
        if isinstance(result, dict) and isinstance(
            receipt := result.get("snapshot_id"), str
        ):
            return receipt or None
        return None

    async def items(
        self, destination: SpotifyDestination, offset: int, count: int
    ) -> tuple[str | None, ...]:
        """Read exact positions against a stable playlist version."""
        tracks = []
        for start in range(offset, offset + count, _PLAYLIST_PAGE):
            limit = min(_PLAYLIST_PAGE, offset + count - start)
            tracks.extend(await self._items_page(destination, start, limit))
        current = await self.destination(destination.identity)
        if current != destination:
            raise PlaylistServiceUnavailableError(
                "Spotify is still updating the playlist. Recheck shortly."
            )
        return tuple(tracks)

    async def _owned(self, account: str) -> AsyncIterator[dict[str, object]]:
        offset = 0
        while True:
            page = await self._get(
                "me/playlists", {"limit": _PLAYLIST_PAGE, "offset": offset}
            )
            records, total = _page(page, offset)
            for record in records:
                if isinstance(record, dict) and _owner_id(record) == account:
                    yield cast(dict[str, object], record)
            offset += len(records)
            if offset >= total:
                return

    async def _items_page(
        self, destination: SpotifyDestination, start: int, limit: int
    ) -> list[str | None]:
        result = await self._get(
            f"playlists/{destination.identity}/items", {"limit": limit, "offset": start}
        )
        records, total = _page(result, start)
        if len(records) != limit or total != destination.count:
            raise PlaylistServiceUnavailableError(
                "Spotify playlist counts are still updating. Recheck shortly."
            )
        return [_item_uri(item) for item in records]

    async def _get(
        self, path: str, query: dict[str, QueryValue] | None = None
    ) -> SpotifyJson:
        try:
            async with asyncio.timeout(25):
                client = await self._owner.client()
                return await client.get(path, query)
        except SpotifyException as error:
            if error.http_status in {403, 404} and path.startswith("playlists/"):
                raise PlaylistExportConflictError(
                    "This Spotify playlist is unavailable to the signed-in account."
                ) from error
            raise PlaylistServiceUnavailableError(
                "Spotify could not read playlist information. Try again."
            ) from error
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
            raise PlaylistServiceUnavailableError(
                "Spotify could not read playlist information. Try again."
            ) from error

    async def _write(self, path: str, payload: SpotifyJson) -> SpotifyJson:
        try:
            client = await self._owner.client()
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
            raise PlaylistServiceUnavailableError(
                "Could not connect to Spotify. Try again."
            ) from error
        request = SpotifyRequest("POST", path, payload=payload, retry_http_status=False)
        try:
            async with asyncio.timeout(25):
                return await client.transport.request(request)
        except SpotifyException as error:
            if error.http_status == 429:
                raise PlaylistServiceUnavailableError(
                    "Spotify rate-limited the export. Wait briefly, then resume."
                ) from error
            if error.http_status in _REJECTED:
                raise PlaylistWriteRejectedError(
                    "Spotify rejected the change. Review the destination and tracks."
                ) from error
            return None
        except OSError, RuntimeError, ValueError, httpx.HTTPError:
            return None


def _required_text(value: object, key: str) -> str:
    if isinstance(value, dict) and isinstance(text := value.get(key), str) and text:
        return text
    raise PlaylistServiceUnavailableError(
        "Spotify returned incomplete playlist information."
    )


def _owner_id(value: dict[str, object]) -> str | None:
    owner = value.get("owner")
    if isinstance(owner, dict) and isinstance(identity := owner.get("id"), str):
        return identity
    return None


def _playlist(raw: object) -> SpotifyDestination:
    if not isinstance(raw, dict):
        raise PlaylistServiceUnavailableError(
            "Spotify returned incomplete playlist information."
        )
    identity, public, owner = (
        _required_text(raw, "id"),
        raw.get("public"),
        _owner_id(raw),
    )
    collection = raw.get("items") or raw.get("tracks")
    count = collection.get("total") if isinstance(collection, dict) else None
    if not owner or not isinstance(public, bool) or type(count) is not int or count < 0:
        raise PlaylistServiceUnavailableError(
            "Spotify returned incomplete playlist information."
        )
    if not _PLAYLIST_ID.fullmatch(identity):
        raise PlaylistServiceUnavailableError(
            "Spotify returned an invalid playlist identity."
        )
    return SpotifyDestination(
        identity,
        _required_text(raw, "name"),
        owner,
        public,
        _required_text(raw, "snapshot_id"),
        count,
    )


def _page(raw: object, offset: int) -> tuple[list[object], int]:
    if not isinstance(raw, dict):
        raise PlaylistServiceUnavailableError("Spotify did not return a playlist page.")
    rows, total = raw.get("items"), raw.get("total")
    if (
        not isinstance(rows, list)
        or type(total) is not int
        or raw.get("offset") != offset
        or offset + len(rows) > total
        or (not rows and offset < total)
    ):
        raise PlaylistServiceUnavailableError(
            "Spotify returned incomplete playlist page data."
        )
    return rows, total


def _item_uri(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    track = raw.get("item") or raw.get("track")
    if not isinstance(track, dict):
        return None
    relinked = track.get("linked_from")
    if isinstance(relinked, dict) and isinstance(original := relinked.get("uri"), str):
        return original
    play = track.get("uri")
    return play if isinstance(play, str) else None
