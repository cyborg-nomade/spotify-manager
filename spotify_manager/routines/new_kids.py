"""Advance artists through New Kids on the Block's four-release review."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from typing import Literal

from spotipy import Spotify

# UFI
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.core.state import RoutineState
from spotify_manager.core.state import StateService
from spotify_manager.core.state.compat import routine_state
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_wine
from spotify_manager.routines.recover_removed_albums import sync_stats_history_counts
from spotify_manager.routines.review_album_limits import REMOVED_ALBUMS_LOG_PATH
from spotify_manager.routines.review_album_limits import append_removed_album_log
from spotify_manager.routines.review_artists import add_playlist_item
from spotify_manager.routines.review_artists import remove_library_artists
from spotify_manager.routines.review_artists import remove_playlist_items
from spotify_manager.routines.slow_listening import release_identity
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "new_kids_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "new_kids_log.jsonl"
DEFAULT_QUEUE_2_LOG_PATH = FILES_DIR / "queue_2_log.jsonl"
DEFAULT_ALBUMS_PATH = FILES_DIR / "albums_total_new.json"
DEFAULT_ARTISTS_PATH = FILES_DIR / "artists_total.json"
DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH

STATE_VERSION = 1
PLAYLIST_CAP = 10
QUEUE_2_DAILY_LIMIT = 10
RELEASES_PER_ARTIST = 4
MIN_SCROBBLED_TRACKS_PER_RELEASE = 3
ARTIST_RELEASE_PAGE_SIZE = 50
ALBUM_BATCH_SIZE = 20
CONTAINS_BATCH_SIZE = 20
TRACK_BATCH_SIZE = 50
CHOICE_SKIP = "__skip__"
CHOICE_QUIT = "__quit__"

LIVE_PATTERN = re.compile(
    r"(?:\blive\b|ao vivo|en vivo|in concert|unplugged|concert)",
    re.IGNORECASE,
)
DECORATED_PATTERN = re.compile(
    r"(?:deluxe|expanded|anniversary|remaster|reissue|special edition|bonus)",
    re.IGNORECASE,
)

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
ReleaseChoiceReader = Callable[[str, tuple["RankedRelease", ...]], str]
ReleaseTier = Literal[0, 1, 2, 3]


class NewKidsError(RuntimeError):
    """Base error for the New Kids routine."""


class NewKidsConfigError(NewKidsError):
    """Raised when a required playlist is not configured."""


class NewKidsStateError(NewKidsError):
    """Raised when durable routine state is malformed or cannot be saved."""


@dataclass(frozen=True)
class RankedRelease:
    """One canonical primary-artist release ranked for discovery."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str
    popularity: int | None
    top_track_rank: int | None
    tier: ReleaseTier
    identity: str
    saved: bool
    plain: bool


@dataclass(frozen=True)
class CatalogTrack:
    """One ordered release track with its primary credit."""

    spotify_id: str
    uri: str
    name: str
    disc_number: int
    track_number: int
    primary_artist_id: str
    primary_artist_name: str
    popularity: int | None = None


@dataclass(frozen=True)
class FillResult:
    """One Queue 2 marker considered while filling New Kids."""

    artist: str
    track: str
    action: Literal["moved", "reconciled", "skipped"]


@dataclass(frozen=True)
class ArtistAssessment:
    """Live completion criteria for one artist."""

    liked_tracks: int
    saved_releases: int
    total_releases: int
    liked_primary_tracks: int
    total_primary_tracks: int
    qualifies: bool
    reasons: tuple[str, ...]
    representative_track: CatalogTrack | None
    top_liked_track: CatalogTrack | None


