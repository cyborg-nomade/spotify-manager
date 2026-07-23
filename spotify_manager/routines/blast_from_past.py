"""Select past Last.fm scrobbles using the music-listening rules."""

import base64
import binascii
import gzip
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from spotipy import Spotify
from unidecode import unidecode


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

SLIDING_QUALIFIER = re.compile(
    r"(?:remaster(?:ed)?|live|deluxe|edition|version|mix|mono|stereo|"
    r"anniversary|bonus|reissue|radio|acoustic|explicit|clean|feat(?:uring)?\.?)",
    re.IGNORECASE,
)
BRACKETED_SUFFIX = re.compile(r"\s*[\[(]([^)\]]+)[)\]]\s*$")
DASHED_SUFFIX = re.compile(r"\s+[-\N{EN DASH}\N{EM DASH}]\s+(.+?)\s*$")

Direction = Literal["top down", "bottom up"]
ProgressCallback = Callable[[str], None]


class BlastFromPastError(Exception):
    """Base error for the blast-from-the-past routine."""


class LastFmExportError(BlastFromPastError):
    """Raised when the Last.fm export cannot be read."""


class RandomOrgError(BlastFromPastError):
    """Raised when Random.org cannot provide a valid selection."""


class BlastFromPastConfigError(BlastFromPastError):
    """Raised when the Spotify playlist configuration is invalid."""


class SpotifyTrackResolutionError(BlastFromPastError):
    """Raised when Spotify returns unusable track or playlist data."""


@dataclass(frozen=True)
class Scrobble:
    """One normalized Last.fm scrobble."""

    track: str
    artist: str
    album: str
    timestamp_ms: int


@dataclass(frozen=True)
class RandomIndexSet:
    """Unique indexes and the Random.org generation timestamp."""

    indexes: tuple[int, ...]
    generated_at: datetime


@dataclass(frozen=True)
class ScrobbleSelection:
    """One date-to-scrobble selection with its rule trace."""

    selected_date: date
    date_index: int
    scrobbles_on_date: int
    page: int
    total_pages: int
    direction: Direction
    position: int
    scrobble: Scrobble


@dataclass(frozen=True)
class BlastFromPastBatch:
    """A completed batch selected from one Random.org response."""

    generated_at: datetime
    cutoff_date: date
    available_dates: int
    selections: tuple[ScrobbleSelection, ...]


@dataclass(frozen=True)
class SpotifyTrackMatch:
    """One Spotify result that passed the artist and track thresholds."""

    spotify_id: str
    uri: str
    track: str
    artists: tuple[str, ...]
    album: str
    search_rank: int
    track_similarity: float
    album_similarity: float | None
    popularity: int | None
    liked: bool = False


@dataclass(frozen=True)
class PlaylistState:
    """Current playlist size and track identities."""

    total_items: int
    track_ids: frozenset[str]
    track_keys: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True)
class SpotifySelectionResult:
    """Spotify resolution and playlist outcome for one Last.fm selection."""

    selection: ScrobbleSelection
    match: SpotifyTrackMatch | None
    qualifying_matches: int
    action: Literal["added", "already present", "duplicate selection", "no match"]


@dataclass(frozen=True)
class SpotifySelectionResolution:
    """Resolved Spotify matches and tracks waiting to be added."""

    results: tuple[SpotifySelectionResult, ...]
    pending_matches: tuple[SpotifyTrackMatch, ...]


@dataclass(frozen=True)
class BlastFromPastSpotifySummary:
    """Completed Spotify playlist update for one command invocation."""

    playlist_id: str
    requested_count: int
    playlist_length_before: int
    playlist_length_after: int
    batch: BlastFromPastBatch | None
    results: tuple[SpotifySelectionResult, ...]

    @property
    def added(self) -> int:
        """Return the number of tracks added in this run."""
        return sum(result.action == "added" for result in self.results)


RandomIndexReader = Callable[[int, int], RandomIndexSet]


def friday_track_cutoff(today: date | None = None) -> date:
    """Return Dec 31 of five years before the current year."""
    current_date = today or datetime.now(SCROBBLE_TIMEZONE).date()
    return date(current_date.year - FRIDAY_TRACK_CUTOFF_YEARS, 12, 31)


