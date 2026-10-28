"""Small read-only client for the documented Last.fm API."""

import json
import time
from dataclasses import dataclass
from typing import Any
from typing import Never
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from spotify_manager.application.ports.runtime import BlockingWait as Wait
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.queue_candidates import (
    LastFmSimilarArtist as LastFmSimilarArtist,
)
from spotify_manager.domain.recommendation_candidates import (
    LastFmSimilarTrack as LastFmSimilarTrack,
)
from spotify_manager.infrastructure.cli_cancellation import BlockingInvocationWait
from spotify_manager.infrastructure.cli_cancellation import check_cli_interruption


type Sleeper = Wait


type EventCallback = Messages


LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
LASTFM_USER_AGENT = "spotify-manager/0.1.0 (u.fiori@iib-institut.de)"
LASTFM_TIMEOUT_SECONDS = 30
TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
TRANSIENT_LASTFM_ERRORS = frozenset({11, 16, 29})


class LastFmError(RuntimeError):
    """Base error for documented Last.fm API requests."""


class LastFmResponseError(LastFmError):
    """Raised when Last.fm returns an error or an invalid response."""


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
        sleeper: Sleeper = time,
    ) -> None:
        """Store non-session credentials and retry configuration.

        Args:
            api_key: Nonempty Last.fm API credential.
            username: Nonempty account whose listening history is read.
            max_retries: Number of retries after the initial request.
            backoff_seconds: Base delay for exponential retry waits.
            event_callback: Optional owner for retry messages.
            sleeper: Owner of synchronous retry waits.

        Raises:
            ValueError: Credentials are empty or retry settings are negative.
        """
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
            self.event_callback.echo(message)

    def _retry_delay(self, attempt: int) -> float:
        """Return the exponential delay before the next attempt."""
        return self.backoff_seconds * (2**attempt)

    def _sleep(self, delay: float) -> None:
        if self.sleeper is time:
            BlockingInvocationWait().sleep(delay)
            return
        self.sleeper.sleep(delay)

    def _request(self, method: str, **params: object) -> dict[str, Any]:
        check_cli_interruption()
        request = _lastfm_request(method, self.api_key, params)
        for attempt in range(self.max_retries + 1):
            check_cli_interruption()
            try:
                return self._request_attempt(request, method, attempt)
            except _RetryLastFmRequestError:
                continue
        raise AssertionError("Last.fm retry loop ended unexpectedly")

    def _request_attempt(
        self, request: Request, method: str, attempt: int
    ) -> dict[str, Any]:
        try:
            payload = _read_lastfm_json(request)
        except HTTPError as error:
            self._http_failure(method, attempt, error)
        except (TimeoutError, URLError) as error:
            self._transport_failure(method, attempt, error)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise LastFmResponseError(
                f"Last.fm request {method} returned invalid JSON."
            ) from error
        return self._validate_payload(payload, method, attempt)

    def _http_failure(self, method: str, attempt: int, error: HTTPError) -> Never:
        if error.code not in TRANSIENT_HTTP_STATUSES or attempt >= self.max_retries:
            raise LastFmResponseError(
                f"Last.fm request {method} failed with HTTP {error.code}."
            ) from error
        delay = self._retry_delay(attempt)
        self._emit(
            f"Last.fm returned HTTP {error.code}; retrying in {delay:g} seconds."
        )
        self._sleep(delay)
        raise _RetryLastFmRequestError

    def _transport_failure(
        self, method: str, attempt: int, error: TimeoutError | URLError
    ) -> Never:
        if attempt >= self.max_retries:
            raise LastFmResponseError(
                f"Last.fm request {method} could not connect."
            ) from error
        delay = self._retry_delay(attempt)
        self._emit(
            f"Last.fm request {method} could not connect; "
            f"retrying in {delay:g} seconds."
        )
        self._sleep(delay)
        raise _RetryLastFmRequestError

    def _validate_payload(
        self, payload: object, method: str, attempt: int
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LastFmResponseError(
                f"Last.fm request {method} returned an invalid object."
            )
        error_code = payload.get("error")
        if error_code is None:
            return payload
        numeric_error = _lastfm_error_code(error_code)
        message = str(payload.get("message") or "unknown Last.fm error")
        if numeric_error not in TRANSIENT_LASTFM_ERRORS or attempt >= self.max_retries:
            raise LastFmResponseError(
                f"Last.fm request {method} failed ({numeric_error}): {message}"
            )
        delay = self._retry_delay(attempt)
        self._emit(f"Last.fm error {numeric_error}; retrying in {delay:g} seconds.")
        self._sleep(delay)
        raise _RetryLastFmRequestError

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

    def similar_artists(
        self,
        artist: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Return ranked artists similar to one seed artist."""
        payload = self._request(
            "artist.getSimilar",
            artist=artist,
            autocorrect=1,
            limit=limit,
        )
        container = payload.get("similarartists")
        raw_artists = container.get("artist") if isinstance(container, dict) else None
        if not isinstance(raw_artists, list):
            raise LastFmResponseError(
                "Last.fm artist.getSimilar returned invalid artist data."
            )

        results: list[LastFmSimilarArtist] = []
        for raw_artist in raw_artists:
            if not isinstance(raw_artist, dict):
                continue
            artist_name = str(raw_artist.get("name") or "").strip()
            try:
                match = float(raw_artist.get("match") or 0)
            except TypeError, ValueError:
                continue
            if artist_name and match > 0:
                results.append(
                    LastFmSimilarArtist(
                        artist=artist_name,
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
        expected_total: int | None = None
        results: list[LastFmRecentTrack] = []
        while page <= total_pages:
            self._emit(f"Fetching Last.fm history page {page} of {total_pages}")
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
                reported_pages = max(1, int(attributes.get("totalPages") or 1))
                reported_total = (
                    int(attributes["total"]) if "total" in attributes else None
                )
                if page > 1 and (
                    reported_pages != total_pages or reported_total != expected_total
                ):
                    raise LastFmResponseError(
                        "Last.fm history changed during pagination; retry the rebuild."
                    )
                total_pages = reported_pages
                expected_total = reported_total
            except (TypeError, ValueError) as exc:
                raise LastFmResponseError(
                    "Last.fm user.getRecentTracks returned invalid pagination."
                ) from exc

            for raw_track in raw_tracks:
                parsed = _parse_recent_track(raw_track)
                if parsed is not None:
                    results.append(parsed)
            page += 1
        if expected_total is not None and len(results) != expected_total:
            raise LastFmResponseError(
                "Last.fm returned incomplete history; existing history was preserved."
            )
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


class _RetryLastFmRequestError(RuntimeError):
    """Continue the original read loop after an accepted transient wait."""


def _lastfm_request(method: str, api_key: str, params: dict[str, object]) -> Request:
    query = urlencode(
        {"method": method, "api_key": api_key, "format": "json", **params}
    )
    return Request(
        f"{LASTFM_API_URL}?{query}", headers={"User-Agent": LASTFM_USER_AGENT}
    )


def _read_lastfm_json(request: Request) -> object:
    with urlopen(request, timeout=LASTFM_TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


def _lastfm_error_code(error_code: Any) -> int:
    try:
        return int(error_code)
    except TypeError, ValueError:
        return -1
