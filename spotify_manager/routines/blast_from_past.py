"""Select past Last.fm scrobbles using the music-listening rules."""

import re
from collections.abc import Callable
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

from spotify_manager.application.historical_resolution import (
    direct_call as _direct_retry,
)
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
from spotify_manager.infrastructure import history_export
from spotify_manager.infrastructure import history_matching_records
from spotify_manager.infrastructure import history_playlist
from spotify_manager.infrastructure import random_indexes


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


def check_cancel(cancel_check: CancelCheck | None) -> None:
    """Stop promptly between network operations when cancellation is requested.

    Args:
        cancel_check: Original cancel check observation.
    """
    if cancel_check is not None and cancel_check():
        raise BlastFromPastCancelledError("Playlist routine cancelled.")


RandomIndexReader = Callable[[int, int], RandomIndexSet]


def friday_track_cutoff(today: date | None = None) -> date:
    """Return Dec 31 of five years before the current year.

    Args:
        today: Original today observation.

    Returns:
        Original friday track cutoff result.
    """
    current_date = today or datetime.now(SCROBBLE_TIMEZONE).date()
    return date(current_date.year - FRIDAY_TRACK_CUTOFF_YEARS, 12, 31)


def load_scrobble_export(
    path: Path = DEFAULT_SCROBBLES_PATH,
) -> dict[str, object]:
    """Load the Last.fm export, including its deployment fallbacks.

    Args:
        path: Original caller-supplied managed file location.

    Returns:
        Original load scrobble export result.
    """
    return history_export.load_export(path)


def load_scrobbles_by_date(
    path: Path = DEFAULT_SCROBBLES_PATH,
) -> dict[date, list[Scrobble]]:
    """Load every export scrobble into Berlin-local Last.fm date buckets.

    Args:
        path: Original caller-supplied managed file location.

    Returns:
        Original load scrobbles by date result.
    """
    return history_export.by_date(load_scrobble_export, path, SCROBBLE_TIMEZONE)


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
    """Extract a Spotify playlist id from a URL, URI, or bare id.

    Args:
        reference: Original name, bare identity, URI or Spotify share link.
        setting_name: Original setting name observation.

    Returns:
        Original parse playlist id result.
    """
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
    """Build a field-filtered Spotify track search query.

    Args:
        scrobble: Original scrobble observation.

    Returns:
        Original spotify search query result.
    """
    track = scrobble.track.replace('"', " ").strip()
    artist = scrobble.artist.replace('"', " ").strip()
    return f'track:"{track}" artist:"{artist}"'


def _spotify_artist_names(raw_track: dict[str, object]) -> tuple[str, ...]:
    """Extract ordered artist names from a Spotify track response."""
    return history_matching_records.artist_names(raw_track)


def matching_spotify_track(
    scrobble: Scrobble,
    raw_track: object,
    search_rank: int,
) -> SpotifyTrackMatch | None:
    """Return a candidate when the mandatory artist and track thresholds pass.

    Args:
        scrobble: Original scrobble observation.
        raw_track: Original raw track observation.
        search_rank: Original search rank observation.

    Returns:
        Original matching spotify track result.
    """
    return history_matching_records.matching_track(
        scrobble, raw_track, search_rank, TRACK_MATCH_THRESHOLD
    )


def search_spotify_matches(
    sp: Spotify,
    scrobble: Scrobble,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> tuple[SpotifyTrackMatch, ...]:
    """Search Spotify once and return every qualifying result in rank order.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        scrobble: Original scrobble observation.
        retry_call: Original retry call observation.
        cancel_check: Original cancel check observation.

    Returns:
        Original search spotify matches result.
    """
    check_cancel(cancel_check)
    response = retry_call(
        partial(_search_historical_track, sp, scrobble),
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
    """Return live liked status for all unique qualifying candidates in batches.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        match_groups: Original match groups observation.
        retry_call: Original retry call observation.
        cancel_check: Original cancel check observation.

    Returns:
        Original liked spotify track ids result.
    """
    track_ids = matching_policy.candidate_ids(match_groups)
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
        liked_ids.update(matching_policy.liked_identities(batch, statuses))
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
    """Fetch unique zero-based indexes and one UTC timestamp from Random.org.

    Args:
        population_size: Original population size observation.
        count: Original count observation.

    Returns:
        Original fetch random indexes result.
    """
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

    return random_indexes.result(
        body, timestamp_header, population_size, count, parsedate_to_datetime
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
    """Load the complete target playlist once.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        playlist_id: Original playlist id observation.
        retry_call: Original retry call observation.
        cancel_check: Original cancel check observation.

    Returns:
        Original load playlist state result.
    """
    return history_playlist.state(
        partial(_playlist_page, sp, playlist_id, retry_call, cancel_check),
        _spotify_artist_names,
        playlist_id,
    )


def add_spotify_matches(
    sp: Spotify,
    playlist_id: str,
    matches: list[SpotifyTrackMatch],
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> None:
    """Append Spotify matches to the playlist in API-sized batches.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        playlist_id: Original playlist id observation.
        matches: Original matches observation.
        retry_call: Original retry call observation.
        cancel_check: Original cancel check observation.
    """
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


def _playlist_page(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
    cancel_check: CancelCheck | None,
    offset: int,
) -> object:
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
    return response


def _search_historical_track(sp: Spotify, scrobble: Scrobble) -> object:
    return sp.search(
        q=spotify_search_query(scrobble),
        type="track",
        limit=SPOTIFY_SEARCH_LIMIT,
        offset=0,
    )