def load_scrobbles_by_date(
    path: Path = DEFAULT_SCROBBLES_PATH,
) -> dict[date, list[Scrobble]]:
    """Load every export scrobble into Berlin-local Last.fm date buckets."""
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

    raw_scrobbles = payload.get("scrobbles") if isinstance(payload, dict) else None
    if not isinstance(raw_scrobbles, list):
        raise LastFmExportError(
            f"Last.fm export must contain a 'scrobbles' list: {path}"
        )

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
    scrobbles_by_date: dict[date, list[Scrobble]],
    cutoff: date,
) -> list[date]:
    """Return chronological dates with scrobbles inside the Friday range."""
    return sorted(
        scrobble_date
        for scrobble_date, scrobbles in scrobbles_by_date.items()
        if scrobbles and FIRST_ELIGIBLE_DATE <= scrobble_date <= cutoff
    )


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
    """Normalize punctuation, accents, spacing, and case for name matching."""
    return re.sub(r"[^a-z0-9]+", "", unidecode(value).casefold())


def without_sliding_qualifiers(value: str) -> str:
    """Remove recognized trailing edition/version descriptions from a name."""
    result = value.strip()
    while True:
        previous = result
        bracketed = BRACKETED_SUFFIX.search(result)
        if bracketed and SLIDING_QUALIFIER.search(bracketed.group(1)):
            result = result[: bracketed.start()].rstrip()
        dashed = DASHED_SUFFIX.search(result)
        if dashed and SLIDING_QUALIFIER.search(dashed.group(1)):
            result = result[: dashed.start()].rstrip()
        if result == previous:
            return result


def name_similarity(expected: str, candidate: str) -> float:
    """Return a 0-1 similarity after allowing known Spotify qualifiers."""
    expected_name = normalize_name(without_sliding_qualifiers(expected))
    candidate_name = normalize_name(without_sliding_qualifiers(candidate))
    if not expected_name or not candidate_name:
        return 0.0
    return SequenceMatcher(None, expected_name, candidate_name).ratio()


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
) -> tuple[SpotifyTrackMatch, ...]:
    """Search Spotify once and return every qualifying result in rank order."""
    response = sp.search(
        q=spotify_search_query(scrobble),
        type="track",
        limit=SPOTIFY_SEARCH_LIMIT,
        offset=0,
    )
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
) -> set[str]:
    """Return live liked status for all unique qualifying candidates in batches."""
    track_ids = list(
        dict.fromkeys(match.spotify_id for matches in match_groups for match in matches)
    )
    liked_ids: set[str] = set()
    for start in range(0, len(track_ids), SPOTIFY_LIKED_BATCH_SIZE):
        batch = track_ids[start : start + SPOTIFY_LIKED_BATCH_SIZE]
        statuses = sp.current_user_saved_tracks_contains(batch)
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
    """Choose a result, allowing liked status to override an album mismatch."""
    eligible_matches = qualifying_spotify_matches(matches, liked_ids)
    if not eligible_matches:
        return None
    return max(
        eligible_matches,
        key=lambda match: (
            match.liked,
            match.track_similarity,
            match.album_similarity if match.album_similarity is not None else 1.0,
            match.popularity if match.popularity is not None else -1,
            -match.search_rank,
        ),
    )


def qualifying_spotify_matches(
    matches: tuple[SpotifyTrackMatch, ...],
    liked_ids: set[str],
) -> tuple[SpotifyTrackMatch, ...]:
    """Apply liked status and the overridable album threshold."""
    with_liked_status = tuple(
        replace(match, liked=match.spotify_id in liked_ids) for match in matches
    )
    return tuple(
        match
        for match in with_liked_status
        if match.liked
        or match.album_similarity is None
        or match.album_similarity >= ALBUM_MATCH_THRESHOLD
    )


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
    """Map the Random.org timestamp to a wrapped Last.fm page number."""
    if total_pages < 1:
        raise ValueError("total_pages must be at least 1")

    minute = generated_at.minute
    if total_pages >= 7 and minute == 0 and generated_at.hour > 12:
        requested_page = 7
    else:
        first_minute_digit = minute // 10
        requested_page = 6 if first_minute_digit == 0 else first_minute_digit
    return ((requested_page - 1) % total_pages) + 1


