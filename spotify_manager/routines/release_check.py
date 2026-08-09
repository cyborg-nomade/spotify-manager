"""Discover new Spotify releases from the user's most-scrobbled artists."""

import calendar
import json
import re
from collections import Counter
from collections import defaultdict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from typing import Literal
from typing import Protocol

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "release_check_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "release_check_log.jsonl"
STATE_VERSION = 1
MIN_ARTIST_SCROBBLES = 100
NEW_VINTAGE_ARTIST_LIMIT = 50
ALL_SINGLES_ARTIST_LIMIT = 20
ARTIST_SEARCH_LIMIT = 10
ARTIST_RELEASE_PAGE_LIMIT = 10
RELEASE_TRACK_PAGE_LIMIT = 50
CHOICE_ADD = "add"
CHOICE_PENDING = "pending"
CHOICE_SKIP = "skip"
CHOICE_SKIP_ARTIST = "skip-artist"
CHOICE_QUIT = "quit"
CHOICE_SEARCH_PREFIX = "search:"

EP_MARKER = re.compile(r"(?:^|[\s\-[(])e\.?p\.?(?:$|[\s\-)\]])", re.IGNORECASE)
ALWAYS_EXCLUDED_RELEASE = re.compile(
    r"\b(?:anthology|best of|collection|compilation|greatest hits|rarities|"
    r"cast recording|motion picture|original score|soundtrack|bootleg|demos?|"
    r"karaoke|remix(?:es)?)\b",
    re.IGNORECASE,
)
LIVE_RELEASE = re.compile(
    r"(?:^live(?:!|$|\s+(?:at|from|in|on)\b)|"
    r"[\[(][^)\]]*\blive\b[^)\]]*[)\]]|"
    r"\s[-\N{EN DASH}\N{EM DASH}]\s.*\blive\b.*$|"
    r"\b(?:ao vivo|en vivo|in concert|unplugged)\b)",
    re.IGNORECASE,
)
EDITION_RELEASE = re.compile(
    r"\b(?:anniversary|bonus|collector(?:'s)?|deluxe|edition|expanded|legacy|"
    r"mono|remaster(?:ed)?|reissue|special|stereo|super deluxe)\b",
    re.IGNORECASE,
)
DELUXE_RELEASE = re.compile(r"\b(?:deluxe|super deluxe)\b", re.IGNORECASE)

ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
PlaylistAction = Literal[
    "added",
    "would add",
    "already present",
    "duplicate selection",
    "not applicable",
]


class ReleaseCheckError(RuntimeError):
    """Base error for a release-check run."""


class ReleaseCheckConfigError(ReleaseCheckError):
    """Raised when either destination playlist is not configured."""


class ReleaseCheckStateError(ReleaseCheckError):
    """Raised when restart state or the audit log cannot be maintained."""


class ReleaseCheckSpotifyError(ReleaseCheckError):
    """Raised when Spotify returns incomplete release data."""


class LastFmReader(scrobble_history.LastFmReader, Protocol):
    """Last.fm methods required by the canonical history refresh."""


