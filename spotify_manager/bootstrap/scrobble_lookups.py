"""Compose original track-history reads without private routine dependencies."""

from datetime import datetime
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from spotipy import Spotify

from spotify_manager.application.lookup_effects import TrackLookup
from spotify_manager.application.scrobble_lookup_run import TrackHistoryLookup
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.infrastructure import scrobble_lookup as history


TIMEZONE = ZoneInfo("Europe/Berlin")
DEFAULT_SCROBBLES_PATH = (
    Path(__file__).resolve().parent.parent / "files/lastfmstats-man-et-arms.json"
)


def latest(path: Path, track: str, artist: str) -> datetime | None:
    """Bind original public export codec and matching timestamp boundary.

    Args:
        path: Original history location.
        track: Original resolved title.
        artist: Original resolved primary artist.

    Returns:
        Original latest matching play or none.
    """
    from spotify_manager.routines import blast_from_past

    return history.latest(
        blast_from_past.load_scrobble_export, path, track, artist, TIMEZONE
    )


def resources(
    client: Spotify,
    name: str | None,
    identifier: str | None,
    path: Path,
    now: datetime | None,
) -> TrackHistoryLookup:
    """Bind original track resolution, public history seam and delayed clock.

    Args:
        client: Original caller-owned synchronous client.
        name: Original optional exact title.
        identifier: Original direct identity.
        path: Original history location.
        now: Original supplied effective time or none.

    Returns:
        Explicit original ordered lookup dependencies.
    """
    from spotify_manager.processors import scrobble_lookups as legacy

    return TrackHistoryLookup(
        partial(legacy.resolve_live_track, client, name=name, track_id=identifier),
        partial(_read_latest, path),
        partial(_current_time, now),
        TIMEZONE,
    )


def _read_latest(path: Path, track: str, artist: str) -> datetime | None:
    from spotify_manager.processors import scrobble_lookups as legacy

    return legacy._last_scrobble_at(path, track_name=track, artist_name=artist)


def _current_time(now: datetime | None) -> datetime:
    from spotify_manager.processors import scrobble_lookups as legacy

    return now or legacy.datetime.now(TIMEZONE)


def track_lookup(client: Spotify) -> TrackLookup:
    """Bind original direct and search track observation seams.

    Args:
        client: Original caller-owned synchronous client.

    Returns:
        Original track reads without constructing an environment client.
    """
    from spotify_manager.processors import scrobble_lookups as legacy

    return TrackLookup(
        partial(legacy._direct_track, client), partial(_track_candidates, client)
    )


def _track_candidates(client: Spotify, name: str) -> list[ResolvedTrack]:
    from spotify_manager.infrastructure import lookup_records
    from spotify_manager.processors import scrobble_lookups as legacy

    return lookup_records.track_identities(legacy._track_search(client, name))
