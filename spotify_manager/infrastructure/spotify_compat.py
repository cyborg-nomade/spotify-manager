"""Await caller-owned SDK methods only at retained synchronous Python API edges.

Native web and CLI paths use the typed HTTPX client. These explicit SDK calls
preserve overridden methods and omitted arguments; unvalidated SDK responses
remain Any at this external boundary. Caller-owned sessions are never closed.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from spotipy import Spotify

from spotify_manager.application.ports.spotify_async import QueryValue
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


@dataclass(frozen=True)
class LegacyOffsetReader:
    """Keep the original saved-resource SDK method bound for one complete scan.

    Args:
        source: Original caller-owned SDK.
        resource: Original saved-resource selector; non-albums select tracks.
    """

    source: Spotify
    resource: str
    _method: Callable[..., Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture the SDK override once at the original scan boundary."""
        method = (
            self.source.current_user_saved_albums
            if self.resource == "albums"
            else self.source.current_user_saved_tracks
        )
        object.__setattr__(self, "_method", method)

    async def read(self, *, limit: int, offset: int) -> object:
        """Read the originally selected endpoint without repeating its lookup.

        Args:
            limit: Original page size.
            offset: Original raw row offset.

        Returns:
            Original unvalidated SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._read, limit, offset))
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _read(self, limit: int, offset: int) -> Any:
        with LegacyControl():
            return self._method(limit=limit, offset=offset)


@dataclass(frozen=True)
class LegacySpotifyClient:
    """Retain the caller's exact SDK methods and original argument lookup.

    Args:
        source: Original caller-owned SDK or compatible external implementation.
    """

    source: Spotify

    def __bool__(self) -> bool:
        """Observe caller truthiness only when the original execution requests it.

        Returns:
            Original caller-owned SDK truthiness.
        """
        return bool(self.source)

    async def album(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original album SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_album, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_album(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.album(*args, **kwargs)

    async def album_tracks(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original album_tracks SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_album_tracks, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_album_tracks(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.album_tracks(*args, **kwargs)

    async def albums(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original albums SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_albums, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_albums(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.albums(*args, **kwargs)

    async def artist(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original artist SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_artist, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_artist(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.artist(*args, **kwargs)

    async def artist_albums(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original artist_albums SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_artist_albums, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_artist_albums(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.artist_albums(*args, **kwargs)

    async def artist_top_tracks(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original artist_top_tracks SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_artist_top_tracks, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_artist_top_tracks(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.artist_top_tracks(*args, **kwargs)

    async def current_user(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original current_user SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_current_user, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.current_user(*args, **kwargs)

    async def current_user_followed_artists(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_followed_artists SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_followed_artists, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_followed_artists(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_followed_artists(*args, **kwargs)

    async def current_user_following_artists(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_following_artists SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_following_artists, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_following_artists(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_following_artists(*args, **kwargs)

    async def current_user_playlists(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original current_user_playlists SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_playlists, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_playlists(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.current_user_playlists(*args, **kwargs)

    async def current_user_saved_albums(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original current_user_saved_albums SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_albums, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_albums(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_albums(*args, **kwargs)

    async def current_user_saved_albums_add(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_saved_albums_add SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_albums_add, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_albums_add(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_albums_add(*args, **kwargs)

    async def current_user_saved_albums_contains(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_saved_albums_contains SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_albums_contains, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_albums_contains(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_albums_contains(*args, **kwargs)

    async def current_user_saved_albums_delete(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_saved_albums_delete SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_albums_delete, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_albums_delete(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_albums_delete(*args, **kwargs)

    async def current_user_saved_tracks(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original current_user_saved_tracks SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_tracks, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_tracks(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_tracks(*args, **kwargs)

    async def current_user_saved_tracks_add(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_saved_tracks_add SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_tracks_add, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_tracks_add(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_tracks_add(*args, **kwargs)

    async def current_user_saved_tracks_contains(
        self, *args: object, **kwargs: object
    ) -> Any:
        """Await the caller's original current_user_saved_tracks_contains SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_current_user_saved_tracks_contains, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_current_user_saved_tracks_contains(
        self, *args: object, **kwargs: object
    ) -> Any:
        with LegacyControl():
            return self.source.current_user_saved_tracks_contains(*args, **kwargs)

    async def next(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original next SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_next, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_next(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.next(*args, **kwargs)

    async def playlist_add_items(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original playlist_add_items SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_playlist_add_items, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_playlist_add_items(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.playlist_add_items(*args, **kwargs)

    async def search(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original search SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_search, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_search(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.search(*args, **kwargs)

    async def track(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original track SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_track, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_track(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.track(*args, **kwargs)

    async def tracks(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original tracks SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_tracks, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_tracks(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.tracks(*args, **kwargs)

    async def user_follow_artists(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original user_follow_artists SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_user_follow_artists, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_user_follow_artists(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.user_follow_artists(*args, **kwargs)

    async def user_playlist_create(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original user_playlist_create SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_user_playlist_create, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_user_playlist_create(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.user_playlist_create(*args, **kwargs)

    async def _get(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original _get SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_raw_get, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_raw_get(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source._get(*args, **kwargs)

    async def _post(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original _post SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_raw_post, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_raw_post(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source._post(*args, **kwargs)

    async def _put(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original _put SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_raw_put, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_raw_put(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source._put(*args, **kwargs)

    async def _delete(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original _delete SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_raw_delete, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_raw_delete(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source._delete(*args, **kwargs)

    async def rotate_credentials(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original rotate_credentials SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_rotate_credentials, *args, **kwargs)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_rotate_credentials(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.rotate_credentials(*args, **kwargs)

    async def refresh_all_app_tokens(self, *args: object, **kwargs: object) -> Any:
        """Await the caller's original refresh_all_app_tokens SDK method.

        Args:
            args: Original positional SDK arguments.
            kwargs: Original keyword SDK arguments, retaining omitted defaults.

        Returns:
            Unvalidated original SDK response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_refresh_all_app_tokens, *args, **kwargs
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_refresh_all_app_tokens(self, *args: object, **kwargs: object) -> Any:
        with LegacyControl():
            return self.source.refresh_all_app_tokens(*args, **kwargs)

    async def get(self, path: str, query: dict[str, QueryValue] | None = None) -> Any:
        """Retain raw GET calls at the SDK edge.

        Args:
            path: Original relative path or complete pagination URL.
            query: Original query parameters.

        Returns:
            Unvalidated SDK response.
        """
        return await self._get(path, args=query)

    async def post(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> Any:
        """Retain raw POST calls at the SDK edge.

        Args:
            path: Original API path.
            payload: Original JSON body.
            query: Original query parameters.

        Returns:
            Unvalidated SDK response.
        """
        return await self._post(path, args=query, payload=payload)

    async def put(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> Any:
        """Retain raw PUT calls at the SDK edge.

        Args:
            path: Original API path.
            payload: Original JSON body.
            query: Original query parameters.

        Returns:
            Unvalidated SDK response.
        """
        return await self._put(path, args=query, payload=payload)

    async def delete(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> Any:
        """Retain raw DELETE calls at the SDK edge.

        Args:
            path: Original API path.
            payload: Original JSON body.
            query: Original query parameters.

        Returns:
            Unvalidated SDK response.
        """
        return await self._delete(path, args=query, payload=payload)


def legacy_spotify(client: Spotify) -> LegacySpotifyClient:
    """Adapt the caller's original SDK without constructing or closing its sessions.

    Args:
        client: Original caller-owned SDK.

    Returns:
        Named async view preserving each overridden SDK method.
    """
    return LegacySpotifyClient(client)