@dataclass(frozen=True)
class ReleaseCheckPlaylists:
    """Parsed destination playlists for a release-check run."""

    wine_cellar: str
    new_vintage: str

    @classmethod
    def from_references(
        cls,
        wine_cellar: str | None,
        new_vintage: str | None,
    ) -> ReleaseCheckPlaylists:
        """Parse both required playlist references."""
        try:
            return cls(
                wine_cellar=blast_from_past.parse_playlist_id(
                    wine_cellar,
                    setting_name="WINE_CELLAR_PLAYLIST",
                ),
                new_vintage=blast_from_past.parse_playlist_id(
                    new_vintage,
                    setting_name="NEW_VINTAGE_PLAYLIST",
                ),
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            raise ReleaseCheckConfigError(str(exc)) from exc


@dataclass(frozen=True)
class RankedArtist:
    """One Last.fm artist ranked by all-time scrobble count."""

    key: str
    name: str
    scrobbles: int
    rank: int

    @property
    def is_new_vintage(self) -> bool:
        """Return whether New Vintage rules apply to this artist."""
        return self.rank <= NEW_VINTAGE_ARTIST_LIMIT

    @property
    def accepts_all_singles(self) -> bool:
        """Return whether standalone singles are eligible."""
        return self.rank <= ALL_SINGLES_ARTIST_LIMIT


@dataclass(frozen=True)
class SpotifyArtistCandidate:
    """One Spotify artist search result available for mapping."""

    spotify_id: str
    name: str
    uri: str
    popularity: int | None
    followers: int | None
    search_rank: int
    exact_name: bool


@dataclass(frozen=True)
class ReleaseCandidate:
    """One primary-artist release returned by Spotify."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    release_date_precision: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str


@dataclass(frozen=True)
class ReleaseTrack:
    """One Spotify track with its credit and release positions."""

    spotify_id: str
    uri: str
    name: str
    primary_artist_id: str
    primary_artist_name: str
    disc_number: int
    track_number: int


@dataclass(frozen=True)
class PendingSingle:
    """A single retained until an announced future record can confirm it."""

    artist_key: str
    release: ReleaseCandidate
    first_track: ReleaseTrack


@dataclass(frozen=True)
class ReleaseCheckResult:
    """One release decision and any resulting playlist actions."""

    artist: str
    artist_rank: int
    artist_scrobbles: int
    spotify_artist_id: str
    release_id: str
    release: str
    release_type: str
    release_date: str
    first_track_id: str | None
    first_track: str | None
    linked_future_release: str | None
    wine_cellar_action: PlaylistAction
    new_vintage_action: PlaylistAction
    reason: str | None
    dry_run: bool


@dataclass(frozen=True)
class ReleaseCheckSummary:
    """Outcome of one complete or paused release check."""

    run_id: str
    checked_from: date
    checked_through: date
    artists_total: int
    artists_processed: int
    dry_run: bool
    resumed: bool
    paused: bool
    history_refresh: scrobble_history.ScrobbleHistorySummary | None
    results: tuple[ReleaseCheckResult, ...]

    @property
    def wine_cellar_added(self) -> int:
        """Count real Wine Cellar additions."""
        return sum(result.wine_cellar_action == "added" for result in self.results)

    @property
    def new_vintage_added(self) -> int:
        """Count real New Vintage additions."""
        return sum(result.new_vintage_action == "added" for result in self.results)


ArtistChoiceReader = Callable[
    [RankedArtist, tuple[SpotifyArtistCandidate, ...]],
    str,
]
ReleaseChoiceReader = Callable[
    [RankedArtist, ReleaseCandidate, ReleaseTrack, tuple[str, ...], bool],
    str,
]


@dataclass
class PlaylistMembership:
    """Mutable playlist identities used to avoid duplicate additions."""

    track_ids: set[str]
    track_keys: set[tuple[str, str]]


def _direct_retry(operation: Callable[[], object], _description: str) -> object:
    """Call Spotify directly when no outer retry policy is supplied."""
    return operation()


def rank_lastfm_artists(
    history: tuple[blast_from_past.Scrobble, ...],
) -> tuple[RankedArtist, ...]:
    """Rank normalized Last.fm artists and retain those with 100 scrobbles."""
    counts: Counter[str] = Counter()
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for scrobble in history:
        name = scrobble.artist.strip()
        key = blast_from_past.normalize_name(name)
        if not key:
            continue
        counts[key] += 1
        names[key][name] += 1

    ordered = sorted(counts, key=lambda key: (-counts[key], key))
    ranking: list[RankedArtist] = []
    for rank, key in enumerate(ordered, start=1):
        scrobbles = counts[key]
        if scrobbles < MIN_ARTIST_SCROBBLES:
            continue
        display_name = min(
            names[key],
            key=lambda name: (-names[key][name], name.casefold(), name),
        )
        ranking.append(
            RankedArtist(
                key=key,
                name=display_name,
                scrobbles=scrobbles,
                rank=rank,
            )
        )
    return tuple(ranking)


def _positive_int(raw: object) -> int | None:
    """Return a non-negative Spotify integer when present."""
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return None


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Return Spotify artist ids and names in credit order."""
    if not isinstance(raw, list):
        return ()
    artists: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or spotify_id).strip()
        if spotify_id:
            artists.append((spotify_id, name))
    return tuple(artists)


def _spotify_artist(
    raw: object,
    rank: int,
    expected_name: str,
) -> SpotifyArtistCandidate | None:
    """Parse one complete artist search result."""
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not spotify_id or not name or not uri:
        return None
    raw_followers = raw.get("followers")
    followers = (
        _positive_int(raw_followers.get("total"))
        if isinstance(raw_followers, dict)
        else None
    )
    return SpotifyArtistCandidate(
        spotify_id=spotify_id,
        name=name,
        uri=uri,
        popularity=_positive_int(raw.get("popularity")),
        followers=followers,
        search_rank=rank,
        exact_name=(
            blast_from_past.normalize_name(name)
            == blast_from_past.normalize_name(expected_name)
        ),
    )


def search_spotify_artists(
    sp: Spotify,
    artist: RankedArtist,
    retry_call: RetryCall,
    search_text: str | None = None,
) -> tuple[SpotifyArtistCandidate, ...]:
    """Search Spotify and parse the candidates for one Last.fm artist."""
    query = (
        search_text
        if search_text is not None
        else f'artist:"{artist.name.replace(chr(34), " ")}"'
    )
    response = retry_call(
        partial(
            sp.search,
            q=query,
            type="artist",
            limit=ARTIST_SEARCH_LIMIT,
            offset=0,
        ),
        f"searching Spotify artists with {query}",
    )
    if not isinstance(response, dict):
        raise ReleaseCheckSpotifyError(
            f"Spotify returned invalid artist search data for {artist.name}."
        )
    page = response.get("artists")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise ReleaseCheckSpotifyError(
            f"Spotify returned invalid artist search data for {artist.name}."
        )
    return tuple(
        candidate
        for rank, raw in enumerate(page["items"], start=1)
        if (candidate := _spotify_artist(raw, rank, artist.name)) is not None
    )


def resolve_spotify_artist(
    sp: Spotify,
    artist: RankedArtist,
    choice_reader: ArtistChoiceReader | None,
    retry_call: RetryCall,
) -> SpotifyArtistCandidate | str | None:
    """Resolve one artist, allowing repeated user-supplied Spotify searches."""
    search_text: str | None = None
    while True:
        candidates = search_spotify_artists(
            sp,
            artist,
            retry_call,
            search_text,
        )
        exact = tuple(candidate for candidate in candidates if candidate.exact_name)
        if search_text is None and len(exact) == 1:
            return exact[0]
        choices = candidates if search_text is not None else (exact or candidates)
        if choice_reader is None:
            if not choices:
                return None
            raise ReleaseCheckSpotifyError(
                f"Spotify artist mapping is ambiguous for {artist.name}."
            )
        choice = choice_reader(artist, choices)
        if choice in {CHOICE_SKIP, CHOICE_SKIP_ARTIST, CHOICE_QUIT}:
            return choice
        if choice.startswith(CHOICE_SEARCH_PREFIX):
            requested_search = choice.removeprefix(CHOICE_SEARCH_PREFIX).strip()
            if not requested_search:
                raise ReleaseCheckSpotifyError(
                    "The custom Spotify artist search cannot be empty."
                )
            search_text = requested_search
            continue
        selected = next(
            (candidate for candidate in choices if candidate.spotify_id == choice),
            None,
        )
        if selected is None:
            raise ReleaseCheckSpotifyError("The selected Spotify artist is invalid.")
        return selected


