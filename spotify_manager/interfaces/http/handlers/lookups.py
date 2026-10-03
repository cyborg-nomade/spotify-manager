"""Original lookups HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from requests.exceptions import RequestException
from spotipy import Spotify

from spotify_manager.interfaces.http.models.common import CommandResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus
from spotify_manager.models.your_library import YourLibraryFile


class CachedLibrary(Protocol):
    """Expose the original cached library provider and explicit invalidation."""

    def __call__(self) -> YourLibraryFile:
        """Read the existing cached library.

        Returns:
            Original parsed library export.
        """
        ...

    def cache_clear(self) -> None:
        """Invalidate the original process-local library cache."""
        ...


@dataclass(kw_only=True)
class LookupsHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        evaluate_album_live: Existing overridable feature dependency.
        get_library: Existing overridable feature dependency.
        get_live_artist_library_stats: Existing overridable feature dependency.
        get_track_scrobble_status: Existing overridable feature dependency.
        parse_spotify_lookup_reference: Existing overridable feature dependency.
    """

    evaluate_album_live: Callable[..., AlbumEvaluation]
    get_library: CachedLibrary
    get_live_artist_library_stats: Callable[..., ArtistLibraryStats]
    get_track_scrobble_status: Callable[..., TrackScrobbleStatus]
    parse_spotify_lookup_reference: Callable[..., tuple[str | None, str | None]]

    def refresh_library(self) -> CommandResult:
        """Drop the cached library so the next request re-reads YourLibrary.json.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        self.get_library.cache_clear()
        return CommandResult(command="library_refresh")

    def artist_stats(
        self,
        client: Spotify,
        reference: str | None,
        name: str | None,
        artist_id: str | None,
    ) -> ArtistLibraryStats:
        """Return live Liked Songs and Saved Albums counts for one artist.

        Args:
            client: Original validated client value.
            reference: Original validated reference value.
            name: Original validated name value.
            artist_id: Original validated artist id value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        if reference is not None:
            try:
                name, artist_id = self.parse_spotify_lookup_reference(
                    reference, "artist"
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not name and (not artist_id):
            raise HTTPException(
                status_code=400, detail="provide an artist name, ID, or Spotify link"
            )
        try:
            return self.get_live_artist_library_stats(
                client, name=name, artist_id=artist_id
            )
        except RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Spotify could not be reached after several "
                    "attempts. Please try again shortly."
                ),
            ) from exc

    def album_evaluation(
        self,
        client: Spotify,
        reference: str | None,
        name: str | None,
        album_id: str | None,
        artist: str | None,
        threshold: float,
    ) -> AlbumEvaluation:
        """Return a keep/remove decision from live Spotify album and liked state.

        Args:
            client: Original validated client value.
            reference: Original validated reference value.
            name: Original validated name value.
            album_id: Original validated album id value.
            artist: Original validated artist value.
            threshold: Original validated threshold value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        if reference is not None:
            try:
                name, album_id = self.parse_spotify_lookup_reference(reference, "album")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not name and (not album_id):
            raise HTTPException(
                status_code=400, detail="provide an album name, ID, or Spotify link"
            )
        try:
            return self.evaluate_album_live(
                client, name=name, album_id=album_id, artist=artist, threshold=threshold
            )
        except RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Spotify could not be reached after several "
                    "attempts. Please try again shortly."
                ),
            ) from exc

    def track_scrobble_status(
        self,
        client: Spotify,
        reference: str | None,
        name: str | None,
        track_id: str | None,
    ) -> TrackScrobbleStatus:
        """Return the latest Last.fm scrobble for one live Spotify track.

        Args:
            client: Original validated client value.
            reference: Original validated reference value.
            name: Original validated name value.
            track_id: Original validated track id value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        if reference is not None:
            try:
                name, track_id = self.parse_spotify_lookup_reference(reference, "track")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not name and (not track_id):
            raise HTTPException(
                status_code=400, detail="provide a track name, ID, or Spotify link"
            )
        try:
            return self.get_track_scrobble_status(
                client,
                name=name,
                track_id=track_id,
                path=scrobble_history.DEFAULT_SCROBBLES_PATH,
            )
        except blast_from_past.LastFmExportError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Spotify could not be reached after several "
                    "attempts. Please try again shortly."
                ),
            ) from exc
