"""Compose original track-history reads without private routine dependencies."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.scrobble_lookup_run import TrackHistoryLookup
from spotify_manager.infrastructure import scrobble_lookup as history
from spotify_manager.infrastructure.lookup_resources import SpotifyTrackLookup


TIMEZONE = ZoneInfo("Europe/Berlin")
DEFAULT_SCROBBLES_PATH = (
    Path(__file__).resolve().parent.parent / "files/lastfmstats-man-et-arms.json"
)


async def latest(path: Path, track: str, artist: str) -> datetime | None:
    """Bind original public export codec and matching timestamp boundary.

    Args:
        path: Original history location.
        track: Original resolved title.
        artist: Original resolved primary artist.

    Returns:
        Original latest matching play or none.
    """
    return await history.latest(path, track, artist, TIMEZONE)


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
    return TrackHistoryLookup(
        SpotifyTrackLookup(client),
        history.ScrobbleHistory(path, TIMEZONE),
        name,
        identifier,
        history.ScrobbleClock(now, TIMEZONE),
        TIMEZONE,
    )


def track_lookup(client: Spotify) -> SpotifyTrackLookup:
    """Construct direct and search observations.

    Args:
        client: Caller-owned synchronous client.

    Returns:
        Named track catalog.
    """
    return SpotifyTrackLookup(client)
