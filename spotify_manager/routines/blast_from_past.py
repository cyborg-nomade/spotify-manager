"""Select past Last.fm scrobbles using the music-listening rules."""

import base64
import binascii
import gzip
import json
import re
from collections.abc import Callable
from datetime import UTC
from datetime import date
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import partial
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from spotipy import Spotify

from spotify_manager.application.historical_values import (
    BlastFromPastBatch as BlastFromPastBatch,
)
from spotify_manager.application.historical_values import (
    BlastFromPastCancelledError as BlastFromPastCancelledError,
)
from spotify_manager.application.historical_values import (
    BlastFromPastConfigError as BlastFromPastConfigError,
)
from spotify_manager.application.historical_values import (
    BlastFromPastError as BlastFromPastError,
)
from spotify_manager.application.historical_values import (
    BlastFromPastSpotifySummary as BlastFromPastSpotifySummary,
)
from spotify_manager.application.historical_values import (
    LastFmExportError as LastFmExportError,
)
from spotify_manager.application.historical_values import PlaylistState as PlaylistState
from spotify_manager.application.historical_values import (
    RandomIndexSet as RandomIndexSet,
)
from spotify_manager.application.historical_values import (
    RandomOrgError as RandomOrgError,
)
from spotify_manager.application.historical_values import (
    SpotifySelectionResolution as SpotifySelectionResolution,
)
from spotify_manager.application.historical_values import (
    SpotifySelectionResult as SpotifySelectionResult,
)
from spotify_manager.application.historical_values import (
    SpotifyTrackMatch as SpotifyTrackMatch,
)
from spotify_manager.application.historical_values import (
    SpotifyTrackResolutionError as SpotifyTrackResolutionError,
)
from spotify_manager.domain import history as history_policy
from spotify_manager.domain import history_matching as matching_policy
from spotify_manager.domain import titles as title_policy
from spotify_manager.domain.history import Scrobble as Scrobble
from spotify_manager.domain.history import ScrobbleSelection as ScrobbleSelection
from spotify_manager.domain.titles import BRACKETED_SUFFIX as BRACKETED_SUFFIX
from spotify_manager.domain.titles import DASHED_SUFFIX as DASHED_SUFFIX
from spotify_manager.domain.titles import SLIDING_QUALIFIER as SLIDING_QUALIFIER


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_SCROBBLES_PATH = FILES_DIR / "lastfmstats-man-et-arms.json"
RANDOM_ORG_INTEGER_SETS_URL = "https://www.random.org/integer-sets/"
RANDOM_ORG_USER_AGENT = "spotify-manager/0.1.0 (u.fiori@iib-institut.de)"
RANDOM_ORG_TIMEOUT_SECONDS = 180
SCROBBLE_TIMEZONE = ZoneInfo("Europe/Berlin")
FIRST_ELIGIBLE_DATE = date(2007, 11, 27)
LASTFM_PAGE_SIZE = 50
FRIDAY_TRACK_CUTOFF_YEARS = 5
SPOTIFY_SEARCH_LIMIT = 10
SPOTIFY_LIKED_BATCH_SIZE = 20
SPOTIFY_PLAYLIST_PAGE_SIZE = 50
SPOTIFY_PLAYLIST_ADD_BATCH_SIZE = 100
TRACK_MATCH_THRESHOLD = 0.9
ALBUM_MATCH_THRESHOLD = 0.9


Direction = Literal["top down", "bottom up"]
ProgressCallback = Callable[[str], None]
RetryCall = Callable[[Callable[[], object], str], object]
CancelCheck = Callable[[], bool]


def _direct_retry(operation: Callable[[], object], _description: str) -> object:
    """Call Spotify directly when no outer retry policy is supplied."""
    return operation()


def check_cancel(cancel_check: CancelCheck | None) -> None:
    """Stop promptly between network operations when cancellation is requested."""
    if cancel_check is not None and cancel_check():
        raise BlastFromPastCancelledError("Playlist routine cancelled.")


RandomIndexReader = Callable[[int, int], RandomIndexSet]


def friday_track_cutoff(today: date | None = None) -> date:
    """Return Dec 31 of five years before the current year."""
    current_date = today or datetime.now(SCROBBLE_TIMEZONE).date()
    return date(current_date.year - FRIDAY_TRACK_CUTOFF_YEARS, 12, 31)