def select_scrobble(
    selected_date: date,
    date_index: int,
    scrobbles: list[Scrobble],
    generated_at: datetime,
) -> ScrobbleSelection:
    """Map one selected date and timestamp to its Last.fm scrobble."""
    if not scrobbles:
        raise ValueError("cannot select from a date without scrobbles")

    total_pages = (len(scrobbles) + LASTFM_PAGE_SIZE - 1) // LASTFM_PAGE_SIZE
    page = page_for_timestamp(generated_at, total_pages)
    page_start = (page - 1) * LASTFM_PAGE_SIZE
    page_scrobbles = scrobbles[page_start : page_start + LASTFM_PAGE_SIZE]

    direction: Direction = "top down" if generated_at.minute % 10 <= 4 else "bottom up"
    ordered_page = (
        page_scrobbles if direction == "top down" else list(reversed(page_scrobbles))
    )
    selected_offset = generated_at.second % len(ordered_page)

    return ScrobbleSelection(
        selected_date=selected_date,
        date_index=date_index,
        scrobbles_on_date=len(scrobbles),
        page=page,
        total_pages=total_pages,
        direction=direction,
        position=selected_offset + 1,
        scrobble=ordered_page[selected_offset],
    )


def select_blast_from_past(
    count: int = 10,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
) -> BlastFromPastBatch:
    """Select a Friday-routine batch from the Last.fm export."""
    if count < 1:
        raise BlastFromPastError("Count must be at least 1.")

    if progress_callback is not None:
        progress_callback("Loading Last.fm scrobbles")
    scrobbles_by_date = load_scrobbles_by_date(path)
    cutoff = friday_track_cutoff(today)
    available_dates = eligible_dates(scrobbles_by_date, cutoff)
    if not available_dates:
        raise BlastFromPastError(
            f"No scrobbled dates are available through {cutoff.isoformat()}."
        )
    if count > len(available_dates):
        raise BlastFromPastError(
            f"Count {count} exceeds the {len(available_dates)} available dates."
        )

    if progress_callback is not None:
        progress_callback("Requesting unique date indexes from Random.org")
    random_indexes = random_index_reader(len(available_dates), count)

    if progress_callback is not None:
        progress_callback("Applying Last.fm pagination rules")
    selections = tuple(
        select_scrobble(
            selected_date=available_dates[index],
            date_index=index,
            scrobbles=scrobbles_by_date[available_dates[index]],
            generated_at=random_indexes.generated_at,
        )
        for index in random_indexes.indexes
    )
    return BlastFromPastBatch(
        generated_at=random_indexes.generated_at,
        cutoff_date=cutoff,
        available_dates=len(available_dates),
        selections=selections,
    )


def load_playlist_state(sp: Spotify, playlist_id: str) -> PlaylistState:
    """Load the complete target playlist once."""
    offset = 0
    track_ids: set[str] = set()
    track_keys: set[tuple[str, str]] = set()
    while True:
        response = sp._get(
            f"playlists/{playlist_id}/items",
            limit=SPOTIFY_PLAYLIST_PAGE_SIZE,
            offset=offset,
        )
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
                normalized_track = normalize_name(
                    without_sliding_qualifiers(track_name)
                )
                track_keys.update(
                    (normalize_name(artist), normalized_track)
                    for artist in _spotify_artist_names(raw_track)
                    if normalize_name(artist) and normalized_track
                )

        offset += len(raw_items)
        total = response.get("total")
        has_more = bool(response.get("next"))
        if isinstance(total, int):
            has_more = has_more or offset < total
        if not has_more:
            total_items = total if isinstance(total, int) else offset
            return PlaylistState(
                total_items=total_items,
                track_ids=frozenset(track_ids),
                track_keys=frozenset(track_keys),
            )
        if not raw_items:
            raise SpotifyTrackResolutionError(
                f"Spotify returned an empty playlist page for {playlist_id}."
            )


