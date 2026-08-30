"""Resolve Spotify tracks and inspect their persisted Last.fm history."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.models.lookups import TrackScrobbleStatus
from spotify_manager.processors.library_lookups import SpotifyLookupResponseError
from spotify_manager.routines import blast_from_past


SPOTIFY_SEARCH_LIMIT = 10


class TrackNotFoundError(LookupError):
    """Raised when a Spotify track cannot be resolved."""


class AmbiguousTrackError(LookupError):
    """Raised when a title belongs to more than one Spotify artist."""

    def __init__(self, message: str, candidates: list[dict[str, str]]) -> None:
        """Store the user-facing error and Spotify candidates."""
        super().__init__(message)
        self.candidates = candidates


@dataclass(frozen=True)
class ResolvedTrack:
    """The Spotify identity needed for a Last.fm history lookup."""

    spotify_id: str
    name: str
    primary_artist: str
    album: str | None
    popularity: int


@dataclass(frozen=True)
class SeasonWindow:
    """One Berlin-local meteorological season."""

    label: str
    start: datetime
    end: datetime


def season_window(when: datetime) -> SeasonWindow:
    """Return the meteorological season containing ``when`` in Berlin."""
    local = when.astimezone(blast_from_past.SCROBBLE_TIMEZONE)
    year = local.year
    timezone = blast_from_past.SCROBBLE_TIMEZONE
    if 3 <= local.month <= 5:
        return SeasonWindow(
            f"Spring {year}",
            datetime(year, 3, 1, tzinfo=timezone),
            datetime(year, 6, 1, tzinfo=timezone),
        )
    if 6 <= local.month <= 8:
        return SeasonWindow(
            f"Summer {year}",
            datetime(year, 6, 1, tzinfo=timezone),
            datetime(year, 9, 1, tzinfo=timezone),
        )
    if 9 <= local.month <= 11:
        return SeasonWindow(
            f"Autumn {year}",
            datetime(year, 9, 1, tzinfo=timezone),
            datetime(year, 12, 1, tzinfo=timezone),
        )
    winter_year = year if local.month == 12 else year - 1
    return SeasonWindow(
        f"Winter {winter_year}/{winter_year + 1}",
        datetime(winter_year, 12, 1, tzinfo=timezone),
        datetime(winter_year + 1, 3, 1, tzinfo=timezone),
    )


def _track_from_spotify(raw: object) -> ResolvedTrack | None:
    """Validate and minimize one Spotify track response."""
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    raw_artists = raw.get("artists")
    if not isinstance(raw_artists, list) or not raw_artists:
        return None
    first_artist = raw_artists[0]
    if not isinstance(first_artist, dict):
        return None
    primary_artist = str(first_artist.get("name") or "").strip()
    raw_album = raw.get("album")
    album = (
        str(raw_album.get("name") or "").strip() or None
        if isinstance(raw_album, dict)
        else None
    )
    popularity = raw.get("popularity")
    if not spotify_id or not name or not primary_artist:
        return None
    return ResolvedTrack(
        spotify_id=spotify_id,
        name=name,
        primary_artist=primary_artist,
        album=album,
        popularity=popularity if isinstance(popularity, int) else 0,
    )


def _matching_tracks(raw_items: list[object], name: str) -> list[ResolvedTrack]:
    """Return exact-title matches, allowing Spotify edition suffixes second."""
    tracks = [
        track for raw in raw_items if (track := _track_from_spotify(raw)) is not None
    ]
    expected = blast_from_past.normalize_name(name)
    exact = [
        track
        for track in tracks
        if blast_from_past.normalize_name(track.name) == expected
    ]
    if exact:
        return exact
    return [
        track
        for track in tracks
        if blast_from_past.name_similarity(name, track.name) == 1.0
    ]


def resolve_live_track(
    sp: Spotify,
    *,
    name: str | None = None,
    track_id: str | None = None,
) -> ResolvedTrack:
    """Resolve one Spotify track by ID or exact title."""
    if not name and not track_id:
        raise ValueError("provide name or track_id")
    if track_id:
        try:
            track = _track_from_spotify(sp.track(track_id))
        except SpotifyException as exc:
            if exc.http_status == 404:
                raise TrackNotFoundError(
                    f"Spotify track id {track_id!r} was not found."
                ) from exc
            raise
        if track is None:
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid track data for {track_id!r}."
            )
        return track

    assert name is not None
    escaped_name = name.replace('"', " ").strip()
    response = sp.search(
        q=f'track:"{escaped_name}"',
        type="track",
        limit=SPOTIFY_SEARCH_LIMIT,
        offset=0,
    )
    page = response.get("tracks") if isinstance(response, dict) else None
    raw_items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(raw_items, list):
        raise SpotifyLookupResponseError(
            f"Spotify returned invalid track search data for {name!r}."
        )
    matches = _matching_tracks(raw_items, name)
    if not matches:
        raise TrackNotFoundError(f"No exact Spotify track named {name!r} was found.")

    by_artist: dict[str, list[ResolvedTrack]] = {}
    for track in matches:
        artist_key = blast_from_past.normalize_name(track.primary_artist)
        by_artist.setdefault(artist_key, []).append(track)
    representatives = [
        max(artist_tracks, key=lambda track: track.popularity)
        for artist_tracks in by_artist.values()
    ]
    if len(representatives) > 1:
        candidates = [
            {
                "track": track.name,
                "artist": track.primary_artist,
                "album": track.album or "",
                "id": track.spotify_id,
            }
            for track in representatives
        ]
        raise AmbiguousTrackError(
            f"Spotify returned {len(representatives)} exact tracks named {name!r}; "
            "use a Spotify track link or ID to disambiguate.",
            candidates,
        )
    return representatives[0]


def _last_scrobble_at(
    path: Path,
    *,
    track_name: str,
    artist_name: str,
) -> datetime | None:
    """Return the latest matching scrobble in the shared history."""
    payload = blast_from_past.load_scrobble_export(path)
    raw_scrobbles = payload["scrobbles"]
    assert isinstance(raw_scrobbles, list)
    expected_track = blast_from_past.normalize_name(
        blast_from_past.without_sliding_qualifiers(track_name)
    )
    expected_artist = blast_from_past.normalize_name(artist_name)
    latest_timestamp: int | None = None
    for index, raw in enumerate(raw_scrobbles):
        if not isinstance(raw, dict):
            raise blast_from_past.LastFmExportError(
                f"Scrobble {index} is not an object."
            )
        raw_artist = blast_from_past.normalize_name(str(raw.get("artist") or ""))
        if raw_artist != expected_artist:
            continue
        raw_track = blast_from_past.without_sliding_qualifiers(
            str(raw.get("track") or "")
        )
        if blast_from_past.normalize_name(raw_track) != expected_track:
            continue
        try:
            timestamp = int(raw["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise blast_from_past.LastFmExportError(
                f"Scrobble {index} has no valid millisecond timestamp."
            ) from exc
        if latest_timestamp is None or timestamp > latest_timestamp:
            latest_timestamp = timestamp
    if latest_timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(
            latest_timestamp / 1000,
            blast_from_past.SCROBBLE_TIMEZONE,
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise blast_from_past.LastFmExportError(
            "The latest matching scrobble has an out-of-range timestamp."
        ) from exc


def get_track_scrobble_status(
    sp: Spotify,
    *,
    name: str | None = None,
    track_id: str | None = None,
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    now: datetime | None = None,
) -> TrackScrobbleStatus:
    """Resolve a track and report its latest Last.fm play and season."""
    track = resolve_live_track(sp, name=name, track_id=track_id)
    last_scrobbled_at = _last_scrobble_at(
        path,
        track_name=track.name,
        artist_name=track.primary_artist,
    )
    current_time = now or datetime.now(blast_from_past.SCROBBLE_TIMEZONE)
    current = season_window(current_time)
    last_season = season_window(last_scrobbled_at) if last_scrobbled_at else None
    return TrackScrobbleStatus(
        track_name=track.name,
        track_id=track.spotify_id,
        artist_name=track.primary_artist,
        album_name=track.album,
        last_scrobbled_at=last_scrobbled_at,
        last_scrobble_season=last_season.label if last_season else None,
        current_season=current.label,
        in_current_season=(
            last_scrobbled_at is not None
            and current.start <= last_scrobbled_at < current.end
        ),
        source="spotify-live + lastfm-history",
    )
