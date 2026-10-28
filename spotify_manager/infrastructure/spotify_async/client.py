"""Explicit native methods for exactly the application's frozen Spotify subset."""

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from spotify_manager.application.ports.spotify_async import QueryValue
from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.application.ports.spotify_async import SpotifyMaintenance
from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.application.ports.spotify_async import SpotifyTransport
from spotify_manager.infrastructure.spotify_async.identifiers import joined_ids
from spotify_manager.infrastructure.spotify_async.identifiers import joined_uris
from spotify_manager.infrastructure.spotify_async.identifiers import spotify_id
from spotify_manager.infrastructure.spotify_async.identifiers import spotify_uri


@dataclass(frozen=True)
class AsyncSpotify:
    """Expose named endpoint calls without owning business sequencing.

    Args:
        transport: Native pooled HTTP, credential and retry owner.
    """

    transport: SpotifyTransport

    async def rotate_credentials(self) -> str:
        """Apply the operator's original manual credential rotation.

        Returns:
            Newly active credential label.

        Raises:
            SpotifyAppAuthenticationError: No alternate credential can be activated.
        """
        if not isinstance(self.transport, SpotifyMaintenance):
            raise TypeError("This Spotify transport cannot rotate credentials.")
        return await self.transport.rotate_credentials()

    async def refresh_all_app_tokens(self) -> tuple[str, ...]:
        """Refresh every configured app through the existing OAuth resource owner.

        Returns:
            Refreshed app labels in original configuration order.
        """
        if not isinstance(self.transport, SpotifyMaintenance):
            raise TypeError("This Spotify transport cannot refresh app tokens.")
        return await self.transport.refresh_all_app_tokens()

    async def get(
        self, path: str, query: dict[str, QueryValue] | None = None
    ) -> SpotifyJson:
        """Await one explicit GET operation.

        Args:
            path: Relative API path or full pagination URL.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        return await self.transport.request(
            SpotifyRequest("GET", path, query or {}, None)
        )

    async def post(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> SpotifyJson:
        """Await one explicit POST operation.

        Args:
            path: Relative API path or full pagination URL.
            payload: Original JSON body.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        return await self.transport.request(
            SpotifyRequest("POST", path, query or {}, cast(SpotifyJson, payload))
        )

    async def put(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> SpotifyJson:
        """Await one explicit PUT operation.

        Args:
            path: Relative API path or full pagination URL.
            payload: Original JSON body.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        return await self.transport.request(
            SpotifyRequest("PUT", path, query or {}, cast(SpotifyJson, payload))
        )

    async def delete(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> SpotifyJson:
        """Await one explicit DELETE operation.

        Args:
            path: Relative API path or full pagination URL.
            payload: Original JSON body.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        return await self.transport.request(
            SpotifyRequest("DELETE", path, query or {}, cast(SpotifyJson, payload))
        )

    async def album(self, album_id: str, market: str | None = None) -> SpotifyJson:
        """Await the original album endpoint contract.

        Args:
            album_id: Original SDK album id value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        path = "albums/" + spotify_id("album", album_id)
        if market is not None:
            path += "?market=" + market
        return await self.get(path)

    async def album_tracks(
        self, album_id: str, limit: int = 50, offset: int = 0, market: str | None = None
    ) -> SpotifyJson:
        """Await the original album tracks endpoint contract.

        Args:
            album_id: Original SDK album id value.
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "albums/" + spotify_id("album", album_id) + "/tracks/",
            {"limit": limit, "offset": offset, "market": market},
        )

    async def albums(
        self, albums: Sequence[str], market: str | None = None
    ) -> SpotifyJson:
        """Await the original albums endpoint contract.

        Args:
            albums: Original SDK albums value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        path = "albums/?ids=" + joined_ids("album", albums)
        if market is not None:
            path += "&market=" + market
        return await self.get(path)

    async def artist(self, artist_id: str) -> SpotifyJson:
        """Await the original artist endpoint contract.

        Args:
            artist_id: Original SDK artist id value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get("artists/" + spotify_id("artist", artist_id))

    async def artist_albums(
        self,
        artist_id: str,
        album_type: str | None = None,
        include_groups: str | None = None,
        country: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SpotifyJson:
        """Await the original artist albums endpoint contract.

        Args:
            artist_id: Original SDK artist id value.
            album_type: Original SDK album type value.
            include_groups: Original SDK include groups value.
            country: Original SDK country value.
            limit: Original SDK limit value.
            offset: Original SDK offset value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        if album_type:
            warnings.warn(
                "You're using `artist_albums(..., album_type='...')` "
                "which will be removed in "
                "future versions. Please adjust your code accordingly by using "
                "`artist_albums(..., include_groups='...')` instead.",
                DeprecationWarning,
                stacklevel=1,
            )
            include_groups = include_groups or album_type
        return await self.get(
            "artists/" + spotify_id("artist", artist_id) + "/albums",
            {
                "include_groups": include_groups,
                "country": country,
                "limit": limit,
                "offset": offset,
            },
        )

    async def artist_top_tracks(
        self, artist_id: str, country: str = "US"
    ) -> SpotifyJson:
        """Await the original artist top tracks endpoint contract.

        Args:
            artist_id: Original SDK artist id value.
            country: Original SDK country value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        warnings.warn(
            "You're using `artist_top_tracks(...)`, "
            "which is marked as deprecated by Spotify.",
            DeprecationWarning,
            stacklevel=1,
        )
        return await self.get(
            "artists/" + spotify_id("artist", artist_id) + "/top-tracks",
            {"country": country},
        )

    async def current_user(self) -> SpotifyJson:
        """Await the original current user endpoint contract.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get("me/")

    async def current_user_followed_artists(
        self, limit: int = 20, after: str | None = None
    ) -> SpotifyJson:
        """Await the original current user followed artists endpoint contract.

        Args:
            limit: Original SDK limit value.
            after: Original SDK after value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "me/following", {"type": "artist", "limit": limit, "after": after}
        )

    async def current_user_following_artists(
        self, ids: Sequence[str] | None = None
    ) -> SpotifyJson:
        """Await the original current user following artists endpoint contract.

        Args:
            ids: Original SDK ids value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "me/library/contains", {"uris": joined_uris("artist", ids or ())}
        )

    async def current_user_playlists(
        self, limit: int = 50, offset: int = 0
    ) -> SpotifyJson:
        """Await the original current user playlists endpoint contract.

        Args:
            limit: Original SDK limit value.
            offset: Original SDK offset value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get("me/playlists", {"limit": limit, "offset": offset})

    async def current_user_saved_albums(
        self, limit: int = 20, offset: int = 0, market: str | None = None
    ) -> SpotifyJson:
        """Await the original current user saved albums endpoint contract.

        Args:
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "me/albums", {"limit": limit, "offset": offset, "market": market}
        )

    async def current_user_saved_albums_add(
        self, albums: Sequence[str] = ()
    ) -> SpotifyJson:
        """Await the original current user saved albums add endpoint contract.

        Args:
            albums: Original SDK albums value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.put(
            "me/library", query={"uris": joined_uris("album", albums)}
        )

    async def current_user_saved_albums_contains(
        self, albums: Sequence[str] = ()
    ) -> SpotifyJson:
        """Await the original current user saved albums contains endpoint contract.

        Args:
            albums: Original SDK albums value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "me/library/contains", {"uris": joined_uris("album", albums)}
        )

    async def current_user_saved_albums_delete(
        self, albums: Sequence[str] = ()
    ) -> SpotifyJson:
        """Await the original current user saved albums delete endpoint contract.

        Args:
            albums: Original SDK albums value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.delete(
            "me/library", query={"uris": joined_uris("album", albums)}
        )

    async def current_user_saved_tracks(
        self, limit: int = 20, offset: int = 0, market: str | None = None
    ) -> SpotifyJson:
        """Await the original current user saved tracks endpoint contract.

        Args:
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "me/tracks", {"limit": limit, "offset": offset, "market": market}
        )

    async def current_user_saved_tracks_add(
        self, tracks: Sequence[str] | None = None
    ) -> SpotifyJson:
        """Await the original current user saved tracks add endpoint contract.

        Args:
            tracks: Original SDK tracks value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.put(
            "me/library", query={"uris": joined_uris("track", tracks or ())}
        )

    async def current_user_saved_tracks_contains(
        self, tracks: Sequence[str] | None = None
    ) -> SpotifyJson:
        """Await the original current user saved tracks contains endpoint contract.

        Args:
            tracks: Original SDK tracks value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "me/library/contains", {"uris": joined_uris("track", tracks or ())}
        )

    async def next(self, result: object) -> SpotifyJson:
        """Await the original next endpoint contract.

        Args:
            result: Original SDK result value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        page = cast(dict[str, SpotifyJson], result)
        if page["next"]:
            return await self.get(cast(str, page["next"]))
        return None

    async def playlist_add_items(
        self, playlist_id: str, items: Sequence[str], position: int | None = None
    ) -> SpotifyJson:
        """Await the original playlist add items endpoint contract.

        Args:
            playlist_id: Original SDK playlist id value.
            items: Original SDK items value.
            position: Original SDK position value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        uris: list[SpotifyJson] = []
        for item in items:
            uris.append(spotify_uri("track", item))
        return await self.post(
            "playlists/" + spotify_id("playlist", playlist_id) + "/items",
            uris,
            {"position": position},
        )

    async def search(
        self,
        q: str,
        limit: int = 10,
        offset: int = 0,
        type: str = "track",  # noqa: A002 - Preserve the SDK keyword.  # noqa: A002 - Preserve the SDK search keyword.
        market: str | None = None,
    ) -> SpotifyJson:
        """Await the original search endpoint contract.

        Args:
            q: Original SDK q value.
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            type: Original SDK type value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "search",
            {"q": q, "limit": limit, "offset": offset, "type": type, "market": market},
        )

    async def track(self, track_id: str, market: str | None = None) -> SpotifyJson:
        """Await the original track endpoint contract.

        Args:
            track_id: Original SDK track id value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "tracks/" + spotify_id("track", track_id), {"market": market}
        )

    async def tracks(
        self, tracks: Sequence[str], market: str | None = None
    ) -> SpotifyJson:
        """Await the original tracks endpoint contract.

        Args:
            tracks: Original SDK tracks value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.get(
            "tracks/?ids=" + joined_ids("track", tracks), {"market": market}
        )

    async def user_follow_artists(self, ids: Sequence[str] = ()) -> SpotifyJson:
        """Await the original user follow artists endpoint contract.

        Args:
            ids: Original SDK ids value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        return await self.put("me/library", query={"uris": joined_uris("artist", ids)})

    async def user_playlist_create(
        self,
        user: str,
        name: str,
        public: bool = True,
        collaborative: bool = False,
        description: str = "",
    ) -> SpotifyJson:
        """Await the original user playlist create endpoint contract.

        Args:
            user: Original SDK user value.
            name: Original SDK name value.
            public: Original SDK public value.
            collaborative: Original SDK collaborative value.
            description: Original SDK description value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        warnings.warn(
            "You're using `user_playlist_create(...)`, "
            "which is marked as deprecated by Spotify. Use "
            "current_user_playlist_create(...) instead.",
            DeprecationWarning,
            stacklevel=1,
        )
        return await self.post(
            f"users/{user}/playlists",
            {
                "name": name,
                "public": public,
                "collaborative": collaborative,
                "description": description,
            },
        )

    async def _get(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> SpotifyJson:
        """Retain the SDK raw GET parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        query = dict(kwargs)
        query.update(args or {})
        return await self.transport.request(
            SpotifyRequest("GET", url, query, cast(SpotifyJson, payload))
        )

    async def _post(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> SpotifyJson:
        """Retain the SDK raw POST parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        query = dict(kwargs)
        query.update(args or {})
        return await self.post(url, payload, query)

    async def _put(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> SpotifyJson:
        """Retain the SDK raw PUT parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        query = dict(kwargs)
        query.update(args or {})
        return await self.put(url, payload, query)

    async def _delete(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> SpotifyJson:
        """Retain the SDK raw DELETE parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        query = dict(kwargs)
        query.update(args or {})
        return await self.delete(url, payload, query)
