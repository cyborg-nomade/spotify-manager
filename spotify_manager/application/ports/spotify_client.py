"""Typed async SDK boundary retaining permissive external Spotify payloads.

The return boundary deliberately accepts unvalidated JSON. Existing endpoint
parsers own validation, including malformed and null responses; narrowing it
here would change their original error semantics.
"""

from collections.abc import Sequence
from typing import Any
from typing import Protocol

from spotify_manager.application.ports.spotify_async import QueryValue


class SpotifyClient(Protocol):
    """Await the inventoried Spotify endpoints without choosing business policy."""

    async def get(self, path: str, query: dict[str, QueryValue] | None = None) -> Any:
        """Await one explicit GET operation.

        Args:
            path: Relative API path or full pagination URL.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        ...

    async def post(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> Any:
        """Await one explicit POST operation.

        Args:
            path: Relative API path or full pagination URL.
            payload: Original JSON body.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        ...

    async def put(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> Any:
        """Await one explicit PUT operation.

        Args:
            path: Relative API path or full pagination URL.
            payload: Original JSON body.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        ...

    async def delete(
        self,
        path: str,
        payload: object = None,
        query: dict[str, QueryValue] | None = None,
    ) -> Any:
        """Await one explicit DELETE operation.

        Args:
            path: Relative API path or full pagination URL.
            payload: Original JSON body.
            query: Original ordered request parameters.

        Returns:
            Original decoded response.
        """
        ...

    async def album(self, album_id: str, market: str | None = None) -> Any:
        """Await the original album endpoint contract.

        Args:
            album_id: Original SDK album id value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def album_tracks(
        self, album_id: str, limit: int = 50, offset: int = 0, market: str | None = None
    ) -> Any:
        """Await the original album tracks endpoint contract.

        Args:
            album_id: Original SDK album id value.
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def albums(self, albums: Sequence[str], market: str | None = None) -> Any:
        """Await the original albums endpoint contract.

        Args:
            albums: Original SDK albums value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def artist(self, artist_id: str) -> Any:
        """Await the original artist endpoint contract.

        Args:
            artist_id: Original SDK artist id value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def artist_albums(
        self,
        artist_id: str,
        album_type: str | None = None,
        include_groups: str | None = None,
        country: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Any:
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
        ...

    async def artist_top_tracks(self, artist_id: str, country: str = "US") -> Any:
        """Await the original artist top tracks endpoint contract.

        Args:
            artist_id: Original SDK artist id value.
            country: Original SDK country value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user(self) -> Any:
        """Await the original current user endpoint contract.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_followed_artists(
        self, limit: int = 20, after: str | None = None
    ) -> Any:
        """Await the original current user followed artists endpoint contract.

        Args:
            limit: Original SDK limit value.
            after: Original SDK after value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_following_artists(
        self, ids: Sequence[str] | None = None
    ) -> Any:
        """Await the original current user following artists endpoint contract.

        Args:
            ids: Original SDK ids value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_playlists(self, limit: int = 50, offset: int = 0) -> Any:
        """Await the original current user playlists endpoint contract.

        Args:
            limit: Original SDK limit value.
            offset: Original SDK offset value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_albums(
        self, limit: int = 20, offset: int = 0, market: str | None = None
    ) -> Any:
        """Await the original current user saved albums endpoint contract.

        Args:
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_albums_add(self, albums: Sequence[str] = ()) -> Any:
        """Await the original current user saved albums add endpoint contract.

        Args:
            albums: Original SDK albums value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_albums_contains(
        self, albums: Sequence[str] = ()
    ) -> Any:
        """Await the original current user saved albums contains endpoint contract.

        Args:
            albums: Original SDK albums value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_albums_delete(self, albums: Sequence[str] = ()) -> Any:
        """Await the original current user saved albums delete endpoint contract.

        Args:
            albums: Original SDK albums value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_tracks(
        self, limit: int = 20, offset: int = 0, market: str | None = None
    ) -> Any:
        """Await the original current user saved tracks endpoint contract.

        Args:
            limit: Original SDK limit value.
            offset: Original SDK offset value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_tracks_add(
        self, tracks: Sequence[str] | None = None
    ) -> Any:
        """Await the original current user saved tracks add endpoint contract.

        Args:
            tracks: Original SDK tracks value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def current_user_saved_tracks_contains(
        self, tracks: Sequence[str] | None = None
    ) -> Any:
        """Await the original current user saved tracks contains endpoint contract.

        Args:
            tracks: Original SDK tracks value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def next(self, result: object) -> Any:
        """Await the original next endpoint contract.

        Args:
            result: Original SDK result value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def playlist_add_items(
        self, playlist_id: str, items: Sequence[str], position: int | None = None
    ) -> Any:
        """Await the original playlist add items endpoint contract.

        Args:
            playlist_id: Original SDK playlist id value.
            items: Original SDK items value.
            position: Original SDK position value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def search(
        self,
        q: str,
        limit: int = 10,
        offset: int = 0,
        type: str = "track",  # noqa: A002 - Preserve the SDK keyword.
        market: str | None = None,
    ) -> Any:
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
        ...

    async def track(self, track_id: str, market: str | None = None) -> Any:
        """Await the original track endpoint contract.

        Args:
            track_id: Original SDK track id value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def tracks(self, tracks: Sequence[str], market: str | None = None) -> Any:
        """Await the original tracks endpoint contract.

        Args:
            tracks: Original SDK tracks value.
            market: Original SDK market value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def user_follow_artists(self, ids: Sequence[str] = ()) -> Any:
        """Await the original user follow artists endpoint contract.

        Args:
            ids: Original SDK ids value.

        Returns:
            Unmodified Spotify JSON, preserving empty and malformed values.
        """
        ...

    async def user_playlist_create(
        self,
        user: str,
        name: str,
        public: bool = True,
        collaborative: bool = False,
        description: str = "",
    ) -> Any:
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
        ...

    async def _get(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> Any:
        """Retain the SDK raw GET parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        ...

    async def _post(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> Any:
        """Retain the SDK raw POST parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        ...

    async def _put(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> Any:
        """Retain the SDK raw PUT parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        ...

    async def _delete(
        self,
        url: str,
        args: dict[str, QueryValue] | None = None,
        payload: object = None,
        **kwargs: QueryValue,
    ) -> Any:
        """Retain the SDK raw DELETE parameter convention at the adapter edge.

        Args:
            url: Original relative endpoint or complete pagination URL.
            args: Original query parameters.
            payload: Original optional JSON payload.
            **kwargs: Original additional query parameters, in encounter order.

        Returns:
            Unvalidated original Spotify JSON for the owning endpoint parser.
        """
        ...


class SpotifyClients(Protocol):
    """Acquire an independently scoped client at an explicit external read boundary."""

    async def client(self) -> SpotifyClient:
        """Acquire the next original client scope.

        Returns:
            Client with independent credential selection and owned resource lifetime.
        """
        ...