@dataclass(frozen=True)
class FlushResult:
    """One snapshotted New Kids track decision."""

    artist: str
    source_track: str
    source_release: str
    current_liked: bool
    consecutive_unliked: int
    action: Literal[
        "advance",
        "next release",
        "great discovery",
        "unlucky",
        "unfollowed",
        "skip",
    ]
    target_track: str | None = None
    target_release: str | None = None
    release_number: int | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    qualification_reasons: tuple[str, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Complete result of one restart-safe New Kids run."""

    results: tuple[FlushResult, ...]
    prefill: tuple[FillResult, ...]
    postfill: tuple[FillResult, ...]
    playlist_length_before: int
    playlist_length_after: int
    paused: bool
    resumed: bool
    dry_run: bool


@dataclass(frozen=True)
class Queue2Summary:
    """Complete result of one restart-safe Queue 2 run."""

    results: tuple[FlushResult, ...]
    prefill: tuple[FillResult, ...]
    queue_length_before: int
    queue_length_after: int
    new_kids_length_before: int
    new_kids_length_after: int
    paused: bool
    resumed: bool
    dry_run: bool


AnnualReleaseKey = tuple[str, str]
AnnualScrobbleIndex = dict[AnnualReleaseKey, frozenset[str]]


def parse_playlist_id(value: str | None, variable: str) -> str:
    """Parse a required Spotify playlist setting."""
    try:
        return new_wine.parse_playlist_id(value, variable)
    except new_wine.NewWineConfigError as exc:
        raise NewKidsConfigError(str(exc)) from exc


def _positive_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback


def _annual_release_key(artist: str, release: str) -> AnnualReleaseKey:
    """Return the edition-tolerant Last.fm identity for one artist release."""
    return (
        blast_from_past.normalize_name(artist),
        release_identity(release),
    )


def _scrobble_track_identity(name: str) -> str:
    """Normalize one Last.fm or Spotify track title across edition suffixes."""
    return release_identity(blast_from_past.without_sliding_qualifiers(name))


def load_annual_scrobble_index(
    path: Path = DEFAULT_SCROBBLES_PATH,
    *,
    year: int,
) -> AnnualScrobbleIndex:
    """Index distinct release tracks scrobbled in one Berlin calendar year."""
    try:
        scrobbles_by_date = blast_from_past.load_scrobbles_by_date(path)
    except blast_from_past.LastFmExportError as exc:
        raise NewKidsStateError(
            f"Could not load the {year} Last.fm scrobble history: {exc}"
        ) from exc

    indexed: dict[AnnualReleaseKey, set[str]] = defaultdict(set)
    for scrobble_date, scrobbles in scrobbles_by_date.items():
        if scrobble_date.year != year:
            continue
        for scrobble in scrobbles:
            key = _annual_release_key(scrobble.artist, scrobble.album)
            track = _scrobble_track_identity(scrobble.track)
            if all(key) and track:
                indexed[key].add(track)
    return {key: frozenset(tracks) for key, tracks in indexed.items()}


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    pairs: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or spotify_id).strip()
        if spotify_id:
            pairs.append((spotify_id, name))
    return tuple(pairs)


def _track_position(value: object, fallback: int) -> int:
    parsed = _positive_int(value)
    return parsed if parsed > 0 else fallback


def _release_type(
    raw_type: object,
    total_tracks: int,
    name: str,
) -> tuple[str, ReleaseTier]:
    normalized = str(raw_type or "").casefold()
    if normalized == "compilation":
        return "Compilation", 3
    if LIVE_PATTERN.search(name):
        return "Live", 2
    if normalized == "album":
        return "Album", 0
    if normalized == "ep" or (normalized == "single" and total_tracks >= 4):
        return "EP", 0
    return "Single", 1


def _release_date_key(value: str) -> tuple[int, int, int, str]:
    try:
        parts = [int(part) for part in value.split("-")]
    except ValueError:
        return (9999, 12, 31, value)
    return (
        parts[0] if parts else 9999,
        parts[1] if len(parts) > 1 else 12,
        parts[2] if len(parts) > 2 else 31,
        value,
    )


def _raw_release(
    raw: object,
    artist_id: str,
    saved: bool,
    top_track_rank: int | None,
) -> RankedRelease | None:
    if not isinstance(raw, dict):
        return None
    artists = _artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or spotify_id).strip()
    if not spotify_id or not uri or not name:
        return None
    total_tracks = _positive_int(raw.get("total_tracks"))
    release_type, tier = _release_type(raw.get("album_type"), total_tracks, name)
    raw_popularity = raw.get("popularity")
    popularity = raw_popularity if isinstance(raw_popularity, int) else None
    return RankedRelease(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=release_type,
        release_date=str(raw.get("release_date") or "Unknown"),
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        popularity=popularity,
        top_track_rank=top_track_rank,
        tier=tier,
        identity=release_identity(name),
        saved=saved,
        plain=not DECORATED_PATTERN.search(name),
    )


def _source_release(source: new_wine.PlaylistTrack) -> RankedRelease:
    release_type, tier = _release_type(
        source.release.release_type,
        source.release.total_tracks,
        source.release.name,
    )
    return RankedRelease(
        spotify_id=source.release.spotify_id,
        uri=source.release.uri,
        name=source.release.name,
        release_type=release_type,
        release_date=source.release.release_date,
        total_tracks=source.release.total_tracks,
        primary_artist_id=source.primary_artist_id,
        primary_artist_name=source.primary_artist_name,
        popularity=None,
        top_track_rank=None,
        tier=tier,
        identity=release_identity(source.release.name),
        saved=False,
        plain=not DECORATED_PATTERN.search(source.release.name),
    )


def _batched_contains(
    ids: list[str],
    operation: Callable[[list[str]], object],
    resource: str,
    retry_call: RetryCall,
) -> dict[str, bool]:
    statuses: dict[str, bool] = {}
    for start in range(0, len(ids), CONTAINS_BATCH_SIZE):
        batch = ids[start : start + CONTAINS_BATCH_SIZE]
        response = retry_call(
            partial(operation, batch),
            f"checking {len(batch)} {resource}",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise NewKidsError(f"Spotify returned invalid {resource} statuses.")
        statuses.update(
            {
                spotify_id: bool(status)
                for spotify_id, status in zip(batch, response, strict=True)
            }
        )
    return statuses


def load_top_track_data(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[dict[str, int], tuple[CatalogTrack, ...]]:
    """Load primary-artist Spotify top tracks and their release ranks."""
    response = retry_call(
        partial(sp.artist_top_tracks, artist_id),
        f"loading top tracks for artist {artist_id}",
    )
    raw_tracks = response.get("tracks") if isinstance(response, dict) else None
    if not isinstance(raw_tracks, list):
        raise NewKidsError("Spotify returned invalid artist top tracks.")
    album_ranks: dict[str, int] = {}
    tracks: list[CatalogTrack] = []
    for rank, raw_track in enumerate(raw_tracks, start=1):
        if not isinstance(raw_track, dict):
            continue
        artists = _artist_pairs(raw_track.get("artists"))
        raw_album = raw_track.get("album")
        if not isinstance(raw_album, dict):
            continue
        album_artists = _artist_pairs(raw_album.get("artists"))
        if (
            not artists
            or artists[0][0] != artist_id
            or not album_artists
            or album_artists[0][0] != artist_id
        ):
            continue
        track_id = str(raw_track.get("id") or "").strip()
        uri = str(raw_track.get("uri") or "").strip()
        album_id = str(raw_album.get("id") or "").strip()
        if not track_id or not uri:
            continue
        if album_id:
            album_ranks.setdefault(album_id, rank)
        raw_popularity = raw_track.get("popularity")
        tracks.append(
            CatalogTrack(
                spotify_id=track_id,
                uri=uri,
                name=str(raw_track.get("name") or track_id),
                disc_number=_track_position(raw_track.get("disc_number"), 1),
                track_number=_track_position(raw_track.get("track_number"), rank),
                primary_artist_id=artists[0][0],
                primary_artist_name=artists[0][1],
                popularity=(
                    raw_popularity if isinstance(raw_popularity, int) else None
                ),
            )
        )
    return album_ranks, tuple(tracks)


def load_ranked_catalog(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[RankedRelease, ...]:
    """Load canonical releases using album popularity and top-track fallback."""
    simplified: dict[str, dict[str, object]] = {}
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.artist_albums,
                artist_id,
                include_groups="album,single,compilation",
                limit=ARTIST_RELEASE_PAGE_SIZE,
                offset=offset,
            ),
            f"loading releases for artist {artist_id} at offset {offset}",
        )
        if not isinstance(response, dict):
            raise NewKidsError("Spotify returned invalid artist releases.")
        raw_items = response.get("items")
        if not isinstance(raw_items, list):
            raise NewKidsError("Spotify returned invalid artist releases.")
        for raw_release in raw_items:
            if not isinstance(raw_release, dict):
                continue
            artists = _artist_pairs(raw_release.get("artists"))
            release_id = str(raw_release.get("id") or "").strip()
            if artists and artists[0][0] == artist_id and release_id:
                simplified[release_id] = raw_release
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewKidsError("Spotify returned an empty release page.")

    release_ids = list(simplified)
    if not release_ids:
        return ()
    saved = _batched_contains(
        release_ids,
        sp.current_user_saved_albums_contains,
        "Saved Albums",
        retry_call,
    )
    top_ranks, _top_tracks = load_top_track_data(sp, artist_id, retry_call)

    full_by_id: dict[str, dict[str, object]] = {}
    for start in range(0, len(release_ids), ALBUM_BATCH_SIZE):
        batch = release_ids[start : start + ALBUM_BATCH_SIZE]
        response = retry_call(
            partial(sp.albums, batch),
            f"loading popularity for {len(batch)} releases",
        )
        raw_albums = response.get("albums") if isinstance(response, dict) else None
        if not isinstance(raw_albums, list):
            raise NewKidsError("Spotify returned invalid album details.")
        for raw_album in raw_albums:
            if not isinstance(raw_album, dict):
                continue
            album_id = str(raw_album.get("id") or "").strip()
            if album_id:
                full_by_id[album_id] = raw_album

    candidates: list[RankedRelease] = []
    for release_id in release_ids:
        raw = full_by_id.get(release_id, simplified[release_id])
        candidate = _raw_release(
            raw,
            artist_id,
            saved.get(release_id, False),
            top_ranks.get(release_id),
        )
        if candidate is not None:
            candidates.append(candidate)

    editions: dict[tuple[str, ReleaseTier], list[RankedRelease]] = defaultdict(list)
    for candidate in candidates:
        editions[(candidate.identity, candidate.tier)].append(candidate)

    canonical: list[RankedRelease] = []
    for group in editions.values():
        canonical.append(
            min(
                group,
                key=lambda release: (
                    not release.saved,
                    not release.plain,
                    release.tier,
                    -(release.popularity if release.popularity is not None else -1),
                    release.top_track_rank or 9999,
                    release.total_tracks,
                    _release_date_key(release.release_date),
                    release.name.casefold(),
                ),
            )
        )
    return tuple(
        sorted(
            canonical,
            key=lambda release: (
                release.tier,
                release.popularity is None,
                -(release.popularity or 0),
                release.top_track_rank or 9999,
                _release_date_key(release.release_date),
                release.name.casefold(),
                release.spotify_id,
            ),
        )
    )


def load_release_tracks(
    sp: Spotify,
    release: RankedRelease,
    retry_call: RetryCall,
) -> tuple[CatalogTrack, ...]:
    """Load an ordered release track list with primary artist credits."""
    tracks: list[CatalogTrack] = []
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.album_tracks,
                release.spotify_id,
                limit=50,
                offset=offset,
            ),
            f"loading {release.name} at offset {offset}",
        )
        if not isinstance(response, dict):
            raise NewKidsError(f"Spotify returned invalid tracks for {release.name}.")
        raw_items = response.get("items")
        if not isinstance(raw_items, list):
            raise NewKidsError(f"Spotify returned invalid tracks for {release.name}.")
        for raw_track in raw_items:
            if not isinstance(raw_track, dict):
                continue
            artists = _artist_pairs(raw_track.get("artists"))
            track_id = str(raw_track.get("id") or "").strip()
            uri = str(raw_track.get("uri") or "").strip()
            if not artists or not track_id or not uri:
                continue
            tracks.append(
                CatalogTrack(
                    spotify_id=track_id,
                    uri=uri,
                    name=str(raw_track.get("name") or track_id),
                    disc_number=_track_position(raw_track.get("disc_number"), 1),
                    track_number=_track_position(
                        raw_track.get("track_number"),
                        len(tracks) + 1,
                    ),
                    primary_artist_id=artists[0][0],
                    primary_artist_name=artists[0][1],
                )
            )
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewKidsError(f"Spotify returned an empty page for {release.name}.")
    return tuple(
        sorted(tracks, key=lambda track: (track.disc_number, track.track_number))
    )


def release_was_played_this_year(
    release: RankedRelease,
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
    annual_scrobbles: AnnualScrobbleIndex,
) -> bool:
    """Return whether current-year scrobbles satisfy the played-release rule."""
    matched_names = {
        track_name
        for track in tracks
        if (track_name := _scrobble_track_identity(track.name))
        in annual_scrobbles.get(
            _annual_release_key(track.primary_artist_name, release.name),
            frozenset(),
        )
    }
    if len(matched_names) < MIN_SCROBBLED_TRACKS_PER_RELEASE:
        return False
    liked_names = {
        _scrobble_track_identity(track.name)
        for track in tracks
        if liked.get(track.spotify_id, False)
    }
    return liked_names <= matched_names


def played_releases_from_history(
    sp: Spotify,
    catalog: tuple[RankedRelease, ...],
    annual_scrobbles: AnnualScrobbleIndex,
    retry_call: RetryCall,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
    liked_cache: dict[str, bool],
) -> tuple[RankedRelease, ...]:
    """Return catalog releases completed according to current-year Last.fm data."""
    played: list[RankedRelease] = []
    for release in catalog:
        scrobbled_names = set().union(
            *(
                names
                for (_artist, album), names in annual_scrobbles.items()
                if album == release.identity
            )
        )
        if len(scrobbled_names) < MIN_SCROBBLED_TRACKS_PER_RELEASE:
            continue
        tracks = track_cache.get(release.spotify_id)
        if tracks is None:
            tracks = load_release_tracks(sp, release, retry_call)
            track_cache[release.spotify_id] = tracks
        new_wine.get_liked_statuses(
            sp,
            [track.spotify_id for track in tracks],
            liked_cache,
            retry_call,
        )
        if release_was_played_this_year(
            release,
            tracks,
            liked_cache,
            annual_scrobbles,
        ):
            played.append(release)
    return tuple(played)


def _default_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "artists": {},
        "great_discoveries_playlists": {},
        "active_run": None,
        "queue_2_active_run": None,
    }


def validate_state(raw: object) -> dict[str, Any]:
    """Validate the New Kids namespace independently of its storage."""
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("artists"), dict)
        or not isinstance(raw.get("great_discoveries_playlists"), dict)
    ):
        raise NewKidsStateError("New Kids state is invalid.")
    return raw


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    """Load durable artist and active-run progress."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewKidsStateError(f"Could not read New Kids state: {path}") from exc
    try:
        return validate_state(raw)
    except NewKidsStateError as exc:
        raise NewKidsStateError(f"New Kids state is invalid: {path}") from exc


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically save durable artist and active-run progress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewKidsStateError(f"Could not save New Kids state: {path}") from exc


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="new_kids",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def append_event(path: Path, event: str, **details: object) -> None:
    """Append one mutation or decision to the audit log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "event": event,
        **details,
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise NewKidsStateError(f"Could not append New Kids log: {path}") from exc


def _source_from_record(raw: object) -> new_wine.PlaylistTrack:
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise NewKidsStateError("New Kids run contains an invalid source track.")
    return new_wine.PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=new_wine.ReleaseCandidate(**raw["release"]),
    )


def _release_from_record(raw: object) -> RankedRelease:
    if not isinstance(raw, dict):
        raise NewKidsStateError("New Kids plan contains an invalid release.")
    return RankedRelease(**raw)


def _track_from_record(raw: object) -> CatalogTrack | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise NewKidsStateError("New Kids plan contains an invalid track.")
    return CatalogTrack(**raw)


def _artist_progress(
    state: dict[str, object],
    source: new_wine.PlaylistTrack,
) -> dict[str, object]:
    artists = state["artists"]
    assert isinstance(artists, dict)
    raw = artists.get(source.primary_artist_id)
    if not isinstance(raw, dict):
        release = _source_release(source)
        raw = {
            "artist_name": source.primary_artist_name,
            "current_release_id": release.spotify_id,
            "prior_unliked_streak": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        artists[source.primary_artist_id] = raw
    for legacy_key in (
        "selected_release_ids",
        "selected_release_identities",
        "completed_release_ids",
    ):
        raw.pop(legacy_key, None)
    return raw


def _track_index(
    tracks: tuple[CatalogTrack, ...],
    source: new_wine.PlaylistTrack,
) -> int | None:
    for index, track in enumerate(tracks):
        if track.spotify_id == source.spotify_id:
            return index
    matches = [
        index
        for index, track in enumerate(tracks)
        if track.name.casefold() == source.name.casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def _live_evaluation(
    release: RankedRelease,
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
) -> AlbumEvaluation:
    as_new_wine = new_wine.ReleaseCandidate(
        spotify_id=release.spotify_id,
        uri=release.uri,
        name=release.name,
        release_type=release.release_type,
        release_date=release.release_date,
        total_tracks=release.total_tracks,
        primary_artist_id=release.primary_artist_id,
        primary_artist_name=release.primary_artist_name,
    )
    as_tracks = tuple(
        new_wine.ReleaseTrack(
            spotify_id=track.spotify_id,
            uri=track.uri,
            name=track.name,
            disc_number=track.disc_number,
            track_number=track.track_number,
        )
        for track in tracks
    )
    return new_wine._live_evaluation(as_new_wine, as_tracks, liked)


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewKidsStateError(f"Could not read local mirror: {path}") from exc
    if not isinstance(raw, list):
        raise NewKidsStateError(f"Local mirror is invalid: {path}")
    return raw


def _write_json_list(path: Path, values: list[object]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(values, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewKidsStateError(f"Could not update local mirror: {path}") from exc
    publish_managed_path(path, source="New Kids library reconciliation")


def _sync_local_album(
    release: RankedRelease,
    should_save: bool,
    path: Path,
) -> bool:
    raw = _read_json_list(path)
    albums = [YourLibraryAlbum.model_validate(item) for item in raw]
    present = any(album.spotify_id == release.spotify_id for album in albums)
    if present == should_save:
        return False
    if should_save:
        albums.append(
            YourLibraryAlbum(
                artist=release.primary_artist_name,
                album=release.name,
                uri=release.uri,
            )
        )
        albums.sort(key=album_sort_key)
    else:
        albums = [album for album in albums if album.spotify_id != release.spotify_id]
    _write_json_list(path, [album.model_dump(mode="json") for album in albums])
    if path == DEFAULT_ALBUMS_PATH:
        sync_stats_history_counts(total_albums=len(albums))
    return True


def remove_local_artist(artist_id: str, path: Path = DEFAULT_ARTISTS_PATH) -> bool:
    """Remove one unfollowed artist from the local mirror and update stats."""
    raw = _read_json_list(path)
    artists = [YourLibraryArtist.model_validate(item) for item in raw]
    updated = [artist for artist in artists if artist.spotify_id != artist_id]
    if len(updated) == len(artists):
        return False
    updated.sort(key=artist_sort_key)
    _write_json_list(path, [artist.model_dump(mode="json") for artist in updated])
    if path == DEFAULT_ARTISTS_PATH:
        sync_stats_history_counts(total_artists=len(updated))
    return True


def _reconcile_release_library(
    sp: Spotify,
    release: RankedRelease,
    evaluation: AlbumEvaluation,
    *,
    dry_run: bool,
    retry_call: RetryCall,
    albums_path: Path,
    removed_albums_log_path: Path,
    log_path: Path,
    echo: Echo,
) -> str:
    response = retry_call(
        partial(sp.current_user_saved_albums_contains, [release.spotify_id]),
        f"checking whether {release.name} is saved",
    )
    is_saved = bool(response[0]) if isinstance(response, list) and response else False
    should_save = evaluation.decision == "keep"
    action = "kept" if should_save else "absent"
    if should_save and not is_saved:
        action = "would save" if dry_run else "saved"
        if not dry_run:
            retry_call(
                partial(sp.current_user_saved_albums_add, [release.spotify_id]),
                f"saving {release.name}",
            )
    elif not should_save and is_saved:
        action = "would remove" if dry_run else "removed"
        if not dry_run:
            retry_call(
                partial(sp.current_user_saved_albums_delete, [release.spotify_id]),
                f"unsaving {release.name}",
            )
            append_removed_album_log(
                YourLibraryAlbum(
                    artist=release.primary_artist_name,
                    album=release.name,
                    uri=release.uri,
                ),
                evaluation,
                log_path=removed_albums_log_path,
                action="new_kids_release_boundary",
                live_liked_tracks=evaluation.liked_tracks,
            )
    if not dry_run:
        _sync_local_album(release, should_save, albums_path)
    append_event(
        log_path,
        "release_library_checked",
        artist=release.primary_artist_name,
        release=release.name,
        release_id=release.spotify_id,
        liked_tracks=evaluation.liked_tracks,
        total_tracks=evaluation.total_tracks,
        decision=evaluation.decision,
        action=action,
        dry_run=dry_run,
    )
    echo(
        f"{'Would reconcile' if dry_run else 'Reconciled'} {release.name}: "
        f"{evaluation.liked_tracks}/{evaluation.total_tracks} liked, {action}."
    )
    return action


def _catalog_track_popularities(
    sp: Spotify,
    track_ids: list[str],
    retry_call: RetryCall,
) -> dict[str, int]:
    popularities: dict[str, int] = {}
    for start in range(0, len(track_ids), TRACK_BATCH_SIZE):
        batch = track_ids[start : start + TRACK_BATCH_SIZE]
        response = retry_call(
            partial(sp.tracks, batch),
            f"loading popularity for {len(batch)} tracks",
        )
        raw_tracks = response.get("tracks") if isinstance(response, dict) else None
        if not isinstance(raw_tracks, list):
            raise NewKidsError("Spotify returned invalid track details.")
        for raw_track in raw_tracks:
            if not isinstance(raw_track, dict):
                continue
            track_id = str(raw_track.get("id") or "").strip()
            popularity = raw_track.get("popularity")
            if track_id and isinstance(popularity, int):
                popularities[track_id] = popularity
    return popularities


def assess_artist(
    sp: Spotify,
    artist_id: str,
    catalog: tuple[RankedRelease, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
) -> ArtistAssessment:
    """Evaluate all four promotion criteria against live Spotify state."""
    release_ids = [release.spotify_id for release in catalog]
    saved = _batched_contains(
        release_ids,
        sp.current_user_saved_albums_contains,
        "Saved Albums",
        retry_call,
    )
    all_tracks: dict[str, CatalogTrack] = {}
    for release in catalog:
        tracks = track_cache.get(release.spotify_id)
        if tracks is None:
            tracks = load_release_tracks(sp, release, retry_call)
            track_cache[release.spotify_id] = tracks
        for track in tracks:
            if track.primary_artist_id == artist_id:
                all_tracks.setdefault(track.spotify_id, track)

    liked = _batched_contains(
        list(all_tracks),
        sp.current_user_saved_tracks_contains,
        "Liked Songs",
        retry_call,
    )
    liked_tracks = [
        track for track_id, track in all_tracks.items() if liked.get(track_id, False)
    ]
    saved_count = sum(saved.values())
    all_releases_saved = bool(catalog) and saved_count == len(catalog)
    all_tracks_liked = bool(all_tracks) and len(liked_tracks) == len(all_tracks)
    reasons: list[str] = []
    if len(liked_tracks) >= 18:
        reasons.append("18 liked tracks")
    if saved_count >= 3:
        reasons.append("3 saved releases")
    if all_releases_saved:
        reasons.append("all releases saved")
    if all_tracks_liked:
        reasons.append("all tracks liked")

    representative: CatalogTrack | None = None
    chronological = sorted(
        catalog,
        key=lambda release: (
            release.tier != 0,
            _release_date_key(release.release_date),
            release.name.casefold(),
        ),
    )
    for release in chronological:
        tracks = track_cache.get(release.spotify_id, ())
        representative = next(
            (track for track in tracks if track.primary_artist_id == artist_id),
            None,
        )
        if representative is not None:
            break

    top_liked: CatalogTrack | None = None
    _album_ranks, top_tracks = load_top_track_data(sp, artist_id, retry_call)
    top_statuses = _batched_contains(
        [track.spotify_id for track in top_tracks],
        sp.current_user_saved_tracks_contains,
        "top Liked Songs",
        retry_call,
    )
    top_liked = next(
        (track for track in top_tracks if top_statuses.get(track.spotify_id, False)),
        None,
    )
    if top_liked is None and liked_tracks:
        popularities = _catalog_track_popularities(
            sp,
            [track.spotify_id for track in liked_tracks],
            retry_call,
        )
        top_liked = max(
            liked_tracks,
            key=lambda track: (
                popularities.get(track.spotify_id, -1),
                track.name.casefold(),
            ),
        )

    return ArtistAssessment(
        liked_tracks=len(liked_tracks),
        saved_releases=saved_count,
        total_releases=len(catalog),
        liked_primary_tracks=len(liked_tracks),
        total_primary_tracks=len(all_tracks),
        qualifies=bool(reasons),
        reasons=tuple(reasons),
        representative_track=representative,
        top_liked_track=top_liked,
    )


def _playlist_artist_ids(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> tuple[set[str], set[str]]:
    tracks = new_wine.load_playlist_tracks(sp, playlist_id, retry_call)
    return (
        {track.primary_artist_id for track in tracks},
        {track.spotify_id for track in tracks},
    )


def _great_discoveries_playlist(
    sp: Spotify,
    state: dict[str, Any],
    year: int,
    seed_2026_playlist_id: str,
    *,
    dry_run: bool,
    retry_call: RetryCall,
    state_access: RoutineState,
    echo: Echo,
) -> str | None:
    playlists = state["great_discoveries_playlists"]
    assert isinstance(playlists, dict)
    stored = playlists.get(str(year))
    if isinstance(stored, str) and stored:
        return stored
    if year == 2026:
        if not dry_run:
            playlists[str(year)] = seed_2026_playlist_id
            state_access.save(state)
        return seed_2026_playlist_id
    if dry_run:
        echo(
            f"Would create Great Discoveries {year}. Spotify's API cannot place "
            "it in a playlist folder."
        )
        return None
    profile = retry_call(sp.current_user, "loading the current Spotify profile")
    user_id = str(profile.get("id") or "") if isinstance(profile, dict) else ""
    if not user_id:
        raise NewKidsError("Spotify returned an invalid current-user profile.")
    created = retry_call(
        partial(
            sp.user_playlist_create,
            user_id,
            f"Great Discoveries {year}",
            public=False,
            description=(
                f"Artists completed through New Kids on the Block during {year}."
            ),
        ),
        f"creating Great Discoveries {year}",
    )
    playlist_id = str(created.get("id") or "") if isinstance(created, dict) else ""
    if not playlist_id:
        raise NewKidsError("Spotify did not return the created playlist id.")
    playlists[str(year)] = playlist_id
    state_access.save(state)
    echo(
        f"Created Great Discoveries {year}. Move it into the intended folder "
        "manually; Spotify's API does not expose playlist folders."
    )
    return playlist_id


def _move_queue_entries(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    current: list[new_wine.PlaylistTrack],
    *,
    dry_run: bool,
    retry_call: RetryCall,
    log_path: Path,
    echo: Echo,
    queue: list[new_wine.PlaylistTrack] | None = None,
) -> tuple[
    list[new_wine.PlaylistTrack],
    tuple[FillResult, ...],
    list[new_wine.PlaylistTrack],
]:
    queue_tracks = queue
    if queue_tracks is None:
        queue_tracks = list(
            new_wine.load_playlist_tracks(sp, queue_2_playlist_id, retry_call)
        )
    current_ids = {track.spotify_id for track in current}
    current_artists = {track.primary_artist_id for track in current}
    results: list[FillResult] = []
    remaining: list[new_wine.PlaylistTrack] = []
    for index, source in enumerate(queue_tracks):
        if len(current) >= PLAYLIST_CAP:
            remaining.extend(queue_tracks[index:])
            break
        if source.primary_artist_id in current_artists:
            if not dry_run:
                retry_call(
                    partial(
                        remove_playlist_items,
                        sp,
                        queue_2_playlist_id,
                        [source.uri],
                    ),
                    "removing reconciled Queue 2 marker for "
                    f"{source.primary_artist_name}",
                )
            results.append(
                FillResult(source.primary_artist_name, source.name, "reconciled")
            )
            continue
        if source.spotify_id not in current_ids and not dry_run:
            retry_call(
                partial(add_playlist_item, sp, new_kids_playlist_id, source.uri),
                f"adding {source.primary_artist_name} to New Kids",
            )
        if not dry_run:
            retry_call(
                partial(
                    remove_playlist_items,
                    sp,
                    queue_2_playlist_id,
                    [source.uri],
                ),
                f"removing {source.primary_artist_name} from Queue 2",
            )
        current.append(source)
        current_ids.add(source.spotify_id)
        current_artists.add(source.primary_artist_id)
        result = FillResult(source.primary_artist_name, source.name, "moved")
        results.append(result)
        append_event(
            log_path,
            "queue_2_moved",
            artist=source.primary_artist_name,
            artist_id=source.primary_artist_id,
            track=source.name,
            track_id=source.spotify_id,
            dry_run=dry_run,
        )
        echo(
            f"{'Would move' if dry_run else 'Moved'} "
            f"{source.primary_artist_name} from Queue 2 to New Kids."
        )
    return current, tuple(results), remaining


def _new_run(
    playlist_id: str,
    tracks: list[new_wine.PlaylistTrack],
) -> dict[str, object]:
    return {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "status": "active",
        "entries": [
            {"source": asdict(track), "status": "pending", "plan": None}
            for track in tracks
        ],
        "started_at": datetime.now(UTC).isoformat(),
    }


def next_release_options(
    releases: tuple[RankedRelease, ...],
) -> tuple[RankedRelease, ...]:
    """Return only the highest-priority release tier still available."""
    if not releases:
        return ()
    best_tier = min(release.tier for release in releases)
    return tuple(release for release in releases if release.tier == best_tier)


def _plan_result(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    dry_run: bool,
) -> FlushResult:
    target = _track_from_record(plan.get("target"))
    target_release = (
        _release_from_record(plan["target_release"])
        if plan.get("target_release") is not None
        else None
    )
    assessment = plan.get("assessment")
    reasons: tuple[str, ...] = ()
    if isinstance(assessment, dict) and isinstance(assessment.get("reasons"), list):
        reasons = tuple(str(reason) for reason in assessment["reasons"])
    evaluation = plan.get("evaluation")
    liked_tracks: int | None = None
    total_tracks: int | None = None
    decision: str | None = None
    if isinstance(evaluation, dict):
        liked_tracks = _positive_int(evaluation.get("liked_tracks"))
        total_tracks = _positive_int(evaluation.get("total_tracks"))
        decision = str(evaluation.get("decision") or "") or None
    return FlushResult(
        artist=source.primary_artist_name,
        source_track=source.name,
        source_release=source.release.name,
        current_liked=bool(plan.get("current_liked")),
        consecutive_unliked=_positive_int(plan.get("consecutive_unliked")),
        action=str(plan["result_action"]),  # type: ignore[arg-type]
        target_track=target.name if target else None,
        target_release=target_release.name if target_release else None,
        release_number=(_positive_int(plan.get("release_number")) or None),
        album_decision=decision,
        album_liked_tracks=liked_tracks,
        album_total_tracks=total_tracks,
        qualification_reasons=reasons,
        dry_run=dry_run,
    )


def _flush_review_playlist(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    _playlist_label: str = "New Kids",
    _active_run_key: str = "active_run",
    _blocking_active_run_key: str = "queue_2_active_run",
    _fill_from_queue: bool = True,
    _initial_tracks: list[new_wine.PlaylistTrack] | None = None,
    _live_tracks: list[new_wine.PlaylistTrack] | None = None,
) -> FlushSummary:
    """Advance one playlist snapshot using the shared four-release rules."""
    retry = retry_call or (lambda operation, _description: operation())
    active_year = year or datetime.now().year
    if progress_callback:
        progress_callback(0, 0, f"Loading {active_year} Last.fm release history")
    annual_scrobbles = load_annual_scrobble_index(
        scrobbles_path,
        year=active_year,
    )
    state_access = _state_access(state_path, state_service)
    state = _default_state() if dry_run else state_access.load()
    blocking_run = state.get(_blocking_active_run_key)
    if (
        not dry_run
        and isinstance(blocking_run, dict)
        and blocking_run.get("status") in {"active", "refilling"}
    ):
        raise NewKidsStateError(
            f"A saved {_blocking_active_run_key.replace('_', ' ')} must be "
            "resumed before starting this run."
        )
    active_run = state.get(_active_run_key)
    resumed = bool(
        not dry_run
        and isinstance(active_run, dict)
        and active_run.get("status") in {"active", "refilling"}
        and active_run.get("playlist_id") == new_kids_playlist_id
    )
    if resumed:
        run = active_run
        assert isinstance(run, dict)
        initial = (
            list(_live_tracks)
            if _live_tracks is not None
            else list(new_wine.load_playlist_tracks(sp, new_kids_playlist_id, retry))
        )
        length_before = len(initial)
        prefill: tuple[FillResult, ...] = ()
    else:
        initial = (
            list(_initial_tracks)
            if _initial_tracks is not None
            else list(new_wine.load_playlist_tracks(sp, new_kids_playlist_id, retry))
        )
        length_before = len(initial)
        prefill = ()
        if _fill_from_queue:
            initial, prefill, _remaining = _move_queue_entries(
                sp,
                new_kids_playlist_id,
                queue_2_playlist_id,
                initial,
                dry_run=dry_run,
                retry_call=retry,
                log_path=log_path,
                echo=echo,
            )
        run = _new_run(new_kids_playlist_id, initial)
        if not dry_run:
            state[_active_run_key] = run
            state_access.save(state)

    raw_entries = run.get("entries")
    if not isinstance(raw_entries, list):
        raise NewKidsStateError("New Kids active run has invalid entries.")

    live_tracks = (
        list(_live_tracks)
        if _live_tracks is not None
        else list(new_wine.load_playlist_tracks(sp, new_kids_playlist_id, retry))
    )
    live_ids = {track.spotify_id for track in live_tracks}
    catalog_cache: dict[str, tuple[RankedRelease, ...]] = {}
    track_cache: dict[str, tuple[CatalogTrack, ...]] = {}
    liked_cache: dict[str, bool] = {}
    membership_cache: dict[str, tuple[set[str], set[str]]] = {}
    results: list[FlushResult] = []
    paused = False

    def catalog_for(artist_id: str) -> tuple[RankedRelease, ...]:
        if artist_id not in catalog_cache:
            catalog_cache[artist_id] = load_ranked_catalog(sp, artist_id, retry)
        return catalog_cache[artist_id]

    def tracks_for(release: RankedRelease) -> tuple[CatalogTrack, ...]:
        if release.spotify_id not in track_cache:
            track_cache[release.spotify_id] = load_release_tracks(sp, release, retry)
        return track_cache[release.spotify_id]

    def membership(playlist_id: str) -> tuple[set[str], set[str]]:
        if playlist_id not in membership_cache:
            membership_cache[playlist_id] = _playlist_artist_ids(
                sp,
                playlist_id,
                retry,
            )
        return membership_cache[playlist_id]

    total = len(raw_entries)
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise NewKidsStateError("New Kids run contains an invalid entry.")
        if raw_entry.get("status") in {"completed", "skipped"}:
            continue
        source = _source_from_record(raw_entry.get("source"))
        if progress_callback:
            progress_callback(
                index - 1,
                total,
                f"{source.primary_artist_name} - {source.name}",
            )
        progress = _artist_progress(state, source)
        catalog = catalog_for(source.primary_artist_id)
        current_release = next(
            (
                release
                for release in catalog
                if release.spotify_id == source.release.spotify_id
            ),
            _source_release(source),
        )
        if all(release.identity != current_release.identity for release in catalog):
            catalog = (current_release, *catalog)
        current_tracks = tracks_for(current_release)
        primary_tracks = tuple(
            track
            for track in current_tracks
            if track.primary_artist_id == source.primary_artist_id
        )
        source_index = _track_index(primary_tracks, source)

        raw_plan = raw_entry.get("plan")
        plan = raw_plan if isinstance(raw_plan, dict) else None
        if plan is None:
            new_wine.get_liked_statuses(
                sp,
                [source.spotify_id],
                liked_cache,
                retry,
            )
            current_liked = liked_cache[source.spotify_id]
            raw_prior = progress.get("prior_unliked_streak")
            prior_streak = raw_prior if isinstance(raw_prior, int) else 0
            if not isinstance(raw_prior, int) and source_index is not None:
                preceding = list(primary_tracks[:source_index])
                new_wine.get_liked_statuses(
                    sp,
                    [track.spotify_id for track in preceding],
                    liked_cache,
                    retry,
                )
                for preceding_track in reversed(preceding):
                    if liked_cache[preceding_track.spotify_id]:
                        break
                    prior_streak += 1
            streak = 0 if current_liked else prior_streak + 1
            target: CatalogTrack | None = None
            advance_reason = "next track"
            if streak >= 3:
                new_wine.get_liked_statuses(
                    sp,
                    [track.spotify_id for track in primary_tracks],
                    liked_cache,
                    retry,
                )
                target = (
                    next(
                        (
                            track
                            for track in primary_tracks[source_index + 1 :]
                            if liked_cache[track.spotify_id]
                        ),
                        None,
                    )
                    if source_index is not None
                    else None
                )
                advance_reason = "next liked track"
            elif source_index is not None and source_index + 1 < len(primary_tracks):
                target = primary_tracks[source_index + 1]

            if target is not None:
                plan = {
                    "action": "advance",
                    "result_action": "advance",
                    "current_release": asdict(current_release),
                    "target_release": asdict(current_release),
                    "target": asdict(target),
                    "current_liked": current_liked,
                    "consecutive_unliked": streak,
                    "next_prior_unliked_streak": (
                        0 if advance_reason == "next liked track" else streak
                    ),
                    "advance_reason": advance_reason,
                }
            else:
                new_wine.get_liked_statuses(
                    sp,
                    [track.spotify_id for track in current_tracks],
                    liked_cache,
                    retry,
                )
                evaluation = _live_evaluation(
                    current_release,
                    current_tracks,
                    liked_cache,
                )
                played_releases = played_releases_from_history(
                    sp,
                    catalog,
                    annual_scrobbles,
                    retry,
                    track_cache,
                    liked_cache,
                )
                played_identity_set = {release.identity for release in played_releases}
                echo(
                    f"{source.primary_artist_name}: {len(played_releases)} "
                    f"release(s) completed from {active_year} Last.fm scrobbles."
                )
                append_event(
                    log_path,
                    "annual_release_progress_checked",
                    artist=source.primary_artist_name,
                    artist_id=source.primary_artist_id,
                    year=active_year,
                    played_release_ids=[
                        release.spotify_id for release in played_releases
                    ],
                    played_release_names=[release.name for release in played_releases],
                    dry_run=dry_run,
                )

                if len(played_releases) >= RELEASES_PER_ARTIST:
                    assessment = assess_artist(
                        sp,
                        source.primary_artist_id,
                        catalog,
                        retry,
                        track_cache,
                    )
                    if assessment.top_liked_track is None:
                        result_action = "unfollowed"
                    elif assessment.qualifies:
                        result_action = "great discovery"
                    elif assessment.top_liked_track is not None:
                        result_action = "unlucky"
                    else:
                        result_action = "unfollowed"
                    plan = {
                        "action": "finish",
                        "result_action": result_action,
                        "current_release": asdict(current_release),
                        "target_release": None,
                        "target": None,
                        "current_liked": current_liked,
                        "consecutive_unliked": streak,
                        "evaluation": evaluation.model_dump(mode="json"),
                        "assessment": asdict(assessment),
                    }
                else:
                    remaining = tuple(
                        release
                        for release in catalog
                        if release.identity not in played_identity_set
                        and release.identity != current_release.identity
                    )
                    viable: list[RankedRelease] = []
                    for candidate in remaining:
                        candidate_tracks = tracks_for(candidate)
                        if any(
                            track.primary_artist_id == source.primary_artist_id
                            for track in candidate_tracks
                        ):
                            viable.append(candidate)
                    options = next_release_options(tuple(viable))
                    if not options:
                        assessment = assess_artist(
                            sp,
                            source.primary_artist_id,
                            catalog,
                            retry,
                            track_cache,
                        )
                        plan = {
                            "action": "finish",
                            "result_action": (
                                "unfollowed"
                                if assessment.top_liked_track is None
                                else (
                                    "great discovery"
                                    if assessment.qualifies
                                    else "unlucky"
                                )
                            ),
                            "current_release": asdict(current_release),
                            "target_release": None,
                            "target": None,
                            "current_liked": current_liked,
                            "consecutive_unliked": streak,
                            "evaluation": evaluation.model_dump(mode="json"),
                            "assessment": asdict(assessment),
                        }
                    else:
                        displayed = options[:10]
                        choice = choice_reader(source.primary_artist_name, displayed)
                        if choice == CHOICE_QUIT:
                            paused = True
                            break
                        if choice == CHOICE_SKIP:
                            raw_entry["status"] = "skipped"
                            result = FlushResult(
                                artist=source.primary_artist_name,
                                source_track=source.name,
                                source_release=source.release.name,
                                current_liked=current_liked,
                                consecutive_unliked=streak,
                                action="skip",
                                dry_run=dry_run,
                            )
                            results.append(result)
                            append_event(
                                log_path,
                                "artist_skipped_run",
                                artist=source.primary_artist_name,
                                artist_id=source.primary_artist_id,
                                dry_run=dry_run,
                            )
                            if not dry_run:
                                state_access.save(state)
                            continue
                        selected = next(
                            (
                                release
                                for release in displayed
                                if release.spotify_id == choice
                            ),
                            None,
                        )
                        if selected is None:
                            raise NewKidsError("Selected release is not available.")
                        selected_tracks = tracks_for(selected)
                        next_track = next(
                            (
                                track
                                for track in selected_tracks
                                if track.primary_artist_id == source.primary_artist_id
                            ),
                            None,
                        )
                        if next_track is None:
                            raise NewKidsError(
                                f"{selected.name} has no primary-artist tracks."
                            )
                        plan = {
                            "action": "next_release",
                            "result_action": "next release",
                            "current_release": asdict(current_release),
                            "target_release": asdict(selected),
                            "target": asdict(next_track),
                            "current_liked": current_liked,
                            "consecutive_unliked": streak,
                            "next_prior_unliked_streak": 0,
                            "release_number": len(played_releases) + 1,
                            "evaluation": evaluation.model_dump(mode="json"),
                        }

            raw_entry["plan"] = plan
            if not dry_run:
                state_access.save(state)

        assert plan is not None
        action = str(plan["action"])
        current_release = _release_from_record(plan["current_release"])
        target_release = (
            _release_from_record(plan["target_release"])
            if plan.get("target_release") is not None
            else None
        )
        target = _track_from_record(plan.get("target"))

        if isinstance(plan.get("evaluation"), dict):
            evaluation = AlbumEvaluation.model_validate(plan["evaluation"])
            _reconcile_release_library(
                sp,
                current_release,
                evaluation,
                dry_run=dry_run,
                retry_call=retry,
                albums_path=albums_path,
                removed_albums_log_path=removed_albums_log_path,
                log_path=log_path,
                echo=echo,
            )

        if action in {"advance", "next_release"} and target is not None:
            if target.spotify_id not in live_ids:
                if not dry_run:
                    retry(
                        partial(
                            add_playlist_item,
                            sp,
                            new_kids_playlist_id,
                            target.uri,
                        ),
                        f"adding {target.name} to {_playlist_label}",
                    )
                live_ids.add(target.spotify_id)
                echo(f"{'Would add' if dry_run else 'Added'}: {target.name}")
        elif action == "finish":
            raw_assessment = plan.get("assessment")
            if not isinstance(raw_assessment, dict):
                raise NewKidsStateError("Artist completion plan lacks assessment.")
            assessment = ArtistAssessment(
                liked_tracks=_positive_int(raw_assessment.get("liked_tracks")),
                saved_releases=_positive_int(raw_assessment.get("saved_releases")),
                total_releases=_positive_int(raw_assessment.get("total_releases")),
                liked_primary_tracks=_positive_int(
                    raw_assessment.get("liked_primary_tracks")
                ),
                total_primary_tracks=_positive_int(
                    raw_assessment.get("total_primary_tracks")
                ),
                qualifies=bool(raw_assessment.get("qualifies")),
                reasons=tuple(
                    str(value) for value in raw_assessment.get("reasons", [])
                ),
                representative_track=_track_from_record(
                    raw_assessment.get("representative_track")
                ),
                top_liked_track=_track_from_record(
                    raw_assessment.get("top_liked_track")
                ),
            )
            if assessment.top_liked_track is not None and assessment.qualifies:
                if assessment.representative_track is None:
                    raise NewKidsError(
                        f"{source.primary_artist_name} qualifies for promotion, but "
                        "Spotify returned no primary-artist representative track."
                    )
                great_id = _great_discoveries_playlist(
                    sp,
                    state,
                    active_year,
                    great_discoveries_2026_playlist_id,
                    dry_run=dry_run,
                    retry_call=retry,
                    state_access=state_access,
                    echo=echo,
                )
                for playlist_id, label in (
                    (great_id, f"Great Discoveries {active_year}"),
                    (newfoundland_playlist_id, "Newfoundland"),
                ):
                    if playlist_id is None:
                        echo(
                            f"Would add {source.primary_artist_name} to {label}: "
                            f"{assessment.representative_track.name}"
                        )
                        continue
                    artist_ids, track_ids = membership(playlist_id)
                    if source.primary_artist_id not in artist_ids:
                        if not dry_run:
                            retry(
                                partial(
                                    add_playlist_item,
                                    sp,
                                    playlist_id,
                                    assessment.representative_track.uri,
                                ),
                                f"adding {source.primary_artist_name} to {label}",
                            )
                        artist_ids.add(source.primary_artist_id)
                        track_ids.add(assessment.representative_track.spotify_id)
                        echo(
                            f"{'Would add' if dry_run else 'Added'} "
                            f"{source.primary_artist_name} to {label}."
                        )
            else:
                if assessment.top_liked_track is not None:
                    artist_ids, track_ids = membership(unlucky_ones_playlist_id)
                    if source.primary_artist_id not in artist_ids:
                        if not dry_run:
                            retry(
                                partial(
                                    add_playlist_item,
                                    sp,
                                    unlucky_ones_playlist_id,
                                    assessment.top_liked_track.uri,
                                ),
                                f"adding {source.primary_artist_name} to Unlucky Ones",
                            )
                        artist_ids.add(source.primary_artist_id)
                        track_ids.add(assessment.top_liked_track.spotify_id)
                        echo(
                            f"{'Would add' if dry_run else 'Added'} "
                            f"{source.primary_artist_name} to Unlucky Ones."
                        )
                followed = retry(
                    partial(
                        sp.current_user_following_artists,
                        [source.primary_artist_id],
                    ),
                    f"checking follow status for {source.primary_artist_name}",
                )
                is_followed = (
                    bool(followed[0])
                    if isinstance(followed, list) and followed
                    else False
                )
                if is_followed:
                    if not dry_run:
                        retry(
                            partial(
                                remove_library_artists,
                                sp,
                                [f"spotify:artist:{source.primary_artist_id}"],
                            ),
                            f"unfollowing {source.primary_artist_name}",
                        )
                        remove_local_artist(source.primary_artist_id, artists_path)
                    echo(
                        f"{'Would unfollow' if dry_run else 'Unfollowed'} "
                        f"{source.primary_artist_name}."
                    )

        if source.spotify_id in live_ids:
            if not dry_run:
                retry(
                    partial(
                        remove_playlist_items,
                        sp,
                        new_kids_playlist_id,
                        [source.uri],
                    ),
                    f"removing previous {_playlist_label} track {source.name}",
                )
            live_ids.discard(source.spotify_id)
            echo(f"{'Would remove' if dry_run else 'Removed'}: {source.name}")

        if not dry_run:
            if action == "finish":
                artists = state["artists"]
                assert isinstance(artists, dict)
                artists.pop(source.primary_artist_id, None)
            else:
                if action == "next_release" and target_release is not None:
                    progress["current_release_id"] = target_release.spotify_id
                progress["prior_unliked_streak"] = _positive_int(
                    plan.get("next_prior_unliked_streak")
                )
                progress["updated_at"] = datetime.now(UTC).isoformat()
            raw_entry["status"] = "completed"
            state_access.save(state)

        result = _plan_result(source, plan, dry_run)
        results.append(result)
        append_event(
            log_path,
            "track_completed",
            run_id=run.get("run_id"),
            result=asdict(result),
        )
        if progress_callback:
            progress_callback(index, total, f"Completed {source.primary_artist_name}")

    postfill: tuple[FillResult, ...] = ()
    if not paused and _fill_from_queue:
        if not dry_run:
            run["status"] = "refilling"
            state_access.save(state)
        current_after = list(
            new_wine.load_playlist_tracks(sp, new_kids_playlist_id, retry)
        )
        current_after, postfill, _remaining = _move_queue_entries(
            sp,
            new_kids_playlist_id,
            queue_2_playlist_id,
            current_after,
            dry_run=dry_run,
            retry_call=retry,
            log_path=log_path,
            echo=echo,
        )
        if not dry_run:
            state[_active_run_key] = None
            state_access.save(state)
        length_after = len(current_after)
    elif not paused:
        if not dry_run:
            state[_active_run_key] = None
            state_access.save(state)
        length_after = len(live_ids)
    else:
        length_after = len(live_ids)

    return FlushSummary(
        results=tuple(results),
        prefill=prefill,
        postfill=postfill,
        playlist_length_before=length_before,
        playlist_length_after=length_after,
        paused=paused,
        resumed=resumed,
        dry_run=dry_run,
    )


def flush_new_kids(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
) -> FlushSummary:
    """Advance every snapshotted artist once, then refill New Kids to ten."""
    return _flush_review_playlist(
        sp,
        new_kids_playlist_id,
        queue_2_playlist_id,
        great_discoveries_2026_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
        choice_reader,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_albums_log_path=removed_albums_log_path,
        scrobbles_path=scrobbles_path,
    )


def flush_queue_2(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_QUEUE_2_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
) -> Queue2Summary:
    """Fill New Kids, then advance the first ten remaining Queue 2 artists."""
    retry = retry_call or (lambda operation, _description: operation())
    state = (
        _default_state()
        if dry_run
        else _state_access(
            state_path,
            state_service,
        ).load()
    )
    queue_run = state.get("queue_2_active_run")
    resumed = bool(
        not dry_run
        and isinstance(queue_run, dict)
        and queue_run.get("status") in {"active", "refilling"}
        and queue_run.get("playlist_id") == queue_2_playlist_id
    )

    new_kids_tracks = list(
        new_wine.load_playlist_tracks(sp, new_kids_playlist_id, retry)
    )
    new_kids_length_before = len(new_kids_tracks)
    queue_tracks = list(new_wine.load_playlist_tracks(sp, queue_2_playlist_id, retry))
    queue_length_before = len(queue_tracks)
    prefill: tuple[FillResult, ...] = ()

    if resumed:
        remaining = queue_tracks
    else:
        active_new_kids_run = state.get("active_run")
        if (
            not dry_run
            and isinstance(active_new_kids_run, dict)
            and active_new_kids_run.get("status") in {"active", "refilling"}
        ):
            raise NewKidsStateError(
                "The saved New Kids run must be resumed before Queue 2 can start."
            )
        new_kids_tracks, prefill, remaining = _move_queue_entries(
            sp,
            new_kids_playlist_id,
            queue_2_playlist_id,
            new_kids_tracks,
            dry_run=dry_run,
            retry_call=retry,
            log_path=log_path,
            echo=echo,
            queue=queue_tracks,
        )

    review_entries: list[new_wine.PlaylistTrack] = []
    seen_artist_ids: set[str] = set()
    for source in remaining:
        if source.primary_artist_id in seen_artist_ids:
            continue
        seen_artist_ids.add(source.primary_artist_id)
        review_entries.append(source)
        if len(review_entries) >= QUEUE_2_DAILY_LIMIT:
            break

    review = _flush_review_playlist(
        sp,
        queue_2_playlist_id,
        queue_2_playlist_id,
        great_discoveries_2026_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
        choice_reader,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_albums_log_path=removed_albums_log_path,
        scrobbles_path=scrobbles_path,
        _playlist_label="Queue 2",
        _active_run_key="queue_2_active_run",
        _blocking_active_run_key="active_run",
        _fill_from_queue=False,
        _initial_tracks=review_entries,
        _live_tracks=remaining,
    )

    return Queue2Summary(
        results=review.results,
        prefill=prefill,
        queue_length_before=queue_length_before,
        queue_length_after=review.playlist_length_after,
        new_kids_length_before=new_kids_length_before,
        new_kids_length_after=len(new_kids_tracks),
        paused=review.paused,
        resumed=review.resumed,
        dry_run=dry_run,
    )
