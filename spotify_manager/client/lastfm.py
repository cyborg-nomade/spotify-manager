"""Small read-only client for the documented Last.fm API."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen


LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
LASTFM_USER_AGENT = "spotify-manager/0.1.0 (u.fiori@iib-institut.de)"
LASTFM_TIMEOUT_SECONDS = 30
TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
TRANSIENT_LASTFM_ERRORS = frozenset({11, 16, 29})
EventCallback = Callable[[str], None]
Sleeper = Callable[[float], None]


class LastFmError(RuntimeError):
    """Base error for documented Last.fm API requests."""


class LastFmResponseError(LastFmError):
    """Raised when Last.fm returns an error or an invalid response."""


@dataclass(frozen=True)
class LastFmSimilarTrack:
    """One track returned by ``track.getSimilar``."""

    artist: str
    track: str
    match: float


@dataclass(frozen=True)
class LastFmRecentTrack:
    """One dated scrobble returned by ``user.getRecentTracks``."""

    artist: str
    track: str
    album: str
    timestamp_seconds: int


class LastFmClient:
    """Call the public Last.fm API with bounded transient retries."""

    def __init__(
        self,
        api_key: str,
        username: str,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        event_callback: EventCallback | None = None,
        sleeper: Sleeper = sleep,
    ) -> None:
        """Store non-session credentials and retry configuration."""
        if not api_key.strip():
            raise ValueError("Last.fm API key must not be empty.")
        if not username.strip():
            raise ValueError("Last.fm username must not be empty.")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")

        self.api_key = api_key.strip()
        self.username = username.strip()
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.event_callback = event_callback
        self.sleeper = sleeper

    def _emit(self, message: str) -> None:
        """Forward a safe progress message when a callback is configured."""
        if self.event_callback is not None:
            self.event_callback(message)

    def _retry_delay(self, attempt: int) -> float:
        """Return the exponential delay before the next attempt."""
        return self.backoff_seconds * (2**attempt)

    def _request(self, method: str, **params: object) -> dict[str, Any]:
        """Return one decoded API response without exposing the API key."""
        query = urlencode(
            {
                "method": method,
                "api_key": self.api_key,
                "format": "json",
                **params,
            }
        )
        request = Request(
            f"{LASTFM_API_URL}?{query}",
            headers={"User-Agent": LASTFM_USER_AGENT},
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=LASTFM_TIMEOUT_SECONDS) as response:
                    payload = json.loads(response.read())
            except HTTPError as exc:
                if exc.code in TRANSIENT_HTTP_STATUSES and attempt < self.max_retries:
                    delay = self._retry_delay(attempt)
                    self._emit(
                        f"Last.fm returned HTTP {exc.code}; retrying in "
                        f"{delay:g} seconds."
                    )
                    self.sleeper(delay)
                    continue
                raise LastFmResponseError(
                    f"Last.fm request {method} failed with HTTP {exc.code}."
                ) from exc
            except (TimeoutError, URLError) as exc:
                if attempt < self.max_retries:
                    delay = self._retry_delay(attempt)
                    self._emit(
                        f"Last.fm request {method} could not connect; retrying "
                        f"in {delay:g} seconds."
                    )
                    self.sleeper(delay)
                    continue
                raise LastFmResponseError(
                    f"Last.fm request {method} could not connect."
                ) from exc
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise LastFmResponseError(
                    f"Last.fm request {method} returned invalid JSON."
                ) from exc

            if not isinstance(payload, dict):
                raise LastFmResponseError(
                    f"Last.fm request {method} returned an invalid object."
                )

            error_code = payload.get("error")
            if error_code is None:
                return payload

            try:
                numeric_error = int(error_code)
            except TypeError, ValueError:
                numeric_error = -1
            message = str(payload.get("message") or "unknown Last.fm error")
            if numeric_error in TRANSIENT_LASTFM_ERRORS and attempt < self.max_retries:
                delay = self._retry_delay(attempt)
                self._emit(
                    f"Last.fm error {numeric_error}; retrying in {delay:g} seconds."
                )
                self.sleeper(delay)
                continue
            raise LastFmResponseError(
                f"Last.fm request {method} failed ({numeric_error}): {message}"
            )

        raise AssertionError("Last.fm retry loop ended unexpectedly")

    def similar_tracks(
        self,
        artist: str,
        track: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Return ranked tracks similar to one seed track."""
        payload = self._request(
            "track.getSimilar",
            artist=artist,
            track=track,
            autocorrect=1,
            limit=limit,
        )
        container = payload.get("similartracks")
        raw_tracks = container.get("track") if isinstance(container, dict) else None
        if not isinstance(raw_tracks, list):
            raise LastFmResponseError(
                "Last.fm track.getSimilar returned invalid track data."
            )

        results: list[LastFmSimilarTrack] = []
        for raw_track in raw_tracks:
            if not isinstance(raw_track, dict):
                continue
            raw_artist = raw_track.get("artist")
            artist_name = (
                str(raw_artist.get("name") or "").strip()
                if isinstance(raw_artist, dict)
                else ""
            )
            track_name = str(raw_track.get("name") or "").strip()
            try:
                match = float(raw_track.get("match") or 0)
            except TypeError, ValueError:
                continue
            if artist_name and track_name and match > 0:
                results.append(
                    LastFmSimilarTrack(
                        artist=artist_name,
                        track=track_name,
                        match=match,
                    )
                )
        return tuple(results)

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ) -> tuple[LastFmRecentTrack, ...]:
        """Return every dated scrobble in one closed UTC timestamp range."""
        if from_timestamp > to_timestamp:
            return ()

        page = 1
        total_pages = 1
        results: list[LastFmRecentTrack] = []
        while page <= total_pages:
            payload = self._request(
                "user.getRecentTracks",
                user=self.username,
                extended=0,
                limit=limit,
                page=page,
                **{"from": from_timestamp, "to": to_timestamp},
            )
            container = payload.get("recenttracks")
            raw_tracks = container.get("track") if isinstance(container, dict) else None
            attributes = container.get("@attr") if isinstance(container, dict) else None
            if not isinstance(raw_tracks, list) or not isinstance(attributes, dict):
                raise LastFmResponseError(
                    "Last.fm user.getRecentTracks returned invalid track data."
                )
            try:
                total_pages = max(1, int(attributes.get("totalPages") or 1))
            except (TypeError, ValueError) as exc:
                raise LastFmResponseError(
                    "Last.fm user.getRecentTracks returned invalid pagination."
                ) from exc

            for raw_track in raw_tracks:
                parsed = _parse_recent_track(raw_track)
                if parsed is not None:
                    results.append(parsed)
            page += 1
        return tuple(results)


def _parse_recent_track(raw_track: object) -> LastFmRecentTrack | None:
    """Parse one dated recent-track response, ignoring now-playing entries."""
    if not isinstance(raw_track, dict):
        return None
    raw_date = raw_track.get("date")
    raw_artist = raw_track.get("artist")
    raw_album = raw_track.get("album")
    if not isinstance(raw_date, dict) or not isinstance(raw_artist, dict):
        return None

    raw_timestamp = raw_date.get("uts")
    if not isinstance(raw_timestamp, (int, str)):
        return None
    try:
        timestamp_seconds = int(raw_timestamp)
    except TypeError, ValueError:
        return None
    artist = str(raw_artist.get("#text") or raw_artist.get("name") or "").strip()
    track = str(raw_track.get("name") or "").strip()
    album = (
        str(raw_album.get("#text") or "").strip() if isinstance(raw_album, dict) else ""
    )
    if not artist or not track:
        return None
    return LastFmRecentTrack(
        artist=artist,
        track=track,
        album=album,
        timestamp_seconds=timestamp_seconds,
    )