def add_spotify_matches(
    sp: Spotify,
    playlist_id: str,
    matches: list[SpotifyTrackMatch],
) -> None:
    """Append Spotify matches to the playlist in API-sized batches."""
    uris = [match.uri for match in matches]
    for start in range(0, len(uris), SPOTIFY_PLAYLIST_ADD_BATCH_SIZE):
        batch = uris[start : start + SPOTIFY_PLAYLIST_ADD_BATCH_SIZE]
        sp._post(
            f"playlists/{playlist_id}/items",
            payload={"uris": batch},
        )


def resolve_spotify_selections(
    sp: Spotify,
    selections: tuple[ScrobbleSelection, ...],
    playlist: PlaylistState,
    progress_callback: ProgressCallback | None = None,
) -> SpotifySelectionResolution:
    """Resolve selected scrobbles and identify new playlist tracks."""
    match_groups: list[tuple[SpotifyTrackMatch, ...]] = []
    for index, selection in enumerate(selections, start=1):
        if progress_callback is not None:
            progress_callback(f"Searching Spotify track {index}/{len(selections)}")
        match_groups.append(search_spotify_matches(sp, selection.scrobble))

    if progress_callback is not None:
        progress_callback("Checking liked Spotify matches")
    liked_ids = liked_spotify_track_ids(sp, match_groups)

    pending_matches: list[SpotifyTrackMatch] = []
    pending_ids: set[str] = set()
    results: list[SpotifySelectionResult] = []
    for selection, matches in zip(selections, match_groups, strict=True):
        qualifying_matches = qualifying_spotify_matches(matches, liked_ids)
        match = preferred_spotify_match(matches, liked_ids)
        if match is None:
            action: Literal[
                "added", "already present", "duplicate selection", "no match"
            ] = "no match"
        elif match.spotify_id in playlist.track_ids:
            action = "already present"
        elif match.spotify_id in pending_ids:
            action = "duplicate selection"
        else:
            action = "added"
            pending_ids.add(match.spotify_id)
            pending_matches.append(match)
        results.append(
            SpotifySelectionResult(
                selection=selection,
                match=match,
                qualifying_matches=len(qualifying_matches),
                action=action,
            )
        )

    return SpotifySelectionResolution(
        results=tuple(results),
        pending_matches=tuple(pending_matches),
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
) -> BlastFromPastSpotifySummary:
    """Select, resolve, and append a blast-from-the-past batch to Spotify."""
    if count is not None and max_playlist_length is not None:
        raise BlastFromPastConfigError(
            "Use either count or maximum playlist length, not both."
        )
    if count is not None and count < 1:
        raise BlastFromPastConfigError("Count must be at least 1.")
    if max_playlist_length is not None and max_playlist_length < 1:
        raise BlastFromPastConfigError("Maximum playlist length must be at least 1.")

    if progress_callback is not None:
        progress_callback("Loading the Spotify playlist")
    playlist = load_playlist_state(sp, playlist_id)
    requested_count = count if count is not None else 10
    if max_playlist_length is not None:
        requested_count = max(0, max_playlist_length - playlist.total_items)
    if requested_count == 0:
        return BlastFromPastSpotifySummary(
            playlist_id=playlist_id,
            requested_count=0,
            playlist_length_before=playlist.total_items,
            playlist_length_after=playlist.total_items,
            batch=None,
            results=(),
        )

    batch = select_blast_from_past(
        count=requested_count,
        path=path,
        today=today,
        random_index_reader=random_index_reader,
        progress_callback=progress_callback,
    )

    resolution = resolve_spotify_selections(
        sp,
        batch.selections,
        playlist,
        progress_callback,
    )

    if resolution.pending_matches:
        if progress_callback is not None:
            progress_callback(
                f"Adding {len(resolution.pending_matches)} tracks to Spotify"
            )
        add_spotify_matches(sp, playlist_id, list(resolution.pending_matches))

    return BlastFromPastSpotifySummary(
        playlist_id=playlist_id,
        requested_count=requested_count,
        playlist_length_before=playlist.total_items,
        playlist_length_after=playlist.total_items + len(resolution.pending_matches),
        batch=batch,
        results=resolution.results,
    )
