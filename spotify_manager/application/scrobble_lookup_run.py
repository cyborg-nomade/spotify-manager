"""Original ordered track resolution, latest-history and season observations."""

from dataclasses import dataclass
from datetime import datetime
from datetime import tzinfo
from typing import Protocol
from typing import cast

from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.lookup_effects import TrackLookup
from spotify_manager.application.lookup_resolution import track as resolve_track
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.lookup_seasons import season_window
from spotify_manager.domain.titles import without_sliding_qualifiers
from spotify_manager.models.lookups import TrackScrobbleStatus


class TrackHistory(Protocol):
    """Read latest matching play facts."""

    def latest(self, track: str, artist: str) -> datetime | None:
        """Read the latest play for resolved metadata.

        Args:
            track: Resolved title.
            artist: Resolved primary artist.

        Returns:
            Latest play time, or none.
        """
        ...


class LookupClock(Protocol):
    """Observe time after the lookup's external reads."""

    def now(self) -> datetime:
        """Observe current time.

        Returns:
            Effective local instant.
        """
        ...


@dataclass(frozen=True)
class TrackHistoryLookup:
    """Describe track lookup, history authority and time observations.

    Args:
        tracks: Direct and search track observations.
        history: History reader.
        name: Optional exact title.
        identifier: Preferred direct identity.
        clock: Clock observed after history.
        timezone: Caller-owned local timezone.
    """

    tracks: TrackLookup
    history: TrackHistory
    name: str | None
    identifier: str | None
    clock: LookupClock
    timezone: tzinfo


def status(deps: TrackHistoryLookup) -> TrackScrobbleStatus:
    """Read original history before observing current and previous seasons.

    Args:
        deps: Original explicitly supplied lookup stages.

    Returns:
        Original complete track-scrobble status model.
    """
    track = resolve_track(deps.tracks, deps.name, deps.identifier)
    latest = deps.history.latest(track.name, track.primary_artist)
    current = season_window(deps.clock.now(), deps.timezone)
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
) -> int | None:
    """Match original history before validating only relevant timestamps.

    Args:
        rows: Original unchecked history rows in encounter order.
        track: Original normalized title.
        artist: Original normalized primary artist.

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


def checked_row(raw: object, index: int) -> dict[str, object]:
    """Validate each row before matching its identity.

    Args:
        raw: Unchecked row.
        index: Original encounter position.

    Returns:
        The same mapping.

    Raises:
        LastFmExportError: A row is not an object.
    """
    if not isinstance(raw, dict):
        raise LastFmExportError(f"Scrobble {index} is not an object.")
    return cast(dict[str, object], raw)


def checked_timestamp(row: dict[str, object], index: int) -> int:
    """Coerce a matching date without tightening numeric acceptance.

    Args:
        row: Matching row.
        index: Original encounter position.

    Returns:
        Coerced millisecond timestamp.

    Raises:
        LastFmExportError: Date indexing or integer conversion fails.
    """
    try:
        return int(cast(int | str, row["date"]))
    except (KeyError, TypeError, ValueError) as error:
        raise LastFmExportError(
            f"Scrobble {index} has no valid millisecond timestamp."
        ) from error