def _release_type(raw_type: object, total_tracks: int, name: str) -> str:
    """Distinguish albums, EPs, and singles from Spotify metadata."""
    normalized = str(raw_type or "").casefold()
    if normalized == "album":
        return "Album"
    if normalized == "single" and (total_tracks >= 4 or EP_MARKER.search(name)):
        return "EP"
    if normalized == "single":
        return "Single"
    if normalized == "ep":
        return "EP"
    if normalized == "compilation":
        return "Compilation"
    return normalized.title() or "Unknown"


def _release_candidate(
    raw: object,
    artist_id: str,
) -> ReleaseCandidate | None:
    """Parse one release whose first credited artist is the target."""
    if not isinstance(raw, dict):
        return None
    artists = _artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    release_date = str(raw.get("release_date") or "").strip()
    if not spotify_id or not uri or not name or not release_date:
        return None
    total_tracks = _positive_int(raw.get("total_tracks")) or 0
    return ReleaseCandidate(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=_release_type(raw.get("album_type"), total_tracks, name),
        release_date=release_date,
        release_date_precision=str(raw.get("release_date_precision") or "day"),
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
    )


def release_date_interval(release: ReleaseCandidate) -> tuple[date, date] | None:
    """Return the possible date interval represented by Spotify precision."""
    try:
        parts = [int(part) for part in release.release_date.split("-")]
        year = parts[0]
        precision = release.release_date_precision.casefold()
        if precision == "year" or len(parts) == 1:
            return date(year, 1, 1), date(year, 12, 31)
        month = parts[1]
        if precision == "month" or len(parts) == 2:
            return (
                date(year, month, 1),
                date(year, month, calendar.monthrange(year, month)[1]),
            )
        day = parts[2]
        parsed = date(year, month, day)
        return parsed, parsed
    except IndexError, ValueError:
        return None


def release_scope_reason(release: ReleaseCandidate, artist_rank: int) -> str | None:
    """Return why an album/EP is excluded, or None when it is eligible."""
    if release.release_type not in {"Album", "EP"}:
        return f"{release.release_type.casefold()} is not an album or EP"
    if ALWAYS_EXCLUDED_RELEASE.search(release.name):
        return "compilation or other non-release-project title"
    if artist_rank <= NEW_VINTAGE_ARTIST_LIMIT:
        if EDITION_RELEASE.search(release.name) and not DELUXE_RELEASE.search(
            release.name
        ):
            return "non-deluxe reissue or remaster"
        return None
    if LIVE_RELEASE.search(release.name):
        return "live release outside the top 50"
    if EDITION_RELEASE.search(release.name):
        return "deluxe edition, reissue, or remaster outside the top 50"
    return None


def load_recent_catalog(
    sp: Spotify,
    artist: RankedArtist,
    spotify_artist: SpotifyArtistCandidate,
    checked_from: date,
    retry_call: RetryCall,
) -> tuple[ReleaseCandidate, ...]:
    """Load recent and future releases, stopping after a wholly old page."""
    releases: dict[str, ReleaseCandidate] = {}
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.artist_albums,
                spotify_artist.spotify_id,
                include_groups="album,single",
                limit=ARTIST_RELEASE_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading releases for {artist.name} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise ReleaseCheckSpotifyError(
                f"Spotify returned invalid release data for {artist.name}."
            )
        raw_items = response["items"]
        page_intervals: list[tuple[date, date]] = []
        for raw_release in raw_items:
            candidate = _release_candidate(
                raw_release,
                spotify_artist.spotify_id,
            )
            if candidate is None:
                continue
            interval = release_date_interval(candidate)
            if interval is None:
                continue
            page_intervals.append(interval)
            if interval[1] >= checked_from:
                releases[candidate.spotify_id] = candidate
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty release page for {artist.name}."
            )
        if page_intervals and all(end < checked_from for _, end in page_intervals):
            break
    return tuple(
        sorted(
            releases.values(),
            key=lambda release: (
                release_date_interval(release) or (date.max, date.max),
                release.release_type,
                release.name.casefold(),
                release.spotify_id,
            ),
        )
    )


def _track_candidate(raw: object, fallback_position: int) -> ReleaseTrack | None:
    """Parse one playable release track."""
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    artists = _artist_pairs(raw.get("artists"))
    if not spotify_id or not uri or not name or not artists:
        return None
    disc_number = _positive_int(raw.get("disc_number")) or 1
    track_number = _positive_int(raw.get("track_number")) or fallback_position
    return ReleaseTrack(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        disc_number=disc_number,
        track_number=track_number,
    )


