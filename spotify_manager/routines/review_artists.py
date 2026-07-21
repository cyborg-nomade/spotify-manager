"""Restart-safe review of followed artists and listening queues."""

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep
from typing import Any

from pydantic import BaseModel
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines.recover_removed_albums import period_report
from spotify_manager.routines.review_album_limits import TRANSIENT_MAX_ATTEMPTS
from spotify_manager.routines.review_album_limits import TRANSIENT_RETRY_DELAY_SECONDS
from spotify_manager.routines.review_album_limits import SpotifyRateLimitError
from spotify_manager.routines.review_album_limits import SpotifyTransientServerError
from spotify_manager.routines.review_album_limits import retry_spotify_server_errors
from spotify_manager.utils.growth import calculate_growth
from spotify_manager.utils.sorting import artist_sort_key


SEARCH_LIMIT = 10
SEARCH_MAX_PAGES = 3
ARTIST_ALBUM_PAGE_LIMIT = 10
PLAYLIST_PAGE_LIMIT = 50
PLAYLIST_MUTATION_BATCH_SIZE = 100
UNFOLLOW_BATCH_SIZE = 40

CHOICE_SKIP = "skip"
CHOICE_QUIT = "quit"
CHOICE_DECLINE = "decline"

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
TrackChoiceReader = Callable[[YourLibraryArtist, tuple["TrackCandidate", ...]], str]
ReleaseChoiceReader = Callable[
    [YourLibraryArtist, tuple["ReleaseCandidate", ...], bool], str
]
Sleep = Callable[[float], None]
RetryCall = Callable[[Callable[[], object], str], object]


class ArtistReviewError(RuntimeError):
    """Base exception for a review that cannot continue safely."""


class ArtistReviewConfigError(ArtistReviewError):
    """Raised when queue playlist configuration is missing or invalid."""


class InvalidReviewChoiceError(ArtistReviewError):
    """Raised when an interactive callback returns an unknown choice."""


@dataclass(frozen=True)
class ArtistReviewPaths:
    """Files read and written by the artist review."""

    artists: Path
    liked_tracks: Path
    stats_history: Path
    log: Path
    cache: Path

    @classmethod
    def for_files_dir(cls, files_dir: Path) -> ArtistReviewPaths:
        """Build conventional review paths beneath a files directory."""
        return cls(
            artists=files_dir / "artists_total.json",
            liked_tracks=files_dir / "liked_tracks_total.json",
            stats_history=files_dir / "stats_history.json",
            log=files_dir / "artist_review_log.jsonl",
            cache=files_dir / "artist_review_cache.json",
        )


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_PATHS = ArtistReviewPaths.for_files_dir(FILES_DIR)


@dataclass(frozen=True)
class QueuePlaylists:
    """Playlist ids for the three liked-track tiers."""

    queue_1: str
    queue_2: str
    queue_3: str

    @classmethod
    def from_references(
        cls,
        queue_1: str | None,
        queue_2: str | None,
        queue_3: str | None,
    ) -> QueuePlaylists:
        """Parse playlist URLs, URIs, or bare ids from configuration."""
        missing = [
            name
            for name, value in (
                ("the_queue_playlist", queue_1),
                ("the_queue_2_playlist", queue_2),
                ("the_queue_3_playlist", queue_3),
            )
            if not value
        ]
        if missing:
            raise ArtistReviewConfigError(
                "Missing queue playlist setting(s): " + ", ".join(missing)
            )
        assert queue_1 is not None
        assert queue_2 is not None
        assert queue_3 is not None
        return cls(
            queue_1=parse_playlist_id(queue_1),
            queue_2=parse_playlist_id(queue_2),
            queue_3=parse_playlist_id(queue_3),
        )

    def for_liked_count(self, liked_count: int) -> str:
        """Return the queue matching one positive liked-track count."""
        if liked_count <= 5:
            return self.queue_1
        if liked_count <= 17:
            return self.queue_2
        return self.queue_3


@dataclass(frozen=True)
class TrackCandidate:
    """A Spotify-ranked track associated with the reviewed artist."""

    spotify_id: str
    name: str
    uri: str
    album: str
    rank: int
    primary_artist_id: str
    primary_artist_name: str
    artist_ids: tuple[str, ...]
    popularity: int | None = None


@dataclass
class ReleaseCandidate:
    """A release and its first-track primary credit."""

    spotify_id: str
    name: str
    uri: str
    release_type: str
    release_date: str
    total_tracks: int
    rank: int
    primary_artist_id: str
    primary_artist_name: str
    artist_ids: tuple[str, ...]
    first_track_checked: bool = False
    first_track_id: str | None = None
    first_track_name: str | None = None
    first_track_uri: str | None = None
    first_track_primary_artist_id: str | None = None
    first_track_primary_artist_name: str | None = None

    def is_eligible_for(self, artist_id: str) -> bool:
        """Return whether the release's first track credits the target first."""
        return (
            self.first_track_id is not None
            and self.first_track_primary_artist_id == artist_id
        )


@dataclass
class PlaylistMembership:
    """Primary artists and tracks already represented in one queue."""

    primary_artist_ids: set[str]
    track_ids: set[str]
    track_uris_by_primary_artist: dict[str, list[str]]


@dataclass
class ArtistReviewState:
    """Completed work and pending automatic unfollows reconstructed from logs."""

    completed_artist_ids: set[str]
    pending_unfollows: dict[str, dict[str, object]]
    pending_queue_moves: dict[str, dict[str, object]]


