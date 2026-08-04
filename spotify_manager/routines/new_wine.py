"""Advance the New Wine from Old Bottles playlist safely by release."""

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import cast

from spotipy import Spotify

# UFI
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.processors.library_lookups import required_liked_tracks
from spotify_manager.routines.review_album_limits import append_removed_album_log


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "new_wine_flush_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "new_wine_flush_log.jsonl"
DEFAULT_ALBUMS_PATH = FILES_DIR / "albums_total_new.json"
DEFAULT_LIKED_TRACKS_PATH = FILES_DIR / "liked_tracks_total.json"
DEFAULT_REMOVED_ALBUMS_LOG_PATH = FILES_DIR / "removed_albums_log.jsonl"
PLAYLIST_PAGE_LIMIT = 50
ARTIST_RELEASE_PAGE_LIMIT = 10
LIKED_TRACK_BATCH_SIZE = 10
STATE_VERSION = 1
NEW_WINE_TARGET_SIZE = 10
NO_DISCOVERY_MIN_LIKED_TRACKS = 18
NO_DISCOVERY_MIN_SAVED_ALBUMS = 3
CHOICE_SKIP = "skip"
CHOICE_QUIT = "quit"
CHOICE_DROP = "drop"
CHOICE_FINISH = "finish"

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
ReleaseChoiceReader = Callable[["PlaylistTrack", tuple["ReleaseCandidate", ...]], str]
FlushAction = Literal[
    "advance",
    "drop",
    "sauvignon",
    "complete single",
    "skip",
]


class NewWineError(RuntimeError):
    """Base error for the New Wine flush."""


class NewWineConfigError(NewWineError):
    """Raised when a playlist setting or option is invalid."""


class NewWineStateError(NewWineError):
    """Raised when restart state cannot be read or written safely."""


@dataclass(frozen=True)
class ReleaseTrack:
    """One ordered track in a Spotify release."""

    spotify_id: str
    uri: str
    name: str
    disc_number: int
    track_number: int


@dataclass(frozen=True)
class ReleaseCandidate:
    """A current-year release available for interactive selection."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str


@dataclass(frozen=True)
class PlaylistTrack:
    """One source entry from New Wine at the start of a flush."""

    spotify_id: str
    uri: str
    name: str
    primary_artist_id: str
    primary_artist_name: str
    release: ReleaseCandidate


@dataclass(frozen=True)
class FlushResult:
    """One source track's planned or completed outcome."""

    source_track: str
    artist: str
    release: str
    release_type: str
    current_liked: bool
    consecutive_unliked: int
    action: FlushAction
    target_track: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    album_unsaved: bool = False
    advance_reason: str | None = None
    drop_reason: str | None = None
    continuation_release: str | None = None
    continuation_track: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class CellarRefillResult:
    """One Wine Cellar entry considered during the post-flush refill."""

    source_track: str
    artist: str
    action: Literal["moved", "already present", "ineligible"]
    liked_tracks: int | None = None
    saved_albums: int | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class CellarRefillSummary:
    """Outcome of filling available New Wine slots from Wine Cellar."""

    target_size: int
    before: int
    after: int
    added: int
    removed_from_cellar: int
    ineligible: int
    no_discovery: bool
    results: tuple[CellarRefillResult, ...]


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one New Wine invocation."""

    run_id: str
    total: int
    processed: int
    advanced: int
    dropped: int
    sent_to_sauvignon: int
    completed_singles: int
    skipped: int
    albums_unsaved: int
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]
    refill: CellarRefillSummary | None = None


def parse_playlist_id(reference: str | None, setting_name: str) -> str:
    """Extract a Spotify playlist id from a URL, URI, or bare id."""
    if not reference or not reference.strip():
        raise NewWineConfigError(f"{setting_name} is not configured.")
    value = reference.strip()
    for pattern in (
        r"^spotify:playlist:(?P<id>[A-Za-z0-9]+)$",
        r"open\.spotify\.com/playlist/(?P<id>[A-Za-z0-9]+)",
        r"^(?P<id>[A-Za-z0-9]+)$",
    ):
        match = re.search(pattern, value)
        if match:
            return match.group("id")
    raise NewWineConfigError(f"Invalid {setting_name} playlist reference.")


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Return nonempty Spotify artist ids and names in credit order."""
    if not isinstance(raw, list):
        return ()
    artists: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if spotify_id:
            artists.append((spotify_id, name or spotify_id))
    return tuple(artists)


def classify_release(raw_type: object, total_tracks: int) -> str:
    """Classify Spotify releases while distinguishing EPs from singles."""
    release_type = str(raw_type or "unknown").casefold()
    if release_type == "album":
        return "Album"
    if release_type == "compilation":
        return "Compilation"
    if release_type == "ep":
        return "EP"
    if release_type == "single":
        return "EP" if total_tracks >= 4 else "Single"
    return release_type.title() or "Unknown"


def _track_position(raw: object, fallback: int) -> int:
    """Parse Spotify's one-based disc/track position defensively."""
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if isinstance(raw, str):
        try:
            parsed = int(raw.strip())
        except ValueError:
            pass
        else:
            if parsed > 0:
                return parsed
    return fallback


def _release_candidate(
    raw: object,
    *,
    target_artist_id: str | None = None,
) -> ReleaseCandidate | None:
    """Parse one Spotify release, requiring the target artist to be first."""
    if not isinstance(raw, dict):
        return None
    artists = _artist_pairs(raw.get("artists"))
    if not artists:
        return None
    if target_artist_id is not None and artists[0][0] != target_artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not spotify_id or not uri:
        return None
    raw_total = raw.get("total_tracks")
    total_tracks = raw_total if isinstance(raw_total, int) else 0
    return ReleaseCandidate(
        spotify_id=spotify_id,
        uri=uri,
        name=str(raw.get("name") or spotify_id),
        release_type=classify_release(raw.get("album_type"), total_tracks),
        release_date=str(raw.get("release_date") or "Unknown"),
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
    )


