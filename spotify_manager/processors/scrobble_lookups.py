"""Stable public track and Last.fm lookup entry points."""

from datetime import datetime as datetime
from pathlib import Path

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application import lookup_resolution
from spotify_manager.application.scrobble_lookup_run import status
from spotify_manager.bootstrap import scrobble_lookups as composition
from spotify_manager.domain import lookup_selection
from spotify_manager.domain.lookup_seasons import season_window as policy_season
from spotify_manager.domain.lookup_values import (
    AmbiguousTrackError as AmbiguousTrackError,
)
from spotify_manager.domain.lookup_values import ResolvedTrack as ResolvedTrack
from spotify_manager.domain.lookup_values import SeasonWindow as SeasonWindow
from spotify_manager.domain.lookup_values import (
    TrackNotFoundError as TrackNotFoundError,
)
from spotify_manager.infrastructure import lookup_records
from spotify_manager.models.lookups import TrackScrobbleStatus
from spotify_manager.processors.library_lookups import (
    SpotifyLookupResponseError as SpotifyLookupResponseError,
)


SPOTIFY_SEARCH_LIMIT = 10


def season_window(when: datetime) -> SeasonWindow:
    """Retain original Berlin-local meteorological season boundaries.

    Args:
        when: Original effective observation time.

    Returns:
        Original local season label and boundaries.
    """
    return policy_season(when, composition.TIMEZONE)


def _track_from_spotify(raw: object) -> ResolvedTrack | None:
    return lookup_records.track(raw)


def _matching_tracks(raw_items: list[object], name: str) -> list[ResolvedTrack]:
    return lookup_selection.matching_tracks(
        lookup_records.track_identities(raw_items), name
    )


def resolve_live_track(
    sp: Spotify, *, name: str | None = None, track_id: str | None = None
) -> ResolvedTrack:
    """Resolve original direct identity or exact/edition-qualified title matches.

    Args:
        sp: Original caller-owned synchronous client.
        name: Original optional title.
        track_id: Original direct identity taking precedence.

    Returns:
        Original unique primary-artist representative.

    Raises:
        ValueError: No original reference is provided.
        TrackNotFoundError: No original match exists.
        AmbiguousTrackError: Multiple original primary artists match.
        SpotifyLookupResponseError: Original response validation fails.
    """
    return lookup_resolution.track(composition.track_lookup(sp), name, track_id)


def _direct_track(sp: Spotify, identifier: str) -> ResolvedTrack:
    try:
        track = _track_from_spotify(sp.track(identifier))
    except SpotifyException as error:
        if error.http_status == 404:
            raise TrackNotFoundError(
                f"Spotify track id {identifier!r} was not found."
            ) from error
        raise
    if track is None:
        raise SpotifyLookupResponseError(
            f"Spotify returned invalid track data for {identifier!r}."
        )
    return track


def _track_search(sp: Spotify, name: str) -> list[object]:
    escaped = name.replace('"', " ").strip()
    response = sp.search(
        q=f'track:"{escaped}"', type="track", limit=SPOTIFY_SEARCH_LIMIT, offset=0
    )
    return lookup_records.search_items(
        response, "tracks", f"Spotify returned invalid track search data for {name!r}."
    )


def _last_scrobble_at(
    path: Path, *, track_name: str, artist_name: str
) -> datetime | None:
    return composition.latest(path, track_name, artist_name)


def get_track_scrobble_status(
    sp: Spotify,
    *,
    name: str | None = None,
    track_id: str | None = None,
    path: Path = composition.DEFAULT_SCROBBLES_PATH,
    now: datetime | None = None,
) -> TrackScrobbleStatus:
    """Observe original live identity, latest play and local season in order.

    Args:
        sp: Original caller-owned synchronous client.
        name: Original optional exact title.
        track_id: Original direct identity taking precedence.
        path: Original history location, including compressed fallbacks.
        now: Original supplied effective observation time or none.

    Returns:
        Original complete track-scrobble status.
    """
    return status(composition.resources(sp, name, track_id, path, now))