@dataclass
class ReviewCounts:
    """Mutable counters for one command invocation."""

    reviewed: int = 0
    unfollowed: int = 0
    queued: int = 0
    moved: int = 0
    already_queued: int = 0
    declined: int = 0
    no_action: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ArtistReviewSummary:
    """Outcome of one invocation of the artist review."""

    total_pending_at_start: int
    reviewed: int
    unfollowed: int
    queued: int
    moved: int
    already_queued: int
    declined: int
    no_action: int
    skipped: int
    paused: bool


def normalize_name(value: str) -> str:
    """Normalize an artist or track name for local matching."""
    return value.strip().casefold()


def parse_playlist_id(reference: str) -> str:
    """Extract a Spotify playlist id from a URL, URI, or bare id."""
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
    raise ArtistReviewConfigError(f"Invalid Spotify playlist reference: {reference}")


def utc_now() -> str:
    """Return a JSON-friendly UTC timestamp."""
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    """Return a sortable review run identifier."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def load_json(path: Path, default: object) -> Any:
    """Load JSON or return a default when the file is absent."""
    try:
        with open(path) as input_file:
            return json.load(input_file)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ArtistReviewError(f"Invalid JSON in {path}.") from exc


def write_json_atomic(path: Path, value: object) -> None:
    """Atomically replace a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(temporary_path, "w") as output_file:
        json.dump(value, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(path)


def append_events(path: Path, events: list[dict[str, object]]) -> None:
    """Append audit events as JSON Lines."""
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as output_file:
        for event in events:
            output_file.write(json.dumps(event, ensure_ascii=False) + "\n")


def event(run_id: str, event_name: str, **details: object) -> dict[str, object]:
    """Build one timestamped audit event."""
    return {
        "timestamp": utc_now(),
        "run_id": run_id,
        "event": event_name,
        **details,
    }


def load_models[T: BaseModel](path: Path, model_type: type[T]) -> list[T]:
    """Load a JSON list of Pydantic models."""
    raw = load_json(path, [])
    if not isinstance(raw, list):
        raise ArtistReviewError(f"Expected a JSON list in {path}.")
    return [model_type.model_validate(item) for item in raw]


def log_int(value: object) -> int:
    """Parse a trusted integer field reconstructed from the JSONL audit log."""
    try:
        return int(str(value))
    except ValueError:
        return 0


def save_artists(path: Path, artists: list[YourLibraryArtist]) -> None:
    """Persist followed artists in the established sort order."""
    artists.sort(key=artist_sort_key)
    write_json_atomic(path, [artist.model_dump() for artist in artists])


def load_review_state(log_path: Path) -> ArtistReviewState:
    """Reconstruct completed artists and unfinished unfollow plans."""
    state = ArtistReviewState(
        completed_artist_ids=set(),
        pending_unfollows={},
        pending_queue_moves={},
    )
    if not log_path.exists():
        return state
    with open(log_path) as log_file:
        for line in log_file:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            artist_id = str(entry.get("artist_id") or "").strip()
            if not artist_id:
                continue
            if entry.get("event") == "unfollow_planned":
                state.pending_unfollows[artist_id] = entry
            elif entry.get("event") == "queue_move_planned":
                state.pending_queue_moves[artist_id] = entry
            elif entry.get("event") == "artist_completed":
                state.completed_artist_ids.add(artist_id)
                state.pending_unfollows.pop(artist_id, None)
                state.pending_queue_moves.pop(artist_id, None)
    return state


def load_cache(path: Path, refresh: bool) -> dict[str, dict[str, object]]:
    """Load reusable catalog metadata, or start fresh when requested."""
    if refresh:
        return {}
    raw = load_json(path, {})
    if not isinstance(raw, dict):
        raise ArtistReviewError(f"Expected a JSON object in {path}.")
    return raw


def save_cache(path: Path, cache: dict[str, dict[str, object]]) -> None:
    """Persist the catalog cache after every completed metadata unit."""
    write_json_atomic(path, cache)


def artist_ids(raw_item: dict[str, object]) -> tuple[str, ...]:
    """Extract ordered artist ids from a Spotify track or release."""
    raw_artists = raw_item.get("artists")
    if not isinstance(raw_artists, list):
        return ()
    return tuple(
        str(raw_artist.get("id"))
        for raw_artist in raw_artists
        if isinstance(raw_artist, dict) and raw_artist.get("id")
    )


def first_artist_name(raw_item: dict[str, object]) -> str:
    """Return the first credited artist name, if present."""
    raw_artists = raw_item.get("artists")
    if not isinstance(raw_artists, list) or not raw_artists:
        return "Unknown artist"
    first = raw_artists[0]
    if not isinstance(first, dict):
        return "Unknown artist"
    return str(first.get("name") or "Unknown artist")


def track_candidate(
    raw_track: object,
    rank: int,
    target_artist_id: str,
) -> TrackCandidate | None:
    """Convert an associated Spotify track into a compact candidate."""
    if not isinstance(raw_track, dict):
        return None
    ids = artist_ids(raw_track)
    if target_artist_id not in ids or not ids:
        return None
    spotify_id = str(raw_track.get("id") or "").strip()
    uri = str(raw_track.get("uri") or "").strip()
    if not spotify_id or not uri:
        return None
    raw_album = raw_track.get("album")
    album = (
        str(raw_album.get("name") or "Unknown release")
        if isinstance(raw_album, dict)
        else "Unknown release"
    )
    popularity = raw_track.get("popularity")
    return TrackCandidate(
        spotify_id=spotify_id,
        name=str(raw_track.get("name") or spotify_id),
        uri=uri,
        album=album,
        rank=rank,
        primary_artist_id=ids[0],
        primary_artist_name=first_artist_name(raw_track),
        artist_ids=ids,
        popularity=popularity if isinstance(popularity, int) else None,
    )


def release_type(raw_release: dict[str, object]) -> str:
    """Classify Spotify's album types, distinguishing EPs from singles."""
    raw_type = str(raw_release.get("album_type") or "unknown").casefold()
    total_tracks = raw_release.get("total_tracks")
    track_count = total_tracks if isinstance(total_tracks, int) else 0
    if raw_type == "album":
        return "Album"
    if raw_type == "compilation":
        return "Compilation"
    if raw_type == "ep":
        return "EP"
    if raw_type == "single":
        return "EP" if track_count >= 4 else "Single"
    return raw_type.title() or "Unknown"


def release_candidate(
    raw_release: object,
    rank: int,
    target_artist_id: str,
) -> ReleaseCandidate | None:
    """Convert an associated Spotify release into a compact candidate."""
    if not isinstance(raw_release, dict):
        return None
    ids = artist_ids(raw_release)
    if target_artist_id not in ids or not ids:
        return None
    spotify_id = str(raw_release.get("id") or "").strip()
    uri = str(raw_release.get("uri") or "").strip()
    if not spotify_id or not uri:
        return None
    total_tracks = raw_release.get("total_tracks")
    return ReleaseCandidate(
        spotify_id=spotify_id,
        name=str(raw_release.get("name") or spotify_id),
        uri=uri,
        release_type=release_type(raw_release),
        release_date=str(raw_release.get("release_date") or "Unknown"),
        total_tracks=total_tracks if isinstance(total_tracks, int) else 0,
        rank=rank,
        primary_artist_id=ids[0],
        primary_artist_name=first_artist_name(raw_release),
        artist_ids=ids,
    )


def spotify_search_query(artist_name: str) -> str:
    """Build an exact-ish artist filter accepted by Spotify search."""
    clean_name = artist_name.replace('"', " ").strip()
    return f'artist:"{clean_name}"'


def ranked_artist_tracks(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[TrackCandidate]:
    """Return Spotify-ranked associated tracks using one search request."""
    artist_cache = cache.setdefault(artist.spotify_id, {})
    cached = artist_cache.get("ranked_tracks")
    if isinstance(cached, list):
        return [TrackCandidate(**item) for item in cached]

    response = retry_call(
        partial(
            sp.search,
            q=spotify_search_query(artist.name),
            type="track",
            limit=SEARCH_LIMIT,
            offset=0,
        ),
        f"searching ranked tracks for {artist.name}",
    )
    if not isinstance(response, dict):
        raise ArtistReviewError(
            f"Spotify returned invalid track search for {artist.name}."
        )
    page = response.get("tracks")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise ArtistReviewError(
            f"Spotify returned invalid track search for {artist.name}."
        )
    tracks = [
        candidate
        for rank, raw_track in enumerate(page["items"], start=1)
        if (candidate := track_candidate(raw_track, rank, artist.spotify_id))
    ][:SEARCH_LIMIT]
    artist_cache["ranked_tracks"] = [asdict(candidate) for candidate in tracks]
    save_cache(cache_path, cache)
    return tracks


def search_ranked_releases(
    sp: Spotify,
    artist: YourLibraryArtist,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Collect up to ten associated releases in Spotify search rank order."""
    releases: list[ReleaseCandidate] = []
    seen_ids: set[str] = set()
    for page_index in range(SEARCH_MAX_PAGES):
        offset = page_index * SEARCH_LIMIT
        response = retry_call(
            partial(
                sp.search,
                q=spotify_search_query(artist.name),
                type="album",
                limit=SEARCH_LIMIT,
                offset=offset,
            ),
            f"searching ranked releases for {artist.name} at offset {offset}",
        )
        if not isinstance(response, dict):
            raise ArtistReviewError(
                f"Spotify returned invalid release search for {artist.name}."
            )
        page = response.get("albums")
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ArtistReviewError(
                f"Spotify returned invalid release search for {artist.name}."
            )
        raw_items = page["items"]
        for raw_index, raw_release in enumerate(raw_items, start=1):
            candidate = release_candidate(
                raw_release,
                rank=offset + raw_index,
                target_artist_id=artist.spotify_id,
            )
            if (
                candidate is None
                or candidate.release_type not in {"Album", "EP"}
                or candidate.spotify_id in seen_ids
            ):
                continue
            seen_ids.add(candidate.spotify_id)
            releases.append(candidate)
            if len(releases) == SEARCH_LIMIT:
                return releases
        if not page.get("next") or not raw_items:
            break
    return releases


def ranked_artist_releases(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Return cached Spotify-ranked album/EP candidates with first tracks."""
    artist_cache = cache.setdefault(artist.spotify_id, {})
    cached = artist_cache.get("ranked_releases")
    if isinstance(cached, list):
        releases = [ReleaseCandidate(**item) for item in cached]
    else:
        releases = search_ranked_releases(sp, artist, retry_call)
        artist_cache["ranked_releases"] = [asdict(release) for release in releases]
        save_cache(cache_path, cache)
    return enrich_first_tracks(
        sp,
        artist,
        releases,
        "ranked_releases",
        cache,
        cache_path,
        retry_call,
    )


def release_date_key(release: ReleaseCandidate) -> tuple[int, int, int, int]:
    """Sort partial Spotify release dates chronologically, unknown dates last."""
    if release.release_date == "Unknown":
        return (1, 9999, 12, 31)
    try:
        parts = [int(part) for part in release.release_date.split("-")]
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        date(year, month, day)
        return (0, year, month, day)
    except ValueError, IndexError:
        return (1, 9999, 12, 31)


def earliest_artist_releases(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Return the artist's ten earliest releases with resumable pagination."""
    artist_cache = cache.setdefault(artist.spotify_id, {})
    cached = artist_cache.get("earliest_releases")
    if isinstance(cached, list):
        releases = [ReleaseCandidate(**item) for item in cached]
        return enrich_first_tracks(
            sp,
            artist,
            releases,
            "earliest_releases",
            cache,
            cache_path,
            retry_call,
        )

    scan = artist_cache.setdefault(
        "discography_scan",
        {"offset": 0, "complete": False, "items": []},
    )
    if not isinstance(scan, dict):
        raise ArtistReviewError(f"Invalid cached discography for {artist.name}.")
    while not scan.get("complete"):
        offset = int(scan.get("offset", 0))
        response = retry_call(
            partial(
                sp.artist_albums,
                artist.spotify_id,
                include_groups="album,single,compilation",
                limit=ARTIST_ALBUM_PAGE_LIMIT,
                offset=offset,
            ),
            f"fetching releases for {artist.name} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise ArtistReviewError(
                f"Spotify returned invalid release data for {artist.name}."
            )
        raw_items = response["items"]
        cached_items = scan.setdefault("items", [])
        if not isinstance(cached_items, list):
            raise ArtistReviewError(f"Invalid cached discography for {artist.name}.")
        cached_items.extend(raw_items)
        scan["offset"] = offset + len(raw_items)
        scan["complete"] = not response.get("next")
        if not raw_items and response.get("next"):
            raise ArtistReviewError(
                f"Spotify returned an empty release page for {artist.name}."
            )
        save_cache(cache_path, cache)

    raw_releases = scan.get("items", [])
    assert isinstance(raw_releases, list)
    by_id: dict[str, ReleaseCandidate] = {}
    for rank, raw_release in enumerate(raw_releases, start=1):
        candidate = release_candidate(raw_release, rank, artist.spotify_id)
        if candidate is not None:
            by_id[candidate.spotify_id] = candidate
    releases = sorted(by_id.values(), key=release_date_key)[:SEARCH_LIMIT]
    for rank, release in enumerate(releases, start=1):
        release.rank = rank
    artist_cache["earliest_releases"] = [asdict(release) for release in releases]
    save_cache(cache_path, cache)
    return enrich_first_tracks(
        sp,
        artist,
        releases,
        "earliest_releases",
        cache,
        cache_path,
        retry_call,
    )


def enrich_first_tracks(
    sp: Spotify,
    artist: YourLibraryArtist,
    releases: list[ReleaseCandidate],
    cache_key: str,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Fetch only each displayed release's first track and cache the result."""
    artist_cache = cache.setdefault(artist.spotify_id, {})
    for release in releases:
        if release.first_track_checked:
            continue
        try:
            response = retry_call(
                partial(sp.album_tracks, release.spotify_id, limit=1, offset=0),
                f"fetching the first track of {release.name}",
            )
        except SpotifyException as exc:
            if exc.http_status != 404:
                raise
            response = {"items": []}
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise ArtistReviewError(
                f"Spotify returned invalid first-track data for {release.name}."
            )
        raw_items = response["items"]
        release.first_track_checked = True
        if raw_items and isinstance(raw_items[0], dict):
            raw_track = raw_items[0]
            ids = artist_ids(raw_track)
            release.first_track_id = str(raw_track.get("id") or "") or None
            release.first_track_name = str(raw_track.get("name") or "") or None
            release.first_track_uri = str(raw_track.get("uri") or "") or None
            release.first_track_primary_artist_id = ids[0] if ids else None
            release.first_track_primary_artist_name = first_artist_name(raw_track)
        artist_cache[cache_key] = [asdict(candidate) for candidate in releases]
        save_cache(cache_path, cache)
    return releases


def playlist_membership(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> PlaylistMembership:
    """Load one queue once and index its tracks and primary artists."""
    membership = PlaylistMembership(
        primary_artist_ids=set(),
        track_ids=set(),
        track_uris_by_primary_artist={},
    )
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp._get,
                f"playlists/{playlist_id}/items",
                limit=PLAYLIST_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading queue playlist {playlist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise ArtistReviewError(
                f"Spotify returned invalid playlist data for {playlist_id}."
            )
        raw_items = response["items"]
        for raw_entry in raw_items:
            if not isinstance(raw_entry, dict):
                continue
            raw_track = raw_entry.get("item") or raw_entry.get("track")
            if not isinstance(raw_track, dict):
                continue
            track_id = str(raw_track.get("id") or "").strip()
            if track_id:
                membership.track_ids.add(track_id)
            ids = artist_ids(raw_track)
            if ids:
                membership.primary_artist_ids.add(ids[0])
                track_uri = str(raw_track.get("uri") or "").strip()
                if track_uri:
                    membership.track_uris_by_primary_artist.setdefault(
                        ids[0], []
                    ).append(track_uri)
        offset += len(raw_items)
        total = response.get("total")
        has_more = bool(response.get("next"))
        if isinstance(total, int):
            has_more = has_more or offset < total
        if not has_more:
            return membership
        if not raw_items:
            raise ArtistReviewError(
                f"Spotify returned an empty playlist page for {playlist_id}."
            )


def add_playlist_item(sp: Spotify, playlist_id: str, track_uri: str) -> object:
    """Add one track through Spotify's current playlist-items endpoint."""
    return sp._post(
        f"playlists/{playlist_id}/items",
        payload={"uris": [track_uri]},
    )


def remove_playlist_items(
    sp: Spotify,
    playlist_id: str,
    track_uris: list[str],
) -> object:
    """Remove specific tracks through Spotify's current playlist endpoint."""
    return sp._delete(
        f"playlists/{playlist_id}/items",
        payload={"items": [{"uri": uri} for uri in track_uris]},
    )


def remove_library_artists(sp: Spotify, artist_uris: list[str]) -> object:
    """Unfollow artists through Spotify's current generic library endpoint."""
    return sp._delete("me/library", uris=",".join(artist_uris))


def update_stats_after_unfollow(
    stats_path: Path,
    total_artists: int,
    removed_count: int,
) -> None:
    """Update the current stats period after a successful unfollow batch."""
    raw_history = load_json(stats_path, {})
    if not isinstance(raw_history, dict) or not raw_history:
        return
    history = {
        key: StatsReport.model_validate(value) for key, value in raw_history.items()
    }
    key, report = period_report(history)
    artist_stats = report.artists_stats
    previous_total = (
        artist_stats.total_followed_artists
        - artist_stats.added_artists
        + artist_stats.removed_artists
    )
    updated_artist_stats = artist_stats.model_copy(
        update={
            "total_followed_artists": total_artists,
            "removed_artists": artist_stats.removed_artists + removed_count,
            "growth": calculate_growth(total_artists, previous_total),
        }
    )
    denominator = max(1, total_artists)
    history[key] = report.model_copy(
        update={
            "artists_stats": updated_artist_stats,
            "avg_albums_per_artists": (
                report.albums_stats.total_saved_albums // denominator
            ),
            "avg_liked_tracks_per_artists": (
                report.tracks_stats.total_liked_tracks // denominator
            ),
        }
    )
    write_json_atomic(
        stats_path,
        {history_key: value.model_dump() for history_key, value in history.items()},
    )


def complete_artist(
    state: ArtistReviewState,
    counts: ReviewCounts,
    log_path: Path,
    run_id: str,
    artist: YourLibraryArtist,
    liked_count: int,
    action: str,
    **details: object,
) -> None:
    """Persist a completed artist decision and update invocation counters."""
    append_events(
        log_path,
        [
            event(
                run_id,
                "artist_completed",
                artist_id=artist.spotify_id,
                artist=artist.name,
                liked_tracks=liked_count,
                action=action,
                **details,
            )
        ],
    )
    state.completed_artist_ids.add(artist.spotify_id)
    state.pending_unfollows.pop(artist.spotify_id, None)
    state.pending_queue_moves.pop(artist.spotify_id, None)
    counts.reviewed += 1
    if action in {"auto_unfollow", "auto_unfollow_reconciled"}:
        counts.unfollowed += 1
    elif action == "queued":
        counts.queued += 1
    elif action == "queue_moved":
        counts.moved += 1
    elif action == "already_queued":
        counts.already_queued += 1
    elif action == "declined":
        counts.declined += 1
    else:
        counts.no_action += 1


def flush_pending_unfollows(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry_call: RetryCall,
    echo: Echo,
) -> list[YourLibraryArtist]:
    """Execute journaled automatic unfollows in API-sized batches."""
    if not state.pending_unfollows:
        return artists
    current_by_id = {artist.spotify_id: artist for artist in artists}
    absent_ids = [
        artist_id
        for artist_id in state.pending_unfollows
        if artist_id not in current_by_id
    ]
    for artist_id in absent_ids:
        plan = state.pending_unfollows[artist_id]
        reconciled_artist = YourLibraryArtist(
            name=str(plan.get("artist") or artist_id),
            uri=f"spotify:artist:{artist_id}",
        )
        complete_artist(
            state,
            counts,
            paths.log,
            run_id,
            reconciled_artist,
            log_int(plan.get("liked_tracks", 0)),
            "auto_unfollow_reconciled",
            reason=plan.get("reason"),
        )

    pending_ids = [
        artist_id for artist_id in state.pending_unfollows if artist_id in current_by_id
    ]
    while pending_ids:
        batch_ids = pending_ids[:UNFOLLOW_BATCH_SIZE]
        batch = [current_by_id[artist_id] for artist_id in batch_ids]
        retry_call(
            partial(remove_library_artists, sp, [artist.uri for artist in batch]),
            f"unfollowing {len(batch)} zero-liked artists",
        )
        removed_ids = set(batch_ids)
        artists = [artist for artist in artists if artist.spotify_id not in removed_ids]
        save_artists(paths.artists, artists)
        update_stats_after_unfollow(paths.stats_history, len(artists), len(batch))
        for artist in batch:
            plan = state.pending_unfollows[artist.spotify_id]
            complete_artist(
                state,
                counts,
                paths.log,
                run_id,
                artist,
                log_int(plan.get("liked_tracks", 0)),
                "auto_unfollow",
                reason=plan.get("reason"),
                ranked_tracks=plan.get("ranked_tracks", []),
            )
            echo(f"Auto-unfollowed: {artist.name}")
        pending_ids = pending_ids[UNFOLLOW_BATCH_SIZE:]
    return artists


def flush_pending_queue_moves(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry_call: RetryCall,
    get_membership: Callable[[str], PlaylistMembership],
    echo: Echo,
) -> None:
    """Finish journaled queue-one to queue-two moves idempotently."""
    artists_by_id = {artist.spotify_id: artist for artist in artists}
    for artist_id, plan in list(state.pending_queue_moves.items()):
        source_playlist_id = str(plan.get("source_playlist_id") or "").strip()
        target_playlist_id = str(plan.get("target_playlist_id") or "").strip()
        selected_track_id = str(plan.get("selected_track_id") or "").strip()
        selected_track_uri = str(plan.get("selected_track_uri") or "").strip()
        raw_source_uris = plan.get("source_track_uris")
        source_track_uris = (
            [str(uri) for uri in raw_source_uris if str(uri).strip()]
            if isinstance(raw_source_uris, list)
            else []
        )
        if not all(
            (
                source_playlist_id,
                target_playlist_id,
                selected_track_id,
                selected_track_uri,
                source_track_uris,
            )
        ):
            raise ArtistReviewError(
                f"Incomplete pending queue move for artist {artist_id}."
            )

        item = artists_by_id.get(artist_id) or YourLibraryArtist(
            name=str(plan.get("artist") or artist_id),
            uri=f"spotify:artist:{artist_id}",
        )
        target = get_membership(target_playlist_id)
        if artist_id not in target.primary_artist_ids:
            retry_call(
                partial(
                    add_playlist_item,
                    sp,
                    target_playlist_id,
                    selected_track_uri,
                ),
                f"adding {item.name} to queue playlist {target_playlist_id}",
            )
            target.primary_artist_ids.add(artist_id)
            target.track_ids.add(selected_track_id)
            target.track_uris_by_primary_artist.setdefault(artist_id, []).append(
                selected_track_uri
            )

        source = get_membership(source_playlist_id)
        current_source_uris = set(
            source.track_uris_by_primary_artist.get(artist_id, [])
        )
        uris_to_remove = [
            uri for uri in source_track_uris if uri in current_source_uris
        ]
        for start in range(0, len(uris_to_remove), PLAYLIST_MUTATION_BATCH_SIZE):
            batch = uris_to_remove[start : start + PLAYLIST_MUTATION_BATCH_SIZE]
            retry_call(
                partial(remove_playlist_items, sp, source_playlist_id, batch),
                f"removing {item.name} from queue playlist {source_playlist_id}",
            )
        remaining_uris = [
            uri
            for uri in source.track_uris_by_primary_artist.get(artist_id, [])
            if uri not in set(uris_to_remove)
        ]
        if remaining_uris:
            source.track_uris_by_primary_artist[artist_id] = remaining_uris
        else:
            source.track_uris_by_primary_artist.pop(artist_id, None)
            source.primary_artist_ids.discard(artist_id)

        complete_artist(
            state,
            counts,
            paths.log,
            run_id,
            item,
            log_int(plan.get("liked_tracks", 0)),
            "queue_moved",
            source_playlist_id=source_playlist_id,
            playlist_id=target_playlist_id,
            removed_track_uris=uris_to_remove,
            selected_track={
                "spotify_id": selected_track_id,
                "uri": selected_track_uri,
                "name": plan.get("selected_track_name"),
            },
            release=plan.get("release"),
        )
        echo(f"Moved: {item.name} from queue 1 to queue 2")


def ambiguous_track_choices(
    candidates: list[TrackCandidate],
) -> list[TrackCandidate]:
    """Return tied or duplicate-name best tracks that need a user choice."""
    if not candidates:
        return []
    if all(candidate.popularity is not None for candidate in candidates):
        top_popularity = max(candidate.popularity or 0 for candidate in candidates)
        tied = [
            candidate
            for candidate in candidates
            if candidate.popularity == top_popularity
        ]
        if len(tied) > 1:
            return tied
    top_name = normalize_name(candidates[0].name)
    same_name = [
        candidate
        for candidate in candidates
        if normalize_name(candidate.name) == top_name
    ]
    return same_name if len(same_name) > 1 else [candidates[0]]


def summary_from_counts(
    total: int,
    counts: ReviewCounts,
    paused: bool,
) -> ArtistReviewSummary:
    """Freeze invocation counters into a public summary."""
    return ArtistReviewSummary(
        total_pending_at_start=total,
        reviewed=counts.reviewed,
        unfollowed=counts.unfollowed,
        queued=counts.queued,
        moved=counts.moved,
        already_queued=counts.already_queued,
        declined=counts.declined,
        no_action=counts.no_action,
        skipped=counts.skipped,
        paused=paused,
    )


def review_artists(
    sp: Spotify,
    playlists: QueuePlaylists,
    track_choice_reader: TrackChoiceReader | None = None,
    release_choice_reader: ReleaseChoiceReader | None = None,
    paths: ArtistReviewPaths = DEFAULT_PATHS,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    refresh_cache: bool = False,
    limit: int | None = None,
    sleep: Sleep = default_sleep,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
) -> ArtistReviewSummary:
    """Review followed artists using local counts and targeted Spotify calls."""
    artists = load_models(paths.artists, YourLibraryArtist)
    liked_tracks = load_models(paths.liked_tracks, YourLibraryTrack)
    liked_counts = Counter(normalize_name(track.artist) for track in liked_tracks)
    liked_track_ids = {track.spotify_id for track in liked_tracks}
    state = load_review_state(paths.log)
    cache = load_cache(paths.cache, refresh=refresh_cache)
    run_id = new_run_id()
    counts = ReviewCounts()

    def retry_call(operation: Callable[[], object], description: str) -> object:
        return retry_spotify_server_errors(
            operation,
            description,
            echo,
            sleep,
            transient_retry_delay_seconds,
            transient_max_attempts,
        )

    append_events(
        paths.log,
        [
            event(
                run_id,
                "review_started",
                artists=len(artists),
                liked_tracks=len(liked_tracks),
                pending_unfollows=len(state.pending_unfollows),
                pending_queue_moves=len(state.pending_queue_moves),
            )
        ],
    )
    artists = flush_pending_unfollows(
        sp,
        artists,
        state,
        counts,
        paths,
        run_id,
        retry_call,
        echo,
    )
    playlist_cache: dict[str, PlaylistMembership] = {}

    def get_membership(playlist_id: str) -> PlaylistMembership:
        if playlist_id not in playlist_cache:
            playlist_cache[playlist_id] = playlist_membership(
                sp,
                playlist_id,
                retry_call,
            )
        return playlist_cache[playlist_id]

    flush_pending_queue_moves(
        sp,
        artists,
        state,
        counts,
        paths,
        run_id,
        retry_call,
        get_membership,
        echo,
    )
    pending_artists = [
        artist
        for artist in artists
        if artist.spotify_id not in state.completed_artist_ids
    ]
    if limit is not None:
        pending_artists = pending_artists[:limit]
    total = len(pending_artists)
    summary_total = counts.reviewed + total

    def queue_placement(
        artist_id: str,
        liked_count: int,
    ) -> tuple[str, str | None, bool]:
        """Return target, optional move source, and whether work is complete."""
        check_order = (
            (playlists.queue_1, playlists.queue_2, playlists.queue_3)
            if liked_count <= 5
            else (playlists.queue_2, playlists.queue_3, playlists.queue_1)
        )
        for existing_playlist_id in check_order:
            existing = get_membership(existing_playlist_id)
            if artist_id not in existing.primary_artist_ids:
                continue
            if existing_playlist_id == playlists.queue_1 and liked_count >= 6:
                return playlists.queue_2, playlists.queue_1, False
            return existing_playlist_id, None, True
        return playlists.for_liked_count(liked_count), None, False

    def pause_review() -> ArtistReviewSummary:
        nonlocal artists
        artists = flush_pending_unfollows(
            sp,
            artists,
            state,
            counts,
            paths,
            run_id,
            retry_call,
            echo,
        )
        flush_pending_queue_moves(
            sp,
            artists,
            state,
            counts,
            paths,
            run_id,
            retry_call,
            get_membership,
            echo,
        )
        append_events(paths.log, [event(run_id, "review_paused")])
        return summary_from_counts(summary_total, counts, paused=True)

    for position, artist in enumerate(pending_artists, start=1):
        liked_count = liked_counts[normalize_name(artist.name)]
        if progress_callback is not None:
            progress_callback(position - 1, total, artist.name)
        echo(
            f"[{position}/{total}] {artist.name}: "
            f"{liked_count} liked track{'s' if liked_count != 1 else ''}"
        )

        if liked_count == 0:
            tracks = ranked_artist_tracks(
                sp,
                artist,
                cache,
                paths.cache,
                retry_call,
            )
            top_five = tracks[:5]
            has_primary_track = any(
                track.primary_artist_id == artist.spotify_id for track in top_five
            )
            if top_five and has_primary_track:
                complete_artist(
                    state,
                    counts,
                    paths.log,
                    run_id,
                    artist,
                    liked_count,
                    "kept_primary_top_track",
                    ranked_tracks=[asdict(track) for track in top_five],
                )
                echo(f"Kept: {artist.name} has a primary-credited ranked track")
            else:
                reason = "no_ranked_tracks" if not top_five else "no_primary_top_track"
                plan = event(
                    run_id,
                    "unfollow_planned",
                    artist_id=artist.spotify_id,
                    artist=artist.name,
                    liked_tracks=liked_count,
                    reason=reason,
                    ranked_tracks=[asdict(track) for track in top_five],
                )
                append_events(paths.log, [plan])
                state.pending_unfollows[artist.spotify_id] = plan
                echo(f"Planned automatic unfollow: {artist.name} ({reason})")
                if len(state.pending_unfollows) >= UNFOLLOW_BATCH_SIZE:
                    artists = flush_pending_unfollows(
                        sp,
                        artists,
                        state,
                        counts,
                        paths,
                        run_id,
                        retry_call,
                        echo,
                    )
            continue

        playlist_id, source_playlist_id, already_queued = queue_placement(
            artist.spotify_id,
            liked_count,
        )
        membership = get_membership(playlist_id)
        if already_queued:
            complete_artist(
                state,
                counts,
                paths.log,
                run_id,
                artist,
                liked_count,
                "already_queued",
                playlist_id=playlist_id,
                expected_playlist_id=playlists.for_liked_count(liked_count),
                placement="retained_existing_tier",
            )
            echo(f"Already queued: {artist.name}")
            continue

        if playlist_id == playlists.queue_1:
            tracks = ranked_artist_tracks(
                sp,
                artist,
                cache,
                paths.cache,
                retry_call,
            )
            eligible_tracks = [
                track
                for track in tracks
                if track.primary_artist_id == artist.spotify_id
                and track.spotify_id not in liked_track_ids
            ]
            choices = ambiguous_track_choices(eligible_tracks)
            if not choices:
                complete_artist(
                    state,
                    counts,
                    paths.log,
                    run_id,
                    artist,
                    liked_count,
                    "no_unliked_primary_track",
                )
                echo(f"No unliked primary-credited ranked track: {artist.name}")
                continue
            if len(choices) == 1:
                selected_track = choices[0]
            else:
                choice = (
                    track_choice_reader(artist, tuple(choices))
                    if track_choice_reader is not None
                    else choices[0].spotify_id
                )
                if choice == CHOICE_QUIT:
                    return pause_review()
                if choice == CHOICE_SKIP:
                    counts.skipped += 1
                    append_events(
                        paths.log,
                        [
                            event(
                                run_id,
                                "artist_skipped_run",
                                artist_id=artist.spotify_id,
                                artist=artist.name,
                                liked_tracks=liked_count,
                            )
                        ],
                    )
                    continue
                selected_choice = next(
                    (track for track in choices if track.spotify_id == choice),
                    None,
                )
                if selected_choice is None:
                    raise InvalidReviewChoiceError(
                        f"Unknown track choice for {artist.name}: {choice}"
                    )
                selected_track = selected_choice
            retry_call(
                partial(add_playlist_item, sp, playlist_id, selected_track.uri),
                f"adding {selected_track.name} to queue playlist",
            )
            membership.track_ids.add(selected_track.spotify_id)
            membership.primary_artist_ids.add(artist.spotify_id)
            membership.track_uris_by_primary_artist.setdefault(
                artist.spotify_id, []
            ).append(selected_track.uri)
            complete_artist(
                state,
                counts,
                paths.log,
                run_id,
                artist,
                liked_count,
                "queued",
                playlist_id=playlist_id,
                track=asdict(selected_track),
                selection="automatic" if len(choices) == 1 else "prompted",
            )
            echo(f"Queued: {artist.name} - {selected_track.name}")
            continue

        allow_decline = playlist_id == playlists.queue_3
        releases = (
            earliest_artist_releases(
                sp,
                artist,
                cache,
                paths.cache,
                retry_call,
            )
            if allow_decline
            else ranked_artist_releases(
                sp,
                artist,
                cache,
                paths.cache,
                retry_call,
            )
        )
        eligible_releases = [
            release
            for release in releases
            if release.is_eligible_for(artist.spotify_id)
        ]
        if not eligible_releases:
            complete_artist(
                state,
                counts,
                paths.log,
                run_id,
                artist,
                liked_count,
                "no_eligible_release",
                releases=[asdict(release) for release in releases],
            )
            echo(f"No eligible first-track release: {artist.name}")
            continue

        choice = (
            release_choice_reader(artist, tuple(releases), allow_decline)
            if release_choice_reader is not None
            else eligible_releases[0].spotify_id
        )
        if choice == CHOICE_QUIT:
            return pause_review()
        if choice == CHOICE_SKIP:
            counts.skipped += 1
            append_events(
                paths.log,
                [
                    event(
                        run_id,
                        "artist_skipped_run",
                        artist_id=artist.spotify_id,
                        artist=artist.name,
                        liked_tracks=liked_count,
                    )
                ],
            )
            continue
        if choice == CHOICE_DECLINE:
            if not allow_decline:
                raise InvalidReviewChoiceError(
                    f"Decline is not available for {artist.name}."
                )
            complete_artist(
                state,
                counts,
                paths.log,
                run_id,
                artist,
                liked_count,
                "declined",
                releases=[asdict(release) for release in releases],
            )
            echo(f"Declined queue addition: {artist.name}")
            continue
        selected_release = next(
            (release for release in eligible_releases if release.spotify_id == choice),
            None,
        )
        if selected_release is None or not selected_release.first_track_uri:
            raise InvalidReviewChoiceError(
                f"Unknown or ineligible release choice for {artist.name}: {choice}"
            )
        if source_playlist_id is not None:
            source_membership = get_membership(source_playlist_id)
            source_track_uris = list(
                source_membership.track_uris_by_primary_artist.get(
                    artist.spotify_id, []
                )
            )
            if not source_track_uris:
                raise ArtistReviewError(
                    f"Cannot safely move {artist.name}: its queue-1 track URI "
                    "was not returned by Spotify."
                )
            if not selected_release.first_track_id:
                raise ArtistReviewError(
                    f"Cannot safely move {artist.name}: the selected track has no ID."
                )
            plan = event(
                run_id,
                "queue_move_planned",
                artist_id=artist.spotify_id,
                artist=artist.name,
                liked_tracks=liked_count,
                source_playlist_id=source_playlist_id,
                target_playlist_id=playlist_id,
                source_track_uris=source_track_uris,
                selected_track_id=selected_release.first_track_id,
                selected_track_uri=selected_release.first_track_uri,
                selected_track_name=selected_release.first_track_name,
                release=asdict(selected_release),
            )
            append_events(paths.log, [plan])
            state.pending_queue_moves[artist.spotify_id] = plan
            flush_pending_queue_moves(
                sp,
                artists,
                state,
                counts,
                paths,
                run_id,
                retry_call,
                get_membership,
                echo,
            )
            continue

        retry_call(
            partial(
                add_playlist_item,
                sp,
                playlist_id,
                selected_release.first_track_uri,
            ),
            f"adding {selected_release.first_track_name} to queue playlist",
        )
        if selected_release.first_track_id:
            membership.track_ids.add(selected_release.first_track_id)
        membership.primary_artist_ids.add(artist.spotify_id)
        membership.track_uris_by_primary_artist.setdefault(
            artist.spotify_id, []
        ).append(selected_release.first_track_uri)
        complete_artist(
            state,
            counts,
            paths.log,
            run_id,
            artist,
            liked_count,
            "queued",
            playlist_id=playlist_id,
            release=asdict(selected_release),
            selection="prompted",
        )
        echo(
            f"Queued: {artist.name} - {selected_release.first_track_name} "
            f"({selected_release.name})"
        )

    artists = flush_pending_unfollows(
        sp,
        artists,
        state,
        counts,
        paths,
        run_id,
        retry_call,
        echo,
    )
    flush_pending_queue_moves(
        sp,
        artists,
        state,
        counts,
        paths,
        run_id,
        retry_call,
        get_membership,
        echo,
    )
    if progress_callback is not None:
        progress_callback(total, total, "Complete")
    append_events(
        paths.log,
        [
            event(
                run_id,
                "review_completed",
                summary=asdict(summary_from_counts(summary_total, counts, False)),
            )
        ],
    )
    return summary_from_counts(summary_total, counts, paused=False)


__all__ = [
    "ArtistReviewConfigError",
    "ArtistReviewError",
    "ArtistReviewPaths",
    "ArtistReviewSummary",
    "CHOICE_DECLINE",
    "CHOICE_QUIT",
    "CHOICE_SKIP",
    "DEFAULT_PATHS",
    "InvalidReviewChoiceError",
    "QueuePlaylists",
    "ReleaseCandidate",
    "SpotifyRateLimitError",
    "SpotifyTransientServerError",
    "TrackCandidate",
    "review_artists",
]