def load_release_tracks(
    sp: Spotify,
    release: ReleaseCandidate,
    retry_call: RetryCall,
    *,
    first_only: bool = False,
) -> tuple[ReleaseTrack, ...]:
    """Load tracks in Spotify disc and track order."""
    tracks: list[ReleaseTrack] = []
    offset = 0
    limit = 1 if first_only else RELEASE_TRACK_PAGE_LIMIT
    while True:
        try:
            response = retry_call(
                partial(
                    sp.album_tracks,
                    release.spotify_id,
                    limit=limit,
                    offset=offset,
                ),
                f"loading tracks from {release.name} at offset {offset}",
            )
        except SpotifyException as exc:
            if exc.http_status != 404:
                raise
            return ()
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise ReleaseCheckSpotifyError(
                f"Spotify returned invalid track data for {release.name}."
            )
        raw_items = response["items"]
        for raw_track in raw_items:
            track = _track_candidate(raw_track, len(tracks) + 1)
            if track is not None:
                tracks.append(track)
        if first_only or not response.get("next"):
            break
        offset += len(raw_items)
        if not raw_items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty track page for {release.name}."
            )
    return tuple(
        sorted(
            tracks,
            key=lambda track: (track.disc_number, track.track_number),
        )
    )


def matching_future_release(
    sp: Spotify,
    single_track: ReleaseTrack,
    future_releases: tuple[ReleaseCandidate, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[ReleaseTrack, ...]] | None = None,
) -> ReleaseCandidate | None:
    """Find an announced record containing the selected single track."""
    cached_tracks = track_cache if track_cache is not None else {}
    expected_name = blast_from_past.normalize_name(
        blast_from_past.without_sliding_qualifiers(single_track.name)
    )
    for release in future_releases:
        tracks = cached_tracks.get(release.spotify_id)
        if tracks is None:
            tracks = load_release_tracks(sp, release, retry_call)
            cached_tracks[release.spotify_id] = tracks
        for track in tracks:
            actual_name = blast_from_past.normalize_name(
                blast_from_past.without_sliding_qualifiers(track.name)
            )
            if track.spotify_id == single_track.spotify_id or (
                expected_name and actual_name == expected_name
            ):
                return release
    return None