def load_scrobble_export(
    path: Path = DEFAULT_SCROBBLES_PATH,
) -> dict[str, object]:
    """Load the Last.fm export, including its deployment fallbacks."""
    compressed_path = Path(f"{path}.gz")
    compressed_parts = tuple(sorted(path.parent.glob(f"{path.name}.gz.part-*")))
    encoded_parts = tuple(sorted(path.parent.glob(f"{path.name}.gz.b64.part-*")))
    failures: list[str] = []
    payload: object | None = None

    try:
        with path.open(encoding="utf-8") as export_file:
            payload = json.load(export_file)
    except OSError as exc:
        failures.append(f"could not read {path}: {exc}")
    except json.JSONDecodeError as exc:
        failures.append(
            f"{path} is not valid JSON: {exc.msg} "
            f"at line {exc.lineno}, column {exc.colno}"
        )

    if payload is None and compressed_path.exists():
        try:
            with gzip.open(compressed_path, mode="rt", encoding="utf-8") as export_file:
                payload = json.load(export_file)
        except OSError as exc:
            failures.append(f"could not read {compressed_path}: {exc}")
        except json.JSONDecodeError as exc:
            failures.append(
                f"{compressed_path} is not valid JSON: {exc.msg} "
                f"at line {exc.lineno}, column {exc.colno}"
            )

    if payload is None and compressed_parts:
        try:
            compressed = b"".join(part.read_bytes() for part in compressed_parts)
            payload = json.loads(gzip.decompress(compressed))
        except (OSError, UnicodeError) as exc:
            failures.append(
                "could not read compressed Last.fm export parts "
                f"{compressed_parts[0].parent}: {exc}"
            )
        except json.JSONDecodeError as exc:
            failures.append(
                "compressed Last.fm export parts are not valid JSON: "
                f"{exc.msg} at line {exc.lineno}, column {exc.colno}"
            )

    if payload is None and encoded_parts:
        try:
            encoded = b"".join(part.read_bytes() for part in encoded_parts)
            compressed = base64.b64decode(encoded)
            payload = json.loads(gzip.decompress(compressed))
        except (OSError, UnicodeError, binascii.Error) as exc:
            failures.append(
                "could not read encoded Last.fm export parts "
                f"{encoded_parts[0].parent}: {exc}"
            )
        except json.JSONDecodeError as exc:
            failures.append(
                "encoded Last.fm export parts are not valid JSON: "
                f"{exc.msg} at line {exc.lineno}, column {exc.colno}"
            )

    if payload is None:
        raise LastFmExportError("Last.fm export failed: " + "; ".join(failures))

    if not isinstance(payload, dict) or not isinstance(payload.get("scrobbles"), list):
        raise LastFmExportError(
            f"Last.fm export must contain a 'scrobbles' list: {path}"
        )
    return payload