def _playlist_track(raw_entry: object) -> PlaylistTrack | None:
    """Parse one playable playlist item."""
    if not isinstance(raw_entry, dict):
        return None
    raw_track = raw_entry.get("item") or raw_entry.get("track")
    if not isinstance(raw_track, dict):
        return None
    spotify_id = str(raw_track.get("id") or "").strip()
    uri = str(raw_track.get("uri") or "").strip()
    artists = _artist_pairs(raw_track.get("artists"))
    release = _release_candidate(raw_track.get("album"))
    if not spotify_id or not uri or not artists or release is None:
        return None
    return PlaylistTrack(
        spotify_id=spotify_id,
        uri=uri,
        name=str(raw_track.get("name") or spotify_id),
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        release=release,
    )


def load_playlist_tracks(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> tuple[PlaylistTrack, ...]:
    """Load every playable item in playlist order."""
    tracks: list[PlaylistTrack] = []
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp._get,
                f"playlists/{playlist_id}/items",
                limit=PLAYLIST_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading playlist {playlist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise NewWineError("Spotify returned invalid playlist data.")
        raw_items = response["items"]
        tracks.extend(
            track
            for raw_item in raw_items
            if (track := _playlist_track(raw_item)) is not None
        )
        offset += len(raw_items)
        total = response.get("total")
        has_more = bool(response.get("next"))
        if isinstance(total, int):
            has_more = has_more or offset < total
        if not has_more:
            return tuple(tracks)
        if not raw_items:
            raise NewWineError("Spotify returned an empty playlist page.")


def load_release_tracks(
    sp: Spotify,
    release: ReleaseCandidate,
    retry_call: RetryCall,
) -> tuple[ReleaseTrack, ...]:
    """Load and order a release's complete Spotify track list."""
    tracks: list[ReleaseTrack] = []
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
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise NewWineError(
                f"Spotify returned invalid track data for {release.name}."
            )
        raw_items = response["items"]
        for raw_track in raw_items:
            if not isinstance(raw_track, dict):
                continue
            spotify_id = str(raw_track.get("id") or "").strip()
            uri = str(raw_track.get("uri") or "").strip()
            if not spotify_id or not uri:
                continue
            tracks.append(
                ReleaseTrack(
                    spotify_id=spotify_id,
                    uri=uri,
                    name=str(raw_track.get("name") or spotify_id),
                    disc_number=_track_position(raw_track.get("disc_number"), 1),
                    track_number=_track_position(
                        raw_track.get("track_number"),
                        len(tracks) + 1,
                    ),
                )
            )
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewWineError(
                f"Spotify returned an empty track page for {release.name}."
            )
    return tuple(
        sorted(
            tracks,
            key=lambda track: (
                track.disc_number,
                track.track_number,
            ),
        )
    )


def current_year_releases(
    sp: Spotify,
    artist_id: str,
    year: int,
    retry_call: RetryCall,
) -> tuple[ReleaseCandidate, ...]:
    """Return current-year primary-artist albums, EPs, and singles."""
    releases: dict[str, ReleaseCandidate] = {}
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.artist_albums,
                artist_id,
                include_groups="album,single",
                limit=ARTIST_RELEASE_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading {year} releases for artist {artist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise NewWineError("Spotify returned invalid artist release data.")
        raw_items = response["items"]
        for raw_release in raw_items:
            candidate = _release_candidate(
                raw_release,
                target_artist_id=artist_id,
            )
            if (
                candidate is not None
                and candidate.release_type != "Compilation"
                and candidate.release_date.startswith(f"{year:04d}")
            ):
                releases[candidate.spotify_id] = candidate
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewWineError("Spotify returned an empty artist release page.")
    return tuple(
        sorted(
            releases.values(),
            key=lambda release: (
                release.release_date,
                release.release_type,
                release.name.casefold(),
                release.spotify_id,
            ),
        )
    )


def _track_index(
    tracks: tuple[ReleaseTrack, ...],
    source: PlaylistTrack,
) -> int | None:
    """Locate the source in a selected release by id, then normalized name."""
    for index, track in enumerate(tracks):
        if track.spotify_id == source.spotify_id:
            return index
    normalized_name = source.name.strip().casefold()
    matches = [
        index
        for index, track in enumerate(tracks)
        if track.name.strip().casefold() == normalized_name
    ]
    return matches[0] if len(matches) == 1 else None


def get_liked_statuses(
    sp: Spotify,
    track_ids: list[str],
    cache: dict[str, bool],
    retry_call: RetryCall,
) -> dict[str, bool]:
    """Fill and return live Liked Songs statuses in conservative batches."""
    missing = list(
        dict.fromkeys(track_id for track_id in track_ids if track_id not in cache)
    )
    for start in range(0, len(missing), LIKED_TRACK_BATCH_SIZE):
        batch = missing[start : start + LIKED_TRACK_BATCH_SIZE]
        response = retry_call(
            partial(sp.current_user_saved_tracks_contains, batch),
            f"checking {len(batch)} live Liked Songs statuses",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise NewWineError("Spotify returned invalid Liked Songs statuses.")
        cache.update(
            {
                track_id: bool(liked)
                for track_id, liked in zip(batch, response, strict=True)
            }
        )
    return cache


def _live_evaluation(
    release: ReleaseCandidate,
    tracks: tuple[ReleaseTrack, ...],
    liked: dict[str, bool],
) -> AlbumEvaluation:
    """Build the usual album keep decision entirely from live Spotify state."""
    liked_count = sum(liked.get(track.spotify_id, False) for track in tracks)
    total = len(tracks)
    required = required_liked_tracks(total, 0.5)
    return AlbumEvaluation(
        album_name=release.name,
        album_id=release.spotify_id,
        artist_name=release.primary_artist_name,
        total_tracks=total,
        liked_tracks=liked_count,
        required_liked_tracks=required,
        liked_ratio=liked_count / total if total else 0,
        threshold=0.5,
        decision="keep" if liked_count >= required else "remove",
        tracks=[
            AlbumTrackLikedStatus(
                name=track.name,
                uri=track.uri,
                liked=liked.get(track.spotify_id, False),
                spotify_id=track.spotify_id,
            )
            for track in tracks
        ],
        source="spotify-live",
        from_cache=False,
    )


def _default_state() -> dict[str, object]:
    """Return an empty versioned restart state."""
    return {
        "version": STATE_VERSION,
        "track_progress": {},
        "active_run": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load restart state, rejecting malformed data instead of discarding it."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewWineStateError(f"New Wine state is invalid: {path}") from exc
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("track_progress"), dict)
    ):
        raise NewWineStateError(f"New Wine state is invalid: {path}")
    return raw


def save_state(state: dict[str, object], path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist restart state atomically after each successful boundary."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewWineStateError(f"Could not save New Wine state: {path}") from exc


def append_log(
    run_id: str,
    result: FlushResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable source-track outcome."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        **asdict(result),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise NewWineStateError(f"Could not write New Wine log: {path}") from exc


def append_cellar_log(
    run_id: str,
    result: CellarRefillResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable Wine Cellar refill decision."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "event": "wine_cellar_refill",
        **asdict(result),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise NewWineStateError(f"Could not write New Wine log: {path}") from exc


def _artist_key(name: str) -> str:
    """Normalize a primary artist name for local library-count matching."""
    return name.strip().casefold()


def _load_no_discovery_inventory(
    liked_tracks_path: Path,
    albums_path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Load candidate Spotify ids by primary artist from library mirrors."""
    try:
        raw_tracks = json.loads(liked_tracks_path.read_text(encoding="utf-8"))
        raw_albums = json.loads(albums_path.read_text(encoding="utf-8"))
        if not isinstance(raw_tracks, list) or not isinstance(raw_albums, list):
            raise ValueError("library mirrors must contain JSON arrays")
        tracks = [YourLibraryTrack.model_validate(item) for item in raw_tracks]
        albums = [YourLibraryAlbum.model_validate(item) for item in raw_albums]
    except (OSError, ValueError) as exc:
        raise NewWineStateError(
            "Could not load liked-track and saved-album mirrors for --no-discovery."
        ) from exc
    track_ids: dict[str, list[str]] = {}
    album_ids: dict[str, list[str]] = {}
    for track in tracks:
        track_ids.setdefault(_artist_key(track.artist), []).append(track.spotify_id)
    for album in albums:
        album_ids.setdefault(_artist_key(album.artist), []).append(album.spotify_id)
    return (
        {
            artist: tuple(dict.fromkeys(spotify_ids))
            for artist, spotify_ids in track_ids.items()
        },
        {
            artist: tuple(dict.fromkeys(spotify_ids))
            for artist, spotify_ids in album_ids.items()
        },
    )


def _live_no_discovery_counts(
    sp: Spotify,
    artist_name: str,
    track_ids_by_artist: dict[str, tuple[str, ...]],
    album_ids_by_artist: dict[str, tuple[str, ...]],
    retry_call: RetryCall,
) -> tuple[int | None, int, bool]:
    """Check one artist's known library ids live, stopping at either threshold."""
    artist_key = _artist_key(artist_name)
    saved_albums = 0
    album_ids = album_ids_by_artist.get(artist_key, ())
    for start in range(0, len(album_ids), LIKED_TRACK_BATCH_SIZE):
        batch = list(album_ids[start : start + LIKED_TRACK_BATCH_SIZE])
        response = retry_call(
            partial(sp.current_user_saved_albums_contains, batch),
            f"checking saved albums for {artist_name}",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise NewWineError("Spotify returned invalid saved-album statuses.")
        saved_albums += sum(bool(saved) for saved in response)
        if saved_albums >= NO_DISCOVERY_MIN_SAVED_ALBUMS:
            return None, saved_albums, True

    liked_tracks = 0
    track_ids = track_ids_by_artist.get(artist_key, ())
    for start in range(0, len(track_ids), LIKED_TRACK_BATCH_SIZE):
        batch = list(track_ids[start : start + LIKED_TRACK_BATCH_SIZE])
        response = retry_call(
            partial(sp.current_user_saved_tracks_contains, batch),
            f"checking liked tracks for {artist_name}",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise NewWineError("Spotify returned invalid Liked Songs statuses.")
        liked_tracks += sum(bool(liked) for liked in response)
        if liked_tracks >= NO_DISCOVERY_MIN_LIKED_TRACKS:
            return liked_tracks, saved_albums, True
    return liked_tracks, saved_albums, False


def _new_run(
    playlist_id: str,
    tracks: tuple[PlaylistTrack, ...],
    wine_cellar_playlist_id: str | None,
    no_discovery: bool,
) -> dict[str, object]:
    """Build a durable snapshot so each original entry advances once."""
    return {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "wine_cellar_playlist_id": wine_cellar_playlist_id,
        "no_discovery": no_discovery,
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "entries": [
            {
                "source": asdict(track),
                "status": "pending",
                "plan": None,
            }
            for track in tracks
        ],
        "refill_pending": None,
    }


def _playlist_track_from_record(raw: object) -> PlaylistTrack:
    """Rebuild one snapshotted source track."""
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise NewWineStateError("New Wine run contains an invalid source track.")
    release = ReleaseCandidate(**raw["release"])
    return PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=release,
    )


def _release_from_record(raw: object) -> ReleaseCandidate:
    """Rebuild a release stored in one durable plan."""
    if not isinstance(raw, dict):
        raise NewWineStateError("New Wine run contains an invalid release plan.")
    return ReleaseCandidate(**raw)


def _track_from_record(raw: object) -> ReleaseTrack | None:
    """Rebuild an optional target track stored in one durable plan."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise NewWineStateError("New Wine run contains an invalid target track.")
    return ReleaseTrack(**raw)


def _remove_local_album(album_id: str, path: Path) -> bool:
    """Remove a live-unsaved album from albums_total_new.json when present."""
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewWineStateError(f"Could not read local albums: {path}") from exc
    if not isinstance(raw, list):
        raise NewWineStateError(f"Local albums file is invalid: {path}")
    updated = [
        item
        for item in raw
        if not (
            isinstance(item, dict)
            and str(item.get("uri") or "").split("spotify:album:")[-1] == album_id
        )
    ]
    if len(updated) == len(raw):
        return False
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(updated, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewWineStateError(f"Could not update local albums: {path}") from exc
    return True


def _add_playlist_track(
    sp: Spotify,
    playlist_id: str,
    track: ReleaseTrack,
    retry_call: RetryCall,
) -> None:
    """Add one track through Spotify's current playlist-items endpoint."""
    retry_call(
        lambda: sp._post(
            f"playlists/{playlist_id}/items",
            payload={"uris": [track.uri]},
        ),
        f"adding {track.name} to playlist {playlist_id}",
    )


def _remove_playlist_track(
    sp: Spotify,
    playlist_id: str,
    track: PlaylistTrack,
    retry_call: RetryCall,
) -> None:
    """Remove the source only after all required additions succeed."""
    retry_call(
        lambda: sp._delete(
            f"playlists/{playlist_id}/items",
            payload={"items": [{"uri": track.uri}]},
        ),
        f"removing {track.name} from playlist {playlist_id}",
    )


def _refill_new_wine(
    sp: Spotify,
    new_wine_playlist_id: str,
    wine_cellar_playlist_id: str,
    *,
    no_discovery: bool,
    dry_run: bool,
    retry_call: RetryCall,
    state: dict[str, object],
    run: dict[str, object],
    state_path: Path,
    log_path: Path,
    liked_tracks_path: Path,
    albums_path: Path,
    echo: Echo,
    projected_new_wine_ids: set[str] | None = None,
) -> CellarRefillSummary:
    """Fill New Wine from Wine Cellar with resumable add-before-remove moves."""
    raw_pending = run.get("refill_pending")
    has_pending = (
        isinstance(raw_pending, dict) and raw_pending.get("source") is not None
    )
    new_wine_tracks = (
        ()
        if projected_new_wine_ids is not None
        else load_playlist_tracks(sp, new_wine_playlist_id, retry_call)
    )
    new_wine_ids = (
        set(projected_new_wine_ids)
        if projected_new_wine_ids is not None
        else {track.spotify_id for track in new_wine_tracks}
    )
    before = len(new_wine_ids)
    if before >= NEW_WINE_TARGET_SIZE and not has_pending:
        return CellarRefillSummary(
            target_size=NEW_WINE_TARGET_SIZE,
            before=before,
            after=before,
            added=0,
            removed_from_cellar=0,
            ineligible=0,
            no_discovery=no_discovery,
            results=(),
        )

    cellar_tracks = load_playlist_tracks(sp, wine_cellar_playlist_id, retry_call)
    cellar_ids = {track.spotify_id for track in cellar_tracks}
    current_count = before
    added = 0
    removed_from_cellar = 0
    ineligible = 0
    results: list[CellarRefillResult] = []
    run_id = str(run["run_id"])

    def transfer(
        source: PlaylistTrack,
        liked_tracks: int | None,
        saved_albums: int | None,
    ) -> CellarRefillResult:
        nonlocal added, current_count, removed_from_cellar
        already_present = source.spotify_id in new_wine_ids
        present_in_cellar = source.spotify_id in cellar_ids
        if not already_present:
            if not dry_run:
                _add_playlist_track(
                    sp,
                    new_wine_playlist_id,
                    ReleaseTrack(
                        spotify_id=source.spotify_id,
                        uri=source.uri,
                        name=source.name,
                        disc_number=1,
                        track_number=1,
                    ),
                    retry_call,
                )
            new_wine_ids.add(source.spotify_id)
            current_count += 1
            added += 1
        if present_in_cellar:
            if not dry_run:
                _remove_playlist_track(
                    sp,
                    wine_cellar_playlist_id,
                    source,
                    retry_call,
                )
            cellar_ids.discard(source.spotify_id)
            removed_from_cellar += 1
        action: Literal["moved", "already present", "ineligible"] = (
            "already present" if already_present else "moved"
        )
        result = CellarRefillResult(
            source_track=source.name,
            artist=source.primary_artist_name,
            action=action,
            liked_tracks=liked_tracks,
            saved_albums=saved_albums,
            dry_run=dry_run,
        )
        verb = "Would move" if dry_run else "Moved"
        if already_present:
            verb = "Would remove duplicate" if dry_run else "Removed duplicate"
        echo(f"{verb} from Wine Cellar: {source.primary_artist_name} - {source.name}")
        return result

    if has_pending:
        assert isinstance(raw_pending, dict)
        pending_source = _playlist_track_from_record(raw_pending["source"])
        raw_liked = raw_pending.get("liked_tracks")
        raw_albums = raw_pending.get("saved_albums")
        pending_result = transfer(
            pending_source,
            raw_liked if isinstance(raw_liked, int) else None,
            raw_albums if isinstance(raw_albums, int) else None,
        )
        if not dry_run:
            run["refill_pending"] = None
            save_state(state, state_path)
        results.append(pending_result)
        append_cellar_log(run_id, pending_result, log_path)

    track_ids_by_artist: dict[str, tuple[str, ...]] = {}
    album_ids_by_artist: dict[str, tuple[str, ...]] = {}
    live_count_cache: dict[str, tuple[int | None, int, bool]] = {}
    if no_discovery and current_count < NEW_WINE_TARGET_SIZE:
        track_ids_by_artist, album_ids_by_artist = _load_no_discovery_inventory(
            liked_tracks_path,
            albums_path,
        )

    for source in cellar_tracks:
        if current_count >= NEW_WINE_TARGET_SIZE:
            break
        if source.spotify_id not in cellar_ids:
            continue
        liked_count: int | None = None
        album_count: int | None = None
        if no_discovery:
            artist_key = _artist_key(source.primary_artist_name)
            live_counts = live_count_cache.get(artist_key)
            if live_counts is None:
                live_counts = _live_no_discovery_counts(
                    sp,
                    source.primary_artist_name,
                    track_ids_by_artist,
                    album_ids_by_artist,
                    retry_call,
                )
                live_count_cache[artist_key] = live_counts
            liked_count, album_count, eligible = live_counts
            if not eligible:
                result = CellarRefillResult(
                    source_track=source.name,
                    artist=source.primary_artist_name,
                    action="ineligible",
                    liked_tracks=liked_count,
                    saved_albums=album_count,
                    dry_run=dry_run,
                )
                ineligible += 1
                results.append(result)
                append_cellar_log(run_id, result, log_path)
                continue

        if not dry_run:
            run["refill_pending"] = {
                "source": asdict(source),
                "liked_tracks": liked_count,
                "saved_albums": album_count,
            }
            save_state(state, state_path)
        result = transfer(source, liked_count, album_count)
        if not dry_run:
            run["refill_pending"] = None
            save_state(state, state_path)
        results.append(result)
        append_cellar_log(run_id, result, log_path)

    return CellarRefillSummary(
        target_size=NEW_WINE_TARGET_SIZE,
        before=before,
        after=current_count,
        added=added,
        removed_from_cellar=removed_from_cellar,
        ineligible=ineligible,
        no_discovery=no_discovery,
        results=tuple(results),
    )


def _plan_result(
    source: PlaylistTrack,
    plan: dict[str, object],
    *,
    dry_run: bool,
    album_unsaved: bool = False,
) -> FlushResult:
    """Convert a durable plan into the public result model."""
    release = _release_from_record(plan["release"])
    target = _track_from_record(plan.get("target"))
    continuation_release = (
        _release_from_record(plan["continuation_release"])
        if plan.get("continuation_release") is not None
        else None
    )
    continuation_target = _track_from_record(plan.get("continuation_target"))
    return FlushResult(
        source_track=source.name,
        artist=source.primary_artist_name,
        release=release.name,
        release_type=release.release_type,
        current_liked=bool(plan["current_liked"]),
        consecutive_unliked=cast(int, plan["consecutive_unliked"]),
        action=cast(FlushAction, str(plan["action"])),
        target_track=target.name if target is not None else None,
        album_liked_tracks=(
            cast(int, plan["album_liked_tracks"])
            if plan.get("album_liked_tracks") is not None
            else None
        ),
        album_total_tracks=(
            cast(int, plan["album_total_tracks"])
            if plan.get("album_total_tracks") is not None
            else None
        ),
        album_unsaved=album_unsaved,
        advance_reason=(
            str(plan["advance_reason"])
            if plan.get("advance_reason") is not None
            else None
        ),
        drop_reason=(
            str(plan["drop_reason"]) if plan.get("drop_reason") is not None else None
        ),
        continuation_release=(
            continuation_release.name if continuation_release is not None else None
        ),
        continuation_track=(
            continuation_target.name if continuation_target is not None else None
        ),
        dry_run=dry_run,
    )


def _drop_plan(
    release: ReleaseCandidate,
    evaluation: AlbumEvaluation,
    *,
    current_liked: bool,
    consecutive_unliked: int,
    reason: str,
) -> dict[str, object]:
    """Build a durable drop plan with its live album evaluation."""
    return {
        "action": "drop",
        "release": asdict(release),
        "target": None,
        "current_liked": current_liked,
        "consecutive_unliked": consecutive_unliked,
        "album_liked_tracks": evaluation.liked_tracks,
        "album_total_tracks": evaluation.total_tracks,
        "should_unsave": evaluation.decision == "remove",
        "evaluation": evaluation.model_dump(mode="json"),
        "album_unsaved": False,
        "drop_reason": reason,
    }


def flush_new_wine(
    sp: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    wine_cellar_playlist_id: str | None = None,
    no_discovery: bool = False,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    liked_tracks_path: Path = DEFAULT_LIKED_TRACKS_PATH,
    removed_albums_log_path: Path = DEFAULT_REMOVED_ALBUMS_LOG_PATH,
) -> FlushSummary:
    """Advance every snapshotted New Wine track exactly once."""
    retry = retry_call or (lambda operation, _description: operation())
    active_year = year or datetime.now().year
    live_tracks = load_playlist_tracks(sp, new_wine_playlist_id, retry)
    new_wine_ids = {track.spotify_id for track in live_tracks}
    sauvignon_tracks = load_playlist_tracks(sp, sauvignon_playlist_id, retry)
    sauvignon_ids = {track.spotify_id for track in sauvignon_tracks}

    resumed = False
    state = _default_state() if dry_run else load_state(state_path)
    active_run = state.get("active_run")
    if (
        not dry_run
        and isinstance(active_run, dict)
        and active_run.get("status") == "active"
        and active_run.get("playlist_id") == new_wine_playlist_id
    ):
        run = active_run
        resumed = True
    else:
        run = _new_run(
            new_wine_playlist_id,
            live_tracks,
            wine_cellar_playlist_id,
            no_discovery,
        )
        if not dry_run:
            state["active_run"] = run
            save_state(state, state_path)

    run_id = str(run["run_id"])
    raw_entries = run.get("entries")
    if not isinstance(raw_entries, list):
        raise NewWineStateError("New Wine run contains invalid entries.")
    progress_state = state.get("track_progress")
    if not isinstance(progress_state, dict):
        raise NewWineStateError("New Wine track progress is invalid.")

    liked_cache: dict[str, bool] = {}
    release_track_cache: dict[str, tuple[ReleaseTrack, ...]] = {}
    artist_release_cache: dict[str, tuple[ReleaseCandidate, ...]] = {}
    results: list[FlushResult] = []
    refill: CellarRefillSummary | None = None
    paused = False

    def release_tracks(release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        if release.spotify_id not in release_track_cache:
            release_track_cache[release.spotify_id] = load_release_tracks(
                sp,
                release,
                retry,
            )
        return release_track_cache[release.spotify_id]

    total = len(raw_entries)
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise NewWineStateError("New Wine run contains an invalid entry.")
        if raw_entry.get("status") in {"completed", "skipped"}:
            continue
        source = _playlist_track_from_record(raw_entry.get("source"))
        if progress_callback is not None:
            progress_callback(
                index - 1,
                total,
                f"{source.primary_artist_name} - {source.name}",
            )

        raw_plan = raw_entry.get("plan")
        plan = raw_plan if isinstance(raw_plan, dict) else None
        if plan is None:
            base_tracks = release_tracks(source.release)
            base_index = _track_index(base_tracks, source)
            get_liked_statuses(
                sp,
                [source.spotify_id],
                liked_cache,
                retry,
            )
            current_liked = liked_cache[source.spotify_id]
            stored_progress = progress_state.get(source.spotify_id)
            prior_streak: int | None = None
            if isinstance(stored_progress, dict):
                raw_streak = stored_progress.get("prior_unliked_streak")
                if isinstance(raw_streak, int):
                    prior_streak = raw_streak
            if prior_streak is None:
                prior_streak = 0
                if base_index is not None:
                    preceding = list(base_tracks[:base_index])
                    get_liked_statuses(
                        sp,
                        [track.spotify_id for track in preceding],
                        liked_cache,
                        retry,
                    )
                    for preceding_track in reversed(preceding):
                        if liked_cache[preceding_track.spotify_id]:
                            break
                        prior_streak += 1
            consecutive_unliked = 0 if current_liked else prior_streak + 1

            if consecutive_unliked >= 3:
                get_liked_statuses(
                    sp,
                    [track.spotify_id for track in base_tracks],
                    liked_cache,
                    retry,
                )
                next_liked_track = (
                    next(
                        (
                            track
                            for track in base_tracks[base_index + 1 :]
                            if liked_cache[track.spotify_id]
                        ),
                        None,
                    )
                    if base_index is not None
                    else None
                )
                if next_liked_track is not None:
                    plan = {
                        "action": "advance",
                        "release": asdict(source.release),
                        "target": asdict(next_liked_track),
                        "current_liked": current_liked,
                        "consecutive_unliked": consecutive_unliked,
                        "next_prior_unliked_streak": 0,
                        "album_liked_tracks": None,
                        "album_total_tracks": None,
                        "should_unsave": False,
                        "album_unsaved": False,
                        "advance_reason": "next_liked_track",
                        "drop_reason": None,
                    }
                else:
                    evaluation = _live_evaluation(
                        source.release,
                        base_tracks,
                        liked_cache,
                    )
                    plan = _drop_plan(
                        source.release,
                        evaluation,
                        current_liked=current_liked,
                        consecutive_unliked=consecutive_unliked,
                        reason="three_consecutive_unliked",
                    )
            else:
                selected_release = source.release
                if source.release.release_type == "Single":
                    candidates = artist_release_cache.get(source.primary_artist_id)
                    if candidates is None:
                        candidates = current_year_releases(
                            sp,
                            source.primary_artist_id,
                            active_year,
                            retry,
                        )
                        artist_release_cache[source.primary_artist_id] = candidates
                    if not candidates:
                        echo(
                            f"No {active_year} primary-artist releases found for "
                            f"{source.primary_artist_name}; skipping this run."
                        )
                        raw_entry["status"] = "skipped"
                        result = FlushResult(
                            source_track=source.name,
                            artist=source.primary_artist_name,
                            release=source.release.name,
                            release_type=source.release.release_type,
                            current_liked=current_liked,
                            consecutive_unliked=consecutive_unliked,
                            action="skip",
                            dry_run=dry_run,
                        )
                        results.append(result)
                        append_log(run_id, result, log_path)
                        if not dry_run:
                            save_state(state, state_path)
                        continue
                    only_current_single = (
                        len(candidates) == 1
                        and candidates[0].spotify_id == source.release.spotify_id
                        and candidates[0].release_type == "Single"
                    )
                    if only_current_single:
                        echo(
                            f"{source.release.name} is the only {active_year} "
                            f"release for {source.primary_artist_name}; "
                            "dropping it automatically."
                        )
                        choice = CHOICE_DROP
                        drop_reason = "only_current_year_single"
                    else:
                        choice = choice_reader(source, candidates)
                        drop_reason = "manual_selection"
                    if choice == CHOICE_QUIT:
                        paused = True
                        break
                    if choice == CHOICE_SKIP:
                        raw_entry["status"] = "skipped"
                        result = FlushResult(
                            source_track=source.name,
                            artist=source.primary_artist_name,
                            release=source.release.name,
                            release_type=source.release.release_type,
                            current_liked=current_liked,
                            consecutive_unliked=consecutive_unliked,
                            action="skip",
                            dry_run=dry_run,
                        )
                        results.append(result)
                        append_log(run_id, result, log_path)
                        if not dry_run:
                            save_state(state, state_path)
                        continue
                    if choice == CHOICE_DROP:
                        get_liked_statuses(
                            sp,
                            [track.spotify_id for track in base_tracks],
                            liked_cache,
                            retry,
                        )
                        evaluation = _live_evaluation(
                            source.release,
                            base_tracks,
                            liked_cache,
                        )
                        plan = _drop_plan(
                            source.release,
                            evaluation,
                            current_liked=current_liked,
                            consecutive_unliked=consecutive_unliked,
                            reason=drop_reason,
                        )
                    else:
                        selected_choice = next(
                            (
                                candidate
                                for candidate in candidates
                                if candidate.spotify_id == choice
                            ),
                            None,
                        )
                        if selected_choice is None:
                            raise NewWineError("The selected release is not available.")
                        selected_release = selected_choice

                if plan is None:
                    selected_tracks = release_tracks(selected_release)
                    if not selected_tracks:
                        echo(
                            f"{selected_release.name} has no available tracks; "
                            "skipping."
                        )
                        raw_entry["status"] = "skipped"
                        result = FlushResult(
                            source_track=source.name,
                            artist=source.primary_artist_name,
                            release=selected_release.name,
                            release_type=selected_release.release_type,
                            current_liked=current_liked,
                            consecutive_unliked=consecutive_unliked,
                            action="skip",
                            dry_run=dry_run,
                        )
                        results.append(result)
                        append_log(run_id, result, log_path)
                        if not dry_run:
                            save_state(state, state_path)
                        continue
                    selected_index = _track_index(selected_tracks, source)
                    switched_release = (
                        selected_release.spotify_id != source.release.spotify_id
                    )
                    if switched_release or selected_index is None:
                        action: FlushAction = "advance"
                        target = selected_tracks[0]
                    elif selected_index + 1 < len(selected_tracks):
                        action = "advance"
                        target = selected_tracks[selected_index + 1]
                    elif selected_release.release_type in {"Album", "EP"}:
                        action = "sauvignon"
                        target = selected_tracks[0]
                    else:
                        action = "complete single"
                        target = None
                    plan = {
                        "action": action,
                        "release": asdict(selected_release),
                        "target": asdict(target) if target is not None else None,
                        "current_liked": current_liked,
                        "consecutive_unliked": consecutive_unliked,
                        "next_prior_unliked_streak": consecutive_unliked,
                        "album_liked_tracks": None,
                        "album_total_tracks": None,
                        "should_unsave": False,
                        "album_unsaved": False,
                        "advance_reason": None,
                        "drop_reason": None,
                    }

            if str(plan["action"]) in {
                "drop",
                "sauvignon",
            } and source.release.release_type in {"Album", "EP"}:
                candidates = artist_release_cache.get(source.primary_artist_id)
                if candidates is None:
                    candidates = current_year_releases(
                        sp,
                        source.primary_artist_id,
                        active_year,
                        retry,
                    )
                    artist_release_cache[source.primary_artist_id] = candidates
                continuation_candidates = tuple(
                    candidate
                    for candidate in candidates
                    if candidate.spotify_id != source.release.spotify_id
                )
                if continuation_candidates:
                    choice = choice_reader(source, continuation_candidates)
                    if choice == CHOICE_QUIT:
                        paused = True
                        break
                    if choice == CHOICE_SKIP:
                        raw_entry["status"] = "skipped"
                        result = FlushResult(
                            source_track=source.name,
                            artist=source.primary_artist_name,
                            release=source.release.name,
                            release_type=source.release.release_type,
                            current_liked=current_liked,
                            consecutive_unliked=consecutive_unliked,
                            action="skip",
                            dry_run=dry_run,
                        )
                        results.append(result)
                        append_log(run_id, result, log_path)
                        if not dry_run:
                            save_state(state, state_path)
                        continue
                    if choice not in {CHOICE_FINISH, CHOICE_DROP}:
                        selected_continuation = next(
                            (
                                candidate
                                for candidate in continuation_candidates
                                if candidate.spotify_id == choice
                            ),
                            None,
                        )
                        if selected_continuation is None:
                            raise NewWineError("The selected release is not available.")
                        continuation_tracks = release_tracks(selected_continuation)
                        if continuation_tracks:
                            plan["continuation_release"] = asdict(selected_continuation)
                            plan["continuation_target"] = asdict(continuation_tracks[0])
                        else:
                            echo(
                                f"{selected_continuation.name} has no available "
                                "tracks; finishing without a follow-up release."
                            )

            raw_entry["plan"] = plan
            if not dry_run:
                save_state(state, state_path)

        release = _release_from_record(plan["release"])
        target = _track_from_record(plan.get("target"))
        continuation_release = (
            _release_from_record(plan["continuation_release"])
            if plan.get("continuation_release") is not None
            else None
        )
        continuation_target = _track_from_record(plan.get("continuation_target"))
        planned_action = str(plan["action"])
        album_unsaved = bool(plan.get("album_unsaved"))

        if not dry_run and source.spotify_id not in new_wine_ids:
            echo(f"Source already removed; completing saved plan for {source.name}.")
        elif planned_action == "advance" and target is not None:
            if target.spotify_id not in new_wine_ids:
                if not dry_run:
                    _add_playlist_track(
                        sp,
                        new_wine_playlist_id,
                        target,
                        retry,
                    )
                new_wine_ids.add(target.spotify_id)
                echo(f"{'Would add' if dry_run else 'Added'} next track: {target.name}")
        elif planned_action == "sauvignon" and target is not None:
            if target.spotify_id not in sauvignon_ids:
                if not dry_run:
                    _add_playlist_track(
                        sp,
                        sauvignon_playlist_id,
                        target,
                        retry,
                    )
                sauvignon_ids.add(target.spotify_id)
                echo(
                    f"{'Would add' if dry_run else 'Added'} to Sauvignon "
                    f"Terre-Neuve: {release.name}"
                )
        elif planned_action == "drop" and bool(plan.get("should_unsave")):
            evaluation = AlbumEvaluation.model_validate(plan["evaluation"])
            response = retry(
                partial(
                    sp.current_user_saved_albums_contains,
                    [release.spotify_id],
                ),
                f"checking whether {release.name} is saved",
            )
            is_saved = (
                bool(response[0]) if isinstance(response, list) and response else False
            )
            if dry_run:
                album_unsaved = is_saved
            elif not album_unsaved and is_saved:
                retry(
                    partial(
                        sp.current_user_saved_albums_delete,
                        [release.spotify_id],
                    ),
                    f"unsaving {release.name}",
                )
                _remove_local_album(release.spotify_id, albums_path)
                append_removed_album_log(
                    album=YourLibraryAlbum(
                        artist=release.primary_artist_name,
                        album=release.name,
                        uri=release.uri,
                    ),
                    evaluation=evaluation,
                    log_path=removed_albums_log_path,
                    action=f"new_wine_{plan.get('drop_reason') or 'drop'}",
                    live_liked_tracks=evaluation.liked_tracks,
                )
                album_unsaved = True
                plan["album_unsaved"] = True
                save_state(state, state_path)
            if is_saved:
                echo(
                    f"{'Would unsave' if dry_run else 'Unsave check complete for'} "
                    f"{release.name}: {evaluation.liked_tracks}/"
                    f"{evaluation.total_tracks} liked."
                )
            else:
                echo(
                    f"{release.name} is already absent from saved albums; "
                    "no library removal needed."
                )

        if (
            continuation_release is not None
            and continuation_target is not None
            and (dry_run or source.spotify_id in new_wine_ids)
        ):
            if continuation_target.spotify_id not in new_wine_ids:
                if not dry_run:
                    _add_playlist_track(
                        sp,
                        new_wine_playlist_id,
                        continuation_target,
                        retry,
                    )
                new_wine_ids.add(continuation_target.spotify_id)
                echo(
                    f"{'Would start' if dry_run else 'Started'} follow-up release: "
                    f"{continuation_release.name} - {continuation_target.name}"
                )

        if not dry_run and source.spotify_id in new_wine_ids:
            _remove_playlist_track(
                sp,
                new_wine_playlist_id,
                source,
                retry,
            )
        if source.spotify_id in new_wine_ids:
            new_wine_ids.discard(source.spotify_id)
        echo(
            f"{'Would remove' if dry_run else 'Removed'} previous track: {source.name}"
        )

        if not dry_run:
            progress_state.pop(source.spotify_id, None)
            if continuation_release is not None and continuation_target is not None:
                progress_state[continuation_target.spotify_id] = {
                    "release": asdict(continuation_release),
                    "prior_unliked_streak": 0,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            elif planned_action == "advance" and target is not None:
                progress_state[target.spotify_id] = {
                    "release": asdict(release),
                    "prior_unliked_streak": cast(
                        int,
                        plan.get(
                            "next_prior_unliked_streak",
                            plan["consecutive_unliked"],
                        ),
                    ),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            raw_entry["status"] = "completed"
            save_state(state, state_path)

        result = _plan_result(
            source,
            plan,
            dry_run=dry_run,
            album_unsaved=album_unsaved,
        )
        results.append(result)
        append_log(run_id, result, log_path)
        if progress_callback is not None:
            progress_callback(index, total, f"Completed {source.name}")

    refill_playlist_id = run.get("wine_cellar_playlist_id")
    if not isinstance(refill_playlist_id, str) or not refill_playlist_id:
        refill_playlist_id = wine_cellar_playlist_id
    refill_no_discovery = (
        bool(run["no_discovery"]) if "no_discovery" in run else no_discovery
    )
    if not paused and refill_playlist_id:
        refill = _refill_new_wine(
            sp,
            new_wine_playlist_id,
            refill_playlist_id,
            no_discovery=refill_no_discovery,
            dry_run=dry_run,
            retry_call=retry,
            state=state,
            run=run,
            state_path=state_path,
            log_path=log_path,
            liked_tracks_path=liked_tracks_path,
            albums_path=albums_path,
            echo=echo,
            projected_new_wine_ids=set(new_wine_ids) if dry_run else None,
        )

    if not dry_run and not paused:
        if all(
            isinstance(entry, dict) and entry.get("status") in {"completed", "skipped"}
            for entry in raw_entries
        ):
            run["status"] = "completed"
            run["completed_at"] = datetime.now(UTC).isoformat()
            save_state(state, state_path)

    return FlushSummary(
        run_id=run_id,
        total=total,
        processed=len(results),
        advanced=sum(result.action == "advance" for result in results),
        dropped=sum(result.action == "drop" for result in results),
        sent_to_sauvignon=sum(result.action == "sauvignon" for result in results),
        completed_singles=sum(result.action == "complete single" for result in results),
        skipped=sum(result.action == "skip" for result in results),
        albums_unsaved=sum(result.album_unsaved for result in results),
        paused=paused,
        dry_run=dry_run,
        resumed=resumed,
        results=tuple(results),
        refill=refill,
    )
