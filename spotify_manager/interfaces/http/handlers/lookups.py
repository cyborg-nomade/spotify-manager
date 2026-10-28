"""Validate and present lookups HTTP requests."""

from typing import Protocol

from fastapi import HTTPException
from requests.exceptions import RequestException

from spotify_manager.application.album_review import AlbumReviewRequest
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.common import CommandResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus
from spotify_manager.models.your_library import YourLibraryFile


SPOTIFY_UNAVAILABLE = (
    "Spotify could not be reached after several attempts. Please try again shortly."
)


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


def refresh_library() -> CommandResult:
    """Drop the cached library so the next request re-reads YourLibrary.json.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    jobs.get_library.cache_clear()
    return CommandResult(command="library_refresh")


async def artist_stats(
    client: Spotify, reference: str | None, name: str | None, artist_id: str | None
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
            name, artist_id = jobs.parse_spotify_lookup_reference(reference, "artist")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not name and (not artist_id):
        raise HTTPException(
            status_code=400, detail="provide an artist name, ID, or Spotify link"
        )
    try:
        return await jobs.get_live_artist_library_stats(
            client, name=name, artist_id=artist_id
        )
    except RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=SPOTIFY_UNAVAILABLE,
        ) from exc


def album_request(
    reference: str | None,
    name: str | None,
    album_id: str | None,
    artist: str | None,
    threshold: float,
) -> AlbumReviewRequest:
    """Validate the existing album query before application execution.

    Args:
        reference: Spotify link, URI, identifier or name.
        name: Exact album title.
        album_id: Direct catalog identifier.
        artist: Optional artist disambiguation.
        threshold: Existing retention threshold.

    Returns:
        An application request with the resolved reference.

    Raises:
        HTTPException: The reference is malformed or missing.
    """
    if reference is not None:
        try:
            name, album_id = jobs.parse_spotify_lookup_reference(reference, "album")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not name and (not album_id):
        raise HTTPException(
            status_code=400, detail="provide an album name, ID, or Spotify link"
        )
    return AlbumReviewRequest(name, album_id, artist, threshold)


async def track_scrobble_status(
    client: Spotify, reference: str | None, name: str | None, track_id: str | None
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
            name, track_id = jobs.parse_spotify_lookup_reference(reference, "track")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not name and (not track_id):
        raise HTTPException(
            status_code=400, detail="provide a track name, ID, or Spotify link"
        )
    try:
        return await jobs.get_track_scrobble_status(
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
            detail=SPOTIFY_UNAVAILABLE,
        ) from exc
