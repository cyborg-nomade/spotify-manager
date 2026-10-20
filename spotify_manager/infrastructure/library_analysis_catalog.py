"""Synchronous library observations and tolerant transport decoding."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotipy import Spotify

from spotify_manager.application.library_analysis_effects import OffsetRead
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.infrastructure import library_analysis_files as files
from spotify_manager.infrastructure.library_models import album_from_saved_item


@dataclass(frozen=True)
class SpotifyAnalysisCatalog:
    """Own caller-supplied synchronous resources and original retry configuration.

    Args:
        spotify: Original caller-owned client or none for offline preparation.
    """

    spotify: Spotify | None

    def offset(self, resource: ResourceName, initial: bool) -> OffsetRead:
        """Select the original method at its original durable scan boundary.

        Args:
            resource: Original saved-resource identity.
            initial: Whether this is the initial monotonic scan.

        Returns:
            Original selected caller-owned method.
        """
        return SpotifyOffsetPages(cast(Spotify, self.spotify), resource, initial)

    def artists(self, after: str | None) -> object:
        """Read the original cursor scan with immediate endpoint fallback.

        Args:
            after: Original stored cursor or none.

        Returns:
            Original unvalidated cursor page.
        """
        from spotify_manager.routines.analyse_library import fetch_followed_artists_page

        return fetch_followed_artists_page(cast(Spotify, self.spotify), after)

    def reconcile_artists(self, after: str | None) -> object:
        """Read the original reconciliation cursor page.

        Args:
            after: Original current pass cursor or none.

        Returns:
            Original unvalidated cursor page.
        """
        from spotify_manager.routines.analyse_library import _reconcile_artist_page

        return _reconcile_artist_page(cast(Spotify, self.spotify), after)

    def following(self, identities: list[str]) -> object:
        """Read original complete live follow verification facts.

        Args:
            identities: Original ordered candidate batch.

        Returns:
            Original unvalidated follow statuses.
        """
        from spotify_manager.routines.analyse_library import _following_artists

        return _following_artists(cast(Spotify, self.spotify), identities)

    def convert(self, row: object, resource: ResourceName) -> LibraryModel | None:
        """Decode a saved resource row without configurable parsing callbacks.

        Args:
            row: Unvalidated transport row.
            resource: Active resource.

        Returns:
            Accepted model, or none for an unusable row.
        """
        if resource == "albums":
            return album_from_saved_item(row)
        if resource == "tracks":
            return files.track_from_saved_item(row)
        return files.artist_from_api_item(row)

    def items(self, page: object, resource: ResourceName) -> list[object]:
        """Validate a saved-resource response.

        Args:
            page: Unvalidated response.
            resource: Active resource.

        Returns:
            Complete raw rows.
        """
        return files.page_items(page, resource)

    def artist_items(self, page: object) -> tuple[list[object], dict[str, object]]:
        """Validate a followed-artists response.

        Args:
            page: Unvalidated response.

        Returns:
            Complete raw rows and cursor envelope.
        """
        return files.followed_artist_page_items(page)


@dataclass(frozen=True)
class SpotifyOffsetPages:
    """Capture one SDK endpoint at the original scan boundary.

    Args:
        spotify: Caller-owned client.
        resource: Saved resource.
        initial: Whether this is the initial scan.
    """

    spotify: Spotify
    resource: ResourceName
    initial: bool
    _method: Callable[..., object] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture the transport handle before the first request."""
        from spotify_manager.routines.analyse_library import _initial_offset_reader
        from spotify_manager.routines.analyse_library import _reconcile_offset_reader

        if self.initial:
            method = _initial_offset_reader(self.spotify, self.resource)
        else:
            method = _reconcile_offset_reader(self.spotify, self.resource)
        object.__setattr__(self, "_method", method)

    def read(self, *, limit: int, offset: int) -> object:
        """Read the selected SDK endpoint.

        Args:
            limit: Original page size.
            offset: Original raw-row offset.

        Returns:
            Unvalidated SDK response.
        """
        return self._method(limit=limit, offset=offset)