def _default_state() -> dict[str, Any]:
    """Return an empty versioned release-check state."""
    return {
        "version": STATE_VERSION,
        "last_successful_check_at": None,
        "last_checked_through": None,
        "artist_mappings": {},
        "skipped_artists": {},
        "processed_releases": {},
        "pending_singles": {},
        "active_run": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    """Load restart state without silently discarding malformed data."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseCheckStateError(f"Release-check state is invalid: {path}") from exc
    if isinstance(raw, dict):
        # Version 1 state predates durable artist skips.
        raw.setdefault("skipped_artists", {})
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("artist_mappings"), dict)
        or not isinstance(raw.get("skipped_artists"), dict)
        or not isinstance(raw.get("processed_releases"), dict)
        or not isinstance(raw.get("pending_singles"), dict)
        or (
            raw.get("active_run") is not None
            and not isinstance(raw["active_run"], dict)
        )
    ):
        raise ReleaseCheckStateError(f"Release-check state is invalid: {path}")
    return raw


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist release-check state atomically."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise ReleaseCheckStateError(
            f"Could not save release-check state: {path}"
        ) from exc


def append_event(
    path: Path,
    run_id: str,
    event: str,
    **details: object,
) -> None:
    """Append one reviewable release-check audit event."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "event": event,
        **details,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ReleaseCheckStateError(
            f"Could not write release-check audit log: {path}"
        ) from exc


def _active_artists(active: dict[str, Any]) -> tuple[RankedArtist, ...]:
    """Parse the frozen artist ranking from an active run."""
    raw_artists = active.get("artists")
    if not isinstance(raw_artists, list):
        raise ReleaseCheckStateError("The active release-check ranking is invalid.")
    try:
        return tuple(RankedArtist(**raw) for raw in raw_artists)
    except (TypeError, ValueError) as exc:
        raise ReleaseCheckStateError(
            "The active release-check ranking is invalid."
        ) from exc


def _mapped_artist(raw: object) -> SpotifyArtistCandidate | None:
    """Parse one persisted Last.fm-to-Spotify mapping."""
    if not isinstance(raw, dict):
        return None
    try:
        return SpotifyArtistCandidate(**raw)
    except TypeError, ValueError:
        return None


def _pending_single(raw: object) -> PendingSingle | None:
    """Parse one pending single from restart state."""
    if not isinstance(raw, dict):
        return None
    try:
        return PendingSingle(
            artist_key=str(raw["artist_key"]),
            release=ReleaseCandidate(**raw["release"]),
            first_track=ReleaseTrack(**raw["first_track"]),
        )
    except KeyError, TypeError, ValueError:
        return None


def _run_id(now: datetime) -> str:
    """Return a sortable identifier for one release check."""
    return now.strftime("%Y%m%dT%H%M%S%fZ")


def _playlist_membership(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> PlaylistMembership:
    """Load one destination playlist once."""
    raw = retry_call(
        partial(blast_from_past.load_playlist_state, sp, playlist_id),
        f"loading playlist {playlist_id}",
    )
    if not isinstance(raw, blast_from_past.PlaylistState):
        raise ReleaseCheckSpotifyError(
            f"Spotify returned invalid playlist data for {playlist_id}."
        )
    return PlaylistMembership(set(raw.track_ids), set(raw.track_keys))


def _track_key(track: ReleaseTrack) -> tuple[str, str]:
    """Return the same artist/title identity used by playlist scans."""
    return (
        blast_from_past.normalize_name(track.primary_artist_name),
        blast_from_past.normalize_name(
            blast_from_past.without_sliding_qualifiers(track.name)
        ),
    )


def _track_is_present(
    membership: PlaylistMembership,
    track: ReleaseTrack,
) -> bool:
    """Return whether a playlist already contains this track identity."""
    return (
        track.spotify_id in membership.track_ids
        or _track_key(track) in membership.track_keys
    )


def _add_to_playlist(
    sp: Spotify,
    playlist_id: str,
    membership: PlaylistMembership,
    track: ReleaseTrack,
    dry_run: bool,
    retry_call: RetryCall,
) -> PlaylistAction:
    """Add one track unless its id or normalized identity is already present."""
    key = _track_key(track)
    if _track_is_present(membership, track):
        return "already present"
    if dry_run:
        membership.track_ids.add(track.spotify_id)
        membership.track_keys.add(key)
        return "would add"
    retry_call(
        partial(
            sp._post,
            f"playlists/{playlist_id}/items",
            payload={"uris": [track.uri]},
        ),
        f"adding {track.name} to playlist {playlist_id}",
    )
    membership.track_ids.add(track.spotify_id)
    membership.track_keys.add(key)
    return "added"


def _release_identity(release: ReleaseCandidate) -> tuple[str, str, str]:
    """Collapse market duplicates without merging deluxe and plain releases."""
    return (
        blast_from_past.normalize_name(release.name),
        release.release_date,
        release.release_type,
    )


def release_tags(release: ReleaseCandidate) -> tuple[str, ...]:
    """Return prominent review labels for special eligible releases."""
    tags: list[str] = []
    if LIVE_RELEASE.search(release.name):
        tags.append("LIVE")
    if DELUXE_RELEASE.search(release.name):
        tags.append("DELUXE")
    return tuple(tags)


def _released_during(
    release: ReleaseCandidate,
    checked_from: date,
    checked_through: date,
) -> bool:
    """Return whether a release's precision interval overlaps the check window."""
    interval = release_date_interval(release)
    return bool(
        interval and interval[0] <= checked_through and interval[1] >= checked_from
    )


def _future_record(
    release: ReleaseCandidate,
    checked_through: date,
    artist_rank: int,
) -> bool:
    """Return whether a qualifying album/EP is definitely still unreleased."""
    interval = release_date_interval(release)
    return bool(
        interval
        and interval[0] > checked_through
        and release_scope_reason(release, artist_rank) is None
    )


def _result(
    artist: RankedArtist,
    spotify_artist: SpotifyArtistCandidate,
    release: ReleaseCandidate,
    *,
    track: ReleaseTrack | None = None,
    linked_future_release: ReleaseCandidate | None = None,
    wine_cellar_action: PlaylistAction = "not applicable",
    new_vintage_action: PlaylistAction = "not applicable",
    reason: str | None = None,
    dry_run: bool,
) -> ReleaseCheckResult:
    """Build one consistent release result."""
    return ReleaseCheckResult(
        artist=artist.name,
        artist_rank=artist.rank,
        artist_scrobbles=artist.scrobbles,
        spotify_artist_id=spotify_artist.spotify_id,
        release_id=release.spotify_id,
        release=release.name,
        release_type=release.release_type,
        release_date=release.release_date,
        first_track_id=track.spotify_id if track else None,
        first_track=track.name if track else None,
        linked_future_release=(
            linked_future_release.name if linked_future_release else None
        ),
        wine_cellar_action=wine_cellar_action,
        new_vintage_action=new_vintage_action,
        reason=reason,
        dry_run=dry_run,
    )


def _mark_processed(
    state: dict[str, Any],
    result: ReleaseCheckResult,
    checked_at: datetime,
) -> None:
    """Record a terminal release decision in restart state."""
    processed = state["processed_releases"]
    assert isinstance(processed, dict)
    processed[result.release_id] = {
        "checked_at": checked_at.isoformat(),
        "artist": result.artist,
        "release": result.release,
        "reason": result.reason,
        "wine_cellar_action": result.wine_cellar_action,
        "new_vintage_action": result.new_vintage_action,
    }


def _store_pending(
    state: dict[str, Any],
    pending: PendingSingle,
) -> None:
    """Persist an unconfirmed single for a later release check."""
    pending_singles = state["pending_singles"]
    assert isinstance(pending_singles, dict)
    pending_singles[pending.release.spotify_id] = {
        "artist_key": pending.artist_key,
        "release": asdict(pending.release),
        "first_track": asdict(pending.first_track),
    }


def _remove_pending(state: dict[str, Any], release_id: str) -> None:
    """Remove a pending single after a terminal decision."""
    pending_singles = state["pending_singles"]
    assert isinstance(pending_singles, dict)
    pending_singles.pop(release_id, None)


def _record_result(
    state: dict[str, Any],
    result: ReleaseCheckResult,
    checked_at: datetime,
    run_id: str,
    log_path: Path,
    state_path: Path,
    dry_run: bool,
    *,
    terminal: bool,
) -> None:
    """Audit and checkpoint one release boundary."""
    if dry_run:
        return
    append_event(log_path, run_id, "release_checked", result=asdict(result))
    if terminal:
        _mark_processed(state, result, checked_at)
        _remove_pending(state, result.release_id)
    save_state(state, state_path)


def _summary(
    *,
    run_id: str,
    checked_from: date,
    checked_through: date,
    artists: tuple[RankedArtist, ...],
    completed: set[str],
    dry_run: bool,
    resumed: bool,
    paused: bool,
    history_refresh: scrobble_history.ScrobbleHistorySummary | None,
    results: list[ReleaseCheckResult],
) -> ReleaseCheckSummary:
    """Build a summary at a normal or paused boundary."""
    return ReleaseCheckSummary(
        run_id=run_id,
        checked_from=checked_from,
        checked_through=checked_through,
        artists_total=len(artists),
        artists_processed=len(completed),
        dry_run=dry_run,
        resumed=resumed,
        paused=paused,
        history_refresh=history_refresh,
        results=tuple(results),
    )


def run_release_check(
    sp: Spotify,
    lastfm: LastFmReader,
    playlists: ReleaseCheckPlaylists,
    *,
    expected_username: str | None,
    artist_choice_reader: ArtistChoiceReader | None = None,
    release_choice_reader: ReleaseChoiceReader | None = None,
    dry_run: bool = False,
    state_path: Path = DEFAULT_STATE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    export_path: Path = scrobble_history.DEFAULT_SCROBBLES_PATH,
    legacy_delta_path: Path | None = scrobble_history.DEFAULT_LEGACY_DELTA_PATH,
    backup_dir: Path = scrobble_history.DEFAULT_BACKUP_DIR,
    history_log_path: Path = scrobble_history.DEFAULT_LOG_PATH,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
) -> ReleaseCheckSummary:
    """Refresh Last.fm, discover releases, and update both playlists safely."""
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    today = generated_at.astimezone(blast_from_past.SCROBBLE_TIMEZONE).date()
    persisted_state = load_state(state_path)
    state = deepcopy(persisted_state)
    raw_active = state.get("active_run")
    resumed = isinstance(raw_active, dict)
    history_refresh: scrobble_history.ScrobbleHistorySummary | None = None

    if resumed:
        assert isinstance(raw_active, dict)
        active = raw_active
        artists = _active_artists(active)
        try:
            checked_from = date.fromisoformat(str(active["checked_from"]))
            checked_through = date.fromisoformat(str(active["checked_through"]))
            run_id = str(active["run_id"])
        except (KeyError, ValueError) as exc:
            raise ReleaseCheckStateError(
                "The active release-check window is invalid."
            ) from exc
    else:
        history_refresh = scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username=expected_username,
            export_path=export_path,
            legacy_delta_path=legacy_delta_path,
            backup_dir=backup_dir,
            log_path=history_log_path,
            dry_run=False,
            now=generated_at,
            progress_callback=(
                (lambda message: progress_callback(0, 0, message))
                if progress_callback is not None
                else None
            ),
        )
        artists = rank_lastfm_artists(history_refresh.history)
        if not artists:
            raise ReleaseCheckError(
                f"No Last.fm artists have at least {MIN_ARTIST_SCROBBLES} scrobbles."
            )
        raw_last_date = state.get("last_checked_through")
        if isinstance(raw_last_date, str):
            try:
                checked_from = date.fromisoformat(raw_last_date)
            except ValueError as exc:
                raise ReleaseCheckStateError(
                    "The previous release-check date is invalid."
                ) from exc
        else:
            checked_from = date(today.year, 1, 1)
        checked_through = today
        run_id = _run_id(generated_at)
        active = {
            "run_id": run_id,
            "started_at": generated_at.isoformat(),
            "checked_from": checked_from.isoformat(),
            "checked_through": checked_through.isoformat(),
            "artists": [asdict(artist) for artist in artists],
            "completed_artist_keys": [],
            "pending_release_id": None,
        }
        state["active_run"] = active
        if not dry_run:
            save_state(state, state_path)
            append_event(
                log_path,
                run_id,
                "run_started",
                checked_from=checked_from.isoformat(),
                checked_through=checked_through.isoformat(),
                artists=len(artists),
            )

    raw_completed = active.get("completed_artist_keys", [])
    if not isinstance(raw_completed, list):
        raise ReleaseCheckStateError("The active release-check progress is invalid.")
    completed = {str(key) for key in raw_completed}
    mappings = state["artist_mappings"]
    skipped_artists = state["skipped_artists"]
    processed_releases = state["processed_releases"]
    pending_singles = state["pending_singles"]
    assert isinstance(mappings, dict)
    assert isinstance(skipped_artists, dict)
    assert isinstance(processed_releases, dict)
    assert isinstance(pending_singles, dict)

    if progress_callback is not None:
        progress_callback(
            len(completed),
            len(artists),
            "Loading destination playlists",
        )
    wine_membership = _playlist_membership(
        sp,
        playlists.wine_cellar,
        retry_call,
    )
    vintage_membership = _playlist_membership(
        sp,
        playlists.new_vintage,
        retry_call,
    )
    results: list[ReleaseCheckResult] = []

    for artist in artists:
        if artist.key in completed:
            continue
        if artist.key in skipped_artists:
            completed.add(artist.key)
            active["completed_artist_keys"] = sorted(completed)
            if not dry_run:
                save_state(state, state_path)
            if progress_callback is not None:
                progress_callback(
                    len(completed),
                    len(artists),
                    f"#{artist.rank} {artist.name}: permanently skipped",
                )
            continue
        if progress_callback is not None:
            progress_callback(
                len(completed),
                len(artists),
                f"#{artist.rank} {artist.name}: resolving Spotify artist",
            )

        spotify_artist = _mapped_artist(mappings.get(artist.key))
        if spotify_artist is None:
            resolved = resolve_spotify_artist(
                sp,
                artist,
                artist_choice_reader,
                retry_call,
            )
            if resolved == CHOICE_QUIT:
                if not dry_run:
                    append_event(log_path, run_id, "run_paused", artist=artist.name)
                return _summary(
                    run_id=run_id,
                    checked_from=checked_from,
                    checked_through=checked_through,
                    artists=artists,
                    completed=completed,
                    dry_run=dry_run,
                    resumed=resumed,
                    paused=True,
                    history_refresh=history_refresh,
                    results=results,
                )
            if resolved == CHOICE_SKIP_ARTIST:
                skip_record = {
                    "artist": artist.name,
                    "rank": artist.rank,
                    "scrobbles": artist.scrobbles,
                    "skipped_at": generated_at.isoformat(),
                }
                skipped_artists[artist.key] = skip_record
                completed.add(artist.key)
                active["completed_artist_keys"] = sorted(completed)
                if dry_run:
                    persisted_skips = persisted_state["skipped_artists"]
                    assert isinstance(persisted_skips, dict)
                    persisted_skips[artist.key] = skip_record
                    save_state(persisted_state, state_path)
                else:
                    append_event(
                        log_path,
                        run_id,
                        "artist_permanently_skipped",
                        artist=artist.name,
                    )
                    save_state(state, state_path)
                continue
            if resolved in {None, CHOICE_SKIP}:
                completed.add(artist.key)
                active["completed_artist_keys"] = sorted(completed)
                if not dry_run:
                    append_event(
                        log_path,
                        run_id,
                        "artist_skipped",
                        artist=artist.name,
                        reason=(
                            "no Spotify search result"
                            if resolved is None
                            else "interactive skip"
                        ),
                    )
                    save_state(state, state_path)
                continue
            assert isinstance(resolved, SpotifyArtistCandidate)
            spotify_artist = resolved
            mappings[artist.key] = asdict(spotify_artist)
            if dry_run:
                persisted_mappings = persisted_state["artist_mappings"]
                assert isinstance(persisted_mappings, dict)
                persisted_mappings[artist.key] = asdict(spotify_artist)
                save_state(persisted_state, state_path)
            else:
                save_state(state, state_path)

        if progress_callback is not None:
            progress_callback(
                len(completed),
                len(artists),
                f"#{artist.rank} {artist.name}: checking releases",
            )
        catalog = load_recent_catalog(
            sp,
            artist,
            spotify_artist,
            checked_from,
            retry_call,
        )
        future_records = tuple(
            release
            for release in catalog
            if _future_record(release, checked_through, artist.rank)
        )
        record_track_cache: dict[str, tuple[ReleaseTrack, ...]] = {}

        current_by_identity: dict[tuple[str, str, str], ReleaseCandidate] = {}
        duplicates: list[ReleaseCandidate] = []
        for release in catalog:
            if not _released_during(release, checked_from, checked_through):
                continue
            identity = _release_identity(release)
            existing = current_by_identity.get(identity)
            if existing is None:
                current_by_identity[identity] = release
            else:
                preferred = min(
                    (existing, release),
                    key=lambda item: (-item.total_tracks, item.spotify_id),
                )
                duplicates.append(release if preferred is existing else existing)
                current_by_identity[identity] = preferred

        for duplicate in duplicates:
            if duplicate.spotify_id in processed_releases:
                continue
            result = _result(
                artist,
                spotify_artist,
                duplicate,
                reason="duplicate Spotify market edition",
                dry_run=dry_run,
            )
            results.append(result)
            _record_result(
                state,
                result,
                generated_at,
                run_id,
                log_path,
                state_path,
                dry_run,
                terminal=True,
            )

        current_records = tuple(
            release
            for release in current_by_identity.values()
            if release.release_type in {"Album", "EP"}
            and release_scope_reason(release, artist.rank) is None
        )

        pending_for_artist = {
            release_id: pending
            for release_id, raw in pending_singles.items()
            if (pending := _pending_single(raw)) is not None
            and pending.artist_key == artist.key
        }
        releases_to_check = list(current_by_identity.values())
        releases_to_check.extend(
            pending.release
            for release_id, pending in pending_for_artist.items()
            if release_id not in current_by_identity
        )
        releases_to_check.sort(
            key=lambda release: (
                release_date_interval(release) or (date.max, date.max),
                release.release_type,
                release.name.casefold(),
                release.spotify_id,
            )
        )

        for release in releases_to_check:
            pending = pending_for_artist.get(release.spotify_id)
            if release.spotify_id in processed_releases and pending is None:
                continue
            active["pending_release_id"] = release.spotify_id
            if not dry_run:
                save_state(state, state_path)

            track: ReleaseTrack | None = pending.first_track if pending else None
            linked_future: ReleaseCandidate | None = None
            reason: str | None = None
            unattached_single = False
            if release.release_type == "Single":
                if track is None:
                    first_tracks = load_release_tracks(
                        sp,
                        release,
                        retry_call,
                        first_only=True,
                    )
                    track = first_tracks[0] if first_tracks else None
                if track is None:
                    reason = "release has no playable first track"
                elif not artist.accepts_all_singles:
                    linked_future = matching_future_release(
                        sp,
                        track,
                        future_records,
                        retry_call,
                        record_track_cache,
                    )
                    if linked_future is None:
                        released_record = matching_future_release(
                            sp,
                            track,
                            current_records,
                            retry_call,
                            record_track_cache,
                        )
                        if released_record is not None:
                            reason = "containing album or EP has already been released"
                        else:
                            unattached_single = True
            else:
                reason = release_scope_reason(release, artist.rank)
                if reason is None:
                    first_tracks = load_release_tracks(
                        sp,
                        release,
                        retry_call,
                        first_only=True,
                    )
                    track = first_tracks[0] if first_tracks else None
                    if track is None:
                        reason = "release has no playable first track"

            terminal = True
            if reason is not None:
                result = _result(
                    artist,
                    spotify_artist,
                    release,
                    track=track,
                    reason=reason,
                    dry_run=dry_run,
                )
            else:
                assert track is not None
                vintage_applicable = artist.is_new_vintage and (
                    release.release_type != "Single" or artist.accepts_all_singles
                )
                destinations: list[str] = []
                if not _track_is_present(wine_membership, track):
                    destinations.append("Wine Cellar")
                if vintage_applicable and not _track_is_present(
                    vintage_membership,
                    track,
                ):
                    destinations.append("New Vintage")

                choice = (
                    CHOICE_PENDING if unattached_single and destinations else CHOICE_ADD
                )
                if destinations and release_choice_reader is not None:
                    choice = release_choice_reader(
                        artist,
                        release,
                        track,
                        tuple(destinations),
                        unattached_single,
                    )
                if choice == CHOICE_QUIT:
                    if not dry_run:
                        append_event(
                            log_path,
                            run_id,
                            "run_paused",
                            artist=artist.name,
                            release=release.name,
                        )
                    return _summary(
                        run_id=run_id,
                        checked_from=checked_from,
                        checked_through=checked_through,
                        artists=artists,
                        completed=completed,
                        dry_run=dry_run,
                        resumed=resumed,
                        paused=True,
                        history_refresh=history_refresh,
                        results=results,
                    )
                if choice == CHOICE_PENDING and not unattached_single:
                    raise ReleaseCheckError(
                        "Only an unattached single can remain pending."
                    )
                if choice not in {CHOICE_ADD, CHOICE_PENDING, CHOICE_SKIP}:
                    raise ReleaseCheckError("The release review choice is invalid.")
                if choice == CHOICE_PENDING:
                    _store_pending(
                        state,
                        PendingSingle(artist.key, release, track),
                    )
                    terminal = False
                    result = _result(
                        artist,
                        spotify_artist,
                        release,
                        track=track,
                        reason="single kept pending for a future album or EP",
                        dry_run=dry_run,
                    )
                    results.append(result)
                    _record_result(
                        state,
                        result,
                        generated_at,
                        run_id,
                        log_path,
                        state_path,
                        dry_run,
                        terminal=False,
                    )
                    active["pending_release_id"] = None
                    if not dry_run:
                        save_state(state, state_path)
                    continue
                if choice == CHOICE_SKIP:
                    result = _result(
                        artist,
                        spotify_artist,
                        release,
                        track=track,
                        linked_future_release=linked_future,
                        reason="skipped by user",
                        dry_run=dry_run,
                    )
                    results.append(result)
                    _record_result(
                        state,
                        result,
                        generated_at,
                        run_id,
                        log_path,
                        state_path,
                        dry_run,
                        terminal=True,
                    )
                    active["pending_release_id"] = None
                    if not dry_run:
                        save_state(state, state_path)
                    continue

                wine_action = _add_to_playlist(
                    sp,
                    playlists.wine_cellar,
                    wine_membership,
                    track,
                    dry_run,
                    retry_call,
                )
                vintage_action: PlaylistAction = "not applicable"
                if vintage_applicable:
                    vintage_action = _add_to_playlist(
                        sp,
                        playlists.new_vintage,
                        vintage_membership,
                        track,
                        dry_run,
                        retry_call,
                    )
                result = _result(
                    artist,
                    spotify_artist,
                    release,
                    track=track,
                    linked_future_release=linked_future,
                    wine_cellar_action=wine_action,
                    new_vintage_action=vintage_action,
                    dry_run=dry_run,
                )
            results.append(result)
            _record_result(
                state,
                result,
                generated_at,
                run_id,
                log_path,
                state_path,
                dry_run,
                terminal=terminal,
            )
            active["pending_release_id"] = None
            if not dry_run:
                save_state(state, state_path)

        completed.add(artist.key)
        active["completed_artist_keys"] = sorted(completed)
        if not dry_run:
            save_state(state, state_path)
        if progress_callback is not None:
            progress_callback(
                len(completed),
                len(artists),
                f"#{artist.rank} {artist.name}: complete",
            )

    if not dry_run:
        state["last_successful_check_at"] = datetime.now(UTC).isoformat()
        state["last_checked_through"] = checked_through.isoformat()
        state["active_run"] = None
        save_state(state, state_path)
        append_event(
            log_path,
            run_id,
            "run_completed",
            checked_through=checked_through.isoformat(),
            artists=len(artists),
            releases=len(results),
        )
    return _summary(
        run_id=run_id,
        checked_from=checked_from,
        checked_through=checked_through,
        artists=artists,
        completed=completed,
        dry_run=dry_run,
        resumed=resumed,
        paused=False,
        history_refresh=history_refresh,
        results=results,
    )


__all__ = [
    "CHOICE_ADD",
    "CHOICE_PENDING",
    "CHOICE_QUIT",
    "CHOICE_SEARCH_PREFIX",
    "CHOICE_SKIP",
    "CHOICE_SKIP_ARTIST",
    "ReleaseCheckConfigError",
    "ReleaseCheckError",
    "ReleaseCheckPlaylists",
    "ReleaseCheckResult",
    "ReleaseCheckStateError",
    "ReleaseCheckSummary",
    "ReleaseCheckSpotifyError",
    "SpotifyArtistCandidate",
    "RankedArtist",
    "matching_future_release",
    "rank_lastfm_artists",
    "release_scope_reason",
    "release_tags",
    "run_release_check",
]
