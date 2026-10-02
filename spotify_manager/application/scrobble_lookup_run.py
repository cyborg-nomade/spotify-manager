"""Original ordered track resolution, latest-history and season observations."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import tzinfo

from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.lookup_seasons import season_window
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.titles import without_sliding_qualifiers
from spotify_manager.models.lookups import TrackScrobbleStatus


@dataclass(frozen=True)
class TrackHistoryLookup:
    """Supply original resolution, history and clock stages.

    Args:
        resolve: Original live track resolution.
        latest: Original latest matching play read.
        now: Original delayed current-clock observation.
        timezone: Original caller-owned local timezone.
    """

    resolve: Callable[[], ResolvedTrack]
    latest: Callable[[str, str], datetime | None]
    now: Callable[[], datetime]
    timezone: tzinfo


def status(deps: TrackHistoryLookup) -> TrackScrobbleStatus:
    """Read original history before observing current and previous seasons.

    Args:
        deps: Original explicitly supplied lookup stages.

    Returns:
        Original complete track-scrobble status model.
    """
    track = deps.resolve()
    latest = deps.latest(track.name, track.primary_artist)
    current = season_window(deps.now(), deps.timezone)
    last = season_window(latest, deps.timezone) if latest else None
    return TrackScrobbleStatus(
        track_name=track.name,
        track_id=track.spotify_id,
        artist_name=track.primary_artist,
        album_name=track.album,
        last_scrobbled_at=latest,
        last_scrobble_season=last.label if last else None,
        current_season=current.label,
        in_current_season=latest is not None and current.start <= latest < current.end,
        source="spotify-live + lastfm-history",
    )


def latest_history_timestamp(
    rows: list[object],
    track: str,
    artist: str,
    checked_row: Callable[[object, int], dict[str, object]],
    checked_timestamp: Callable[[dict[str, object], int], int],
) -> int | None:
    """Match original history before validating only relevant timestamps.

    Args:
        rows: Original unchecked history rows in encounter order.
        track: Original normalized title.
        artist: Original normalized primary artist.
        checked_row: Original row container codec.
        checked_timestamp: Original matching-row date codec.

    Returns:
        Greatest original matching timestamp, or no matching play.
    """
    latest: int | None = None
    for index, raw in enumerate(rows):
        row = checked_row(raw, index)
        if normalize_name(str(row.get("artist") or "")) != artist:
            continue
        raw_track = without_sliding_qualifiers(str(row.get("track") or ""))
        if normalize_name(raw_track) != track:
            continue
        timestamp = checked_timestamp(row, index)
        if latest is None or timestamp > latest:
            latest = timestamp
    return latest