def load_scrobbles_by_date(
    path: Path = DEFAULT_SCROBBLES_PATH,
) -> dict[date, list[Scrobble]]:
    """Load every export scrobble into Berlin-local Last.fm date buckets."""
    payload = load_scrobble_export(path)
    raw_scrobbles = payload["scrobbles"]
    assert isinstance(raw_scrobbles, list)

    by_date: dict[date, list[Scrobble]] = {}
    for index, raw_scrobble in enumerate(raw_scrobbles):
        if not isinstance(raw_scrobble, dict):
            raise LastFmExportError(f"Scrobble {index} is not an object.")
        try:
            timestamp_ms = int(raw_scrobble["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LastFmExportError(
                f"Scrobble {index} has no valid millisecond timestamp."
            ) from exc

        try:
            played_at = datetime.fromtimestamp(
                timestamp_ms / 1000,
                SCROBBLE_TIMEZONE,
            )
        except (OSError, OverflowError, ValueError) as exc:
            raise LastFmExportError(
                f"Scrobble {index} has an out-of-range timestamp."
            ) from exc

        scrobble = Scrobble(
            track=str(raw_scrobble.get("track") or "Unknown track"),
            artist=str(raw_scrobble.get("artist") or "Unknown artist"),
            album=str(raw_scrobble.get("album") or ""),
            timestamp_ms=timestamp_ms,
        )
        by_date.setdefault(played_at.date(), []).append(scrobble)

    for scrobbles in by_date.values():
        scrobbles.sort(key=lambda item: item.timestamp_ms, reverse=True)
    return by_date


def eligible_dates(
    scrobbles_by_date: dict[date, list[Scrobble]], cutoff: date
) -> list[date]:
    """Return populated historical dates inside the configured Friday range.

    Args:
        scrobbles_by_date: Loaded scrobbles grouped by date.
        cutoff: Inclusive upper bound.

    Returns:
        Eligible dates in chronological order.
    """
    return history_policy.eligible_dates(scrobbles_by_date, FIRST_ELIGIBLE_DATE, cutoff)


def parse_playlist_id(
    reference: str | None,
    setting_name: str = "BLAST_FROM_THE_PAST_PLAYLIST",
) -> str:
    """Extract a Spotify playlist id from a URL, URI, or bare id."""
    if not reference or not reference.strip():
        raise BlastFromPastConfigError(f"{setting_name} is not configured.")

    value = reference.strip()
    patterns = (
        r"^spotify:playlist:(?P<id>[A-Za-z0-9]+)$",
        r"open\.spotify\.com/playlist/(?P<id>[A-Za-z0-9]+)",
        r"^(?P<id>[A-Za-z0-9]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group("id")
    raise BlastFromPastConfigError(f"Invalid {setting_name} reference: {reference}")


def normalize_name(value: str) -> str:
    """Normalize a name through the existing Last.fm identity policy.

    Args:
        value: Artist, album, or track title.

    Returns:
        Lowercase ASCII letters and digits without punctuation or spaces.
    """
    return history_policy.normalize_name(value)


def without_sliding_qualifiers(value: str) -> str:
    """Remove recognized trailing edition/version descriptions from a name.

    Args:
        value: Original display title.

    Returns:
        Title without recognized trailing qualifiers.
    """
    return title_policy.without_sliding_qualifiers(value)


def name_similarity(expected: str, candidate: str) -> float:
    """Return a 0-1 similarity after allowing known Spotify qualifiers.

    Args:
        expected: Original export title.
        candidate: Observed catalog title.

    Returns:
        Sequence similarity after normalizing known qualifiers.
    """
    return matching_policy.name_similarity(expected, candidate)


def spotify_search_query(scrobble: Scrobble) -> str:
    """Build a field-filtered Spotify track search query."""
    track = scrobble.track.replace('"', " ").strip()
    artist = scrobble.artist.replace('"', " ").strip()
    return f'track:"{track}" artist:"{artist}"'


def _spotify_artist_names(raw_track: dict[str, object]) -> tuple[str, ...]:
    """Extract ordered artist names from a Spotify track response."""
    raw_artists = raw_track.get("artists")
    if not isinstance(raw_artists, list):
        return ()
    return tuple(
        str(raw_artist.get("name"))
        for raw_artist in raw_artists
        if isinstance(raw_artist, dict) and raw_artist.get("name")
    )


def matching_spotify_track(
    scrobble: Scrobble,
    raw_track: object,
    search_rank: int,
) -> SpotifyTrackMatch | None:
    """Return a candidate when the mandatory artist and track thresholds pass."""
    if not isinstance(raw_track, dict):
        return None
    spotify_id = str(raw_track.get("id") or "").strip()
    uri = str(raw_track.get("uri") or "").strip()
    track_name = str(raw_track.get("name") or "").strip()
    artists = _spotify_artist_names(raw_track)
    if not spotify_id or not uri or not track_name or not artists:
        return None

    expected_artist = normalize_name(scrobble.artist)
    if not expected_artist or not any(
        normalize_name(artist) == expected_artist for artist in artists
    ):
        return None

    track_similarity = name_similarity(scrobble.track, track_name)
    if track_similarity < TRACK_MATCH_THRESHOLD:
        return None

    raw_album = raw_track.get("album")
    album_name = (
        str(raw_album.get("name") or "").strip() if isinstance(raw_album, dict) else ""
    )
    album_similarity: float | None = None
    if scrobble.album:
        album_similarity = name_similarity(scrobble.album, album_name)

    popularity = raw_track.get("popularity")
    return SpotifyTrackMatch(
        spotify_id=spotify_id,
        uri=uri,
        track=track_name,
        artists=artists,
        album=album_name,
        search_rank=search_rank,
        track_similarity=track_similarity,
        album_similarity=album_similarity,
        popularity=popularity if isinstance(popularity, int) else None,
    )


def search_spotify_matches(
    sp: Spotify,
    scrobble: Scrobble,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> tuple[SpotifyTrackMatch, ...]:
    """Search Spotify once and return every qualifying result in rank order."""
    check_cancel(cancel_check)
    response = retry_call(
        lambda: sp.search(
            q=spotify_search_query(scrobble),
            type="track",
            limit=SPOTIFY_SEARCH_LIMIT,
            offset=0,
        ),
        f"searching Spotify for {scrobble.artist} - {scrobble.track}",
    )
    check_cancel(cancel_check)
    if not isinstance(response, dict):
        raise SpotifyTrackResolutionError(
            f"Spotify returned invalid search data for {scrobble.artist} - "
            f"{scrobble.track}."
        )
    page = response.get("tracks")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise SpotifyTrackResolutionError(
            f"Spotify returned invalid search data for {scrobble.artist} - "
            f"{scrobble.track}."
        )

    matches: list[SpotifyTrackMatch] = []
    seen_ids: set[str] = set()
    for rank, raw_track in enumerate(page["items"], start=1):
        match = matching_spotify_track(scrobble, raw_track, rank)
        if match is None or match.spotify_id in seen_ids:
            continue
        seen_ids.add(match.spotify_id)
        matches.append(match)
    return tuple(matches)


def liked_spotify_track_ids(
    sp: Spotify,
    match_groups: list[tuple[SpotifyTrackMatch, ...]],
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> set[str]:
    """Return live liked status for all unique qualifying candidates in batches."""
    track_ids = list(
        dict.fromkeys(match.spotify_id for matches in match_groups for match in matches)
    )
    liked_ids: set[str] = set()
    for start in range(0, len(track_ids), SPOTIFY_LIKED_BATCH_SIZE):
        check_cancel(cancel_check)
        batch = track_ids[start : start + SPOTIFY_LIKED_BATCH_SIZE]
        statuses = retry_call(
            partial(sp.current_user_saved_tracks_contains, batch),
            "checking live liked-track status",
        )
        check_cancel(cancel_check)
        if not isinstance(statuses, list):
            raise SpotifyTrackResolutionError(
                "Spotify returned invalid liked-track statuses."
            )
        if len(statuses) != len(batch):
            raise SpotifyTrackResolutionError(
                "Spotify returned incomplete liked-track statuses."
            )
        liked_ids.update(
            spotify_id
            for spotify_id, is_liked in zip(batch, statuses, strict=True)
            if is_liked
        )
    return liked_ids


def preferred_spotify_match(
    matches: tuple[SpotifyTrackMatch, ...],
    liked_ids: set[str],
) -> SpotifyTrackMatch | None:
    """Choose a result, allowing liked status to override an album mismatch.

    Args:
        matches: Search-ranked artist/track-qualified observations.
        liked_ids: Current liked identities.

    Returns:
        Preferred eligible observation, or none when no match qualifies.
    """
    return matching_policy.preferred_match(matches, liked_ids, ALBUM_MATCH_THRESHOLD)


def qualifying_spotify_matches(
    matches: tuple[SpotifyTrackMatch, ...],
    liked_ids: set[str],
) -> tuple[SpotifyTrackMatch, ...]:
    """Apply liked status and the overridable album threshold.

    Args:
        matches: Search-ranked observations.
        liked_ids: Current liked identities, replacing prior liked flags.

    Returns:
        Qualified observations in their original order.
    """
    return matching_policy.qualifying_matches(matches, liked_ids, ALBUM_MATCH_THRESHOLD)


def _random_org_error_message(exc: HTTPError) -> str:
    """Extract Random.org's plain-text error when one is available."""
    try:
        detail = exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        detail = ""
    return detail or str(exc.reason)


def fetch_random_indexes(population_size: int, count: int) -> RandomIndexSet:
    """Fetch unique zero-based indexes and one UTC timestamp from Random.org."""
    if population_size < 1:
        raise ValueError("population_size must be at least 1")
    if count < 1 or count > population_size:
        raise ValueError("count must be between 1 and population_size")

    query = urlencode(
        {
            "sets": 1,
            "num": count,
            "min": 0,
            "max": population_size - 1,
            "seqnos": "off",
            "commas": "off",
            "sort": "off",
            "order": "index",
            "format": "plain",
            "rnd": "new",
        }
    )
    request = Request(
        f"{RANDOM_ORG_INTEGER_SETS_URL}?{query}",
        headers={"User-Agent": RANDOM_ORG_USER_AGENT},
    )

    try:
        with urlopen(request, timeout=RANDOM_ORG_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            timestamp_header = response.headers.get("Date")
    except HTTPError as exc:
        detail = _random_org_error_message(exc)
        raise RandomOrgError(f"Random.org returned HTTP {exc.code}: {detail}") from exc
    except (TimeoutError, URLError) as exc:
        raise RandomOrgError(f"Could not reach Random.org: {exc}") from exc

    if "Error:" in body:
        error_line = next(
            (line.strip() for line in body.splitlines() if "Error:" in line),
            body,
        )
        raise RandomOrgError(f"Random.org could not generate indexes: {error_line}")

    indexes = tuple(int(value) for value in re.findall(r"-?\d+", body))
    if len(indexes) != count:
        raise RandomOrgError(
            f"Random.org returned {len(indexes)} indexes; expected {count}."
        )
    if len(set(indexes)) != count:
        raise RandomOrgError("Random.org returned duplicate date indexes.")
    if any(index < 0 or index >= population_size for index in indexes):
        raise RandomOrgError("Random.org returned an out-of-range date index.")
    if not timestamp_header:
        raise RandomOrgError("Random.org response did not include a timestamp.")

    try:
        generated_at = parsedate_to_datetime(timestamp_header)
    except (TypeError, ValueError) as exc:
        raise RandomOrgError(
            f"Random.org returned an invalid timestamp: {timestamp_header}"
        ) from exc
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)

    return RandomIndexSet(
        indexes=indexes,
        generated_at=generated_at.astimezone(UTC),
    )


def fetch_random_timestamp() -> datetime:
    """Return the UTC timestamp from a minimal Random.org generation request."""
    return fetch_random_indexes(population_size=2, count=1).generated_at


def page_for_timestamp(generated_at: datetime, total_pages: int) -> int:
    """Return the historical track page selected by a Random.org timestamp.

    Args:
        generated_at: Timestamp supplied by the random source.
        total_pages: Number of populated pages.

    Returns:
        Wrapped one-based page number.

    Raises:
        ValueError: There are no pages.
    """
    return history_policy.page_for_timestamp(generated_at, total_pages)


def select_scrobble(
    selected_date: date,
    date_index: int,
    scrobbles: list[Scrobble],
    generated_at: datetime,
) -> ScrobbleSelection:
    """Apply the pure historical track selection to loaded scrobbles.

    Args:
        selected_date: Date selected by the random source.
        date_index: Original eligible-date index.
        scrobbles: Ordered scrobbles on that date.
        generated_at: Random source timestamp.

    Returns:
        Selection and its explanatory page, direction, and position.

    Raises:
        ValueError: The selected date has no scrobbles.
    """
    return history_policy.select_scrobble(
        selected_date,
        date_index,
        scrobbles,
        generated_at,
        LASTFM_PAGE_SIZE,
    )


def select_blast_from_past(
    count: int = 10,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
) -> BlastFromPastBatch:
    """Select a Friday-routine batch from the Last.fm export.

    Args:
        count: Number of populated historical dates to select.
        path: Existing history export.
        today: Optional effective local date for the cutoff.
        random_index_reader: Existing source of unique indexes and one timestamp.
        progress_callback: Optional progress presenter.

    Returns:
        Selected plays in response-index order with the original cutoff.

    Raises:
        BlastFromPastError: Count or eligible-date population is invalid.
        LastFmExportError: History cannot be read.
        RandomOrgError: The random source fails.
    """
    from spotify_manager.bootstrap.historical_playlists import select_blast

    return select_blast(count, path, today, random_index_reader, progress_callback)


def load_playlist_state(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> PlaylistState:
    """Load the complete target playlist once."""
    offset = 0
    track_ids: set[str] = set()
    track_keys: set[tuple[str, str]] = set()
    primary_artist_keys: set[str] = set()
    seen_next_pages: set[str] = set()
    while True:
        check_cancel(cancel_check)
        response = retry_call(
            partial(
                sp._get,
                f"playlists/{playlist_id}/items",
                limit=SPOTIFY_PLAYLIST_PAGE_SIZE,
                offset=offset,
            ),
            f"loading Spotify playlist items at offset {offset}",
        )
        check_cancel(cancel_check)
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise SpotifyTrackResolutionError(
                f"Spotify returned invalid playlist data for {playlist_id}."
            )
        raw_items = response["items"]
        for raw_entry in raw_items:
            if not isinstance(raw_entry, dict):
                continue
            raw_track = raw_entry.get("item") or raw_entry.get("track")
            if not isinstance(raw_track, dict):
                continue
            spotify_id = str(raw_track.get("id") or "").strip()
            if spotify_id:
                track_ids.add(spotify_id)
            track_name = str(raw_track.get("name") or "").strip()
            if track_name:
                artist_names = _spotify_artist_names(raw_track)
                normalized_track = normalize_name(
                    without_sliding_qualifiers(track_name)
                )
                track_keys.update(
                    (normalize_name(artist), normalized_track)
                    for artist in artist_names
                    if normalize_name(artist) and normalized_track
                )
                if artist_names and normalize_name(artist_names[0]):
                    primary_artist_keys.add(normalize_name(artist_names[0]))

        offset += len(raw_items)
        total = response.get("total")
        next_page = response.get("next")
        has_more = bool(next_page)
        if "next" not in response and isinstance(total, int):
            has_more = offset < total
        if not has_more:
            total_items = (
                offset
                if "next" in response
                else total
                if isinstance(total, int)
                else offset
            )
            return PlaylistState(
                total_items=total_items,
                track_ids=frozenset(track_ids),
                track_keys=frozenset(track_keys),
                primary_artist_keys=frozenset(primary_artist_keys),
            )
        if not raw_items:
            raise SpotifyTrackResolutionError(
                f"Spotify returned an empty playlist page for {playlist_id}."
            )
        if isinstance(next_page, str):
            if next_page in seen_next_pages:
                raise SpotifyTrackResolutionError(
                    f"Spotify repeated a playlist page for {playlist_id}."
                )
            seen_next_pages.add(next_page)


def add_spotify_matches(
    sp: Spotify,
    playlist_id: str,
    matches: list[SpotifyTrackMatch],
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> None:
    """Append Spotify matches to the playlist in API-sized batches."""
    uris = [match.uri for match in matches]
    for start in range(0, len(uris), SPOTIFY_PLAYLIST_ADD_BATCH_SIZE):
        check_cancel(cancel_check)
        batch = uris[start : start + SPOTIFY_PLAYLIST_ADD_BATCH_SIZE]
        retry_call(
            partial(
                sp._post,
                f"playlists/{playlist_id}/items",
                payload={"uris": batch},
            ),
            f"adding {len(batch)} tracks to the Spotify playlist",
        )
        check_cancel(cancel_check)


def resolve_spotify_selections(
    sp: Spotify,
    selections: tuple[ScrobbleSelection, ...],
    playlist: PlaylistState,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> SpotifySelectionResolution:
    """Resolve selected scrobbles and identify new playlist tracks.

    Args:
        sp: Caller-owned Spotify client.
        selections: Original ordered selected plays.
        playlist: Observed destination membership.
        progress_callback: Optional progress presenter.
        retry_call: Original retry policy.
        cancel_check: Optional cancellation predicate.

    Returns:
        Ordered decisions and unique pending additions.

    Raises:
        SpotifyTrackResolutionError: Spotify observations are unusable.
        BlastFromPastCancelledError: Cancellation is requested.
    """
    from spotify_manager.bootstrap.historical_playlists import resolve_matches

    return resolve_matches(
        sp, selections, playlist, progress_callback, retry_call, cancel_check
    )


def add_blast_from_past_to_spotify(
    sp: Spotify,
    playlist_id: str,
    count: int | None = 10,
    max_playlist_length: int | None = None,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
    dry_run: bool = False,
) -> BlastFromPastSpotifySummary:
    """Select, resolve, and append a blast-from-the-past batch to Spotify.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        count: Optional explicit historical date count.
        max_playlist_length: Optional destination capacity, exclusive with count.
        path: Existing history export.
        today: Optional effective local date for the cutoff.
        random_index_reader: Existing random-index source.
        progress_callback: Optional progress presenter.
        retry_call: Original retry policy.
        cancel_check: Optional cancellation predicate.
        dry_run: Suppress writes while retaining resolved added actions.

    Returns:
        Original summary with observed and projected destination sizes.

    Raises:
        BlastFromPastError: Configuration, selection or observations fail.
        BlastFromPastCancelledError: Cancellation is requested.
    """
    from spotify_manager.bootstrap.historical_playlists import add_blast

    return add_blast(
        sp,
        playlist_id,
        count,
        max_playlist_length,
        path,
        today,
        random_index_reader,
        progress_callback,
        retry_call,
        cancel_check,
        dry_run,
    )
