"""Advance the first two Slow Listening entries through studio discographies."""

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import cast

from spotipy import Spotify
from unidecode import unidecode

# UFI
from spotify_manager.routines import new_wine


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "slow_listening_flush_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "slow_listening_flush_log.jsonl"
ARTIST_RELEASE_PAGE_LIMIT = 10
SAVED_ALBUM_BATCH_SIZE = 20
MAX_TRACKS_PER_RUN = 2
STATE_VERSION = 1
CHOICE_ADVANCE = "advance"
CHOICE_SKIP = "skip"
CHOICE_QUIT = "quit"

EDITION_QUALIFIER = re.compile(
    r"\b(?:anniversary|bonus|collector(?:'s)?|deluxe|edition|expanded|legacy|"
    r"mono|remaster(?:ed)?|reissue|special|stereo|super deluxe)\b",
    re.IGNORECASE,
)
BRACKETED_SUFFIX = re.compile(r"\s*[\[(]([^)\]]+)[)\]]\s*$")
DASHED_SUFFIX = re.compile(r"\s+[-\N{EN DASH}\N{EM DASH}]\s+(.+?)\s*$")
TRAILING_EDITION = re.compile(
    r"\s+(?:(?:\d{2,4}(?:st|nd|rd|th)?\s+)?"
    r"(?:anniversary|deluxe|expanded|legacy|remaster(?:ed)?|reissue|special)"
    r"(?:\s+(?:edition|version))?)\s*$",
    re.IGNORECASE,
)
EP_MARKER = re.compile(r"(?:^|[\s\-[(])e\.?p\.?(?:$|[\s\-)\]])", re.IGNORECASE)
NON_STUDIO_PATTERNS = (
    re.compile(
        r"^live(?:!|$|\s+(?:at|from|in|on)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:[\[(][^)\]]*\blive\b[^)\]]*[)\]]|"
        r"\s[-\N{EN DASH}\N{EM DASH}]\s.*\blive\b.*)$",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:ao vivo|en vivo|in concert|unplugged)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:anthology|best of|collection|compilation|greatest hits|"
        r"rarities)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:cast recording|motion picture|original score|soundtrack)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:bootleg|demos?|karaoke|remix(?:es)?)\b", re.IGNORECASE),
)

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]
ReleaseOrderReader = Callable[
    [str, tuple["DiscographyRelease", ...]],
    tuple[str, ...],
]
CompletionNotifier = Callable[[new_wine.PlaylistTrack], None]
TrackActionReader = Callable[
    [
        new_wine.PlaylistTrack,
        new_wine.ReleaseTrack,
        "DiscographyRelease",
    ],
    str,
]
FlushAction = Literal["advance", "complete", "skip"]


class SlowListeningError(RuntimeError):
    """Base error for Slow Listening flushes."""


class SlowListeningConfigError(SlowListeningError):
    """Raised when the Slow Listening playlist is not configured."""


class SlowListeningStateError(SlowListeningError):
    """Raised when restart state cannot be read or written safely."""


class SlowListeningCancelledError(SlowListeningError):
    """Raised when interactive release ordering is cancelled."""


@dataclass(frozen=True)
class DiscographyRelease:
    """One selected studio album or EP edition."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    chronology_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str
    identity: str
    saved: bool
    plain: bool
    edition_rank: int


@dataclass(frozen=True)
class FlushResult:
    """One planned or completed Slow Listening transition."""

    source_track: str
    source_release: str
    artist: str
    action: FlushAction
    target_track: str | None = None
    target_release: str | None = None
    skipped_candidates: tuple[str, ...] = ()
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one Slow Listening invocation."""

    run_id: str
    total: int
    processed: int
    advanced: int
    completed_artists: int
    skipped: int
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Slow Listening playlist id."""
    try:
        return new_wine.parse_playlist_id(reference, "SLOW_LISTENING_PLAYLIST")
    except new_wine.NewWineConfigError as exc:
        raise SlowListeningConfigError(str(exc)) from exc


def _positive_int(raw: object, fallback: int = 0) -> int:
    """Parse a positive integer returned by Spotify."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw if raw > 0 else fallback
    if isinstance(raw, str):
        try:
            parsed = int(raw.strip())
        except ValueError:
            return fallback
        return parsed if parsed > 0 else fallback
    return fallback


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Return Spotify artist ids and names in credit order."""
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


def _edition_details(name: str) -> tuple[str, int]:
    """Return an edition-neutral title and its decoration penalty."""
    base = name.strip()
    penalty = 0
    while True:
        changed = False
        for pattern in (BRACKETED_SUFFIX, DASHED_SUFFIX):
            match = pattern.search(base)
            if match and EDITION_QUALIFIER.search(match.group(1)):
                base = base[: match.start()].strip()
                penalty += 1
                changed = True
                break
        if changed:
            continue
        match = TRAILING_EDITION.search(base)
        if match:
            base = base[: match.start()].strip()
            penalty += 1
            continue
        break
    return base or name.strip(), penalty


def release_identity(name: str) -> str:
    """Return a stable identity shared by plain and decorated editions."""
    base, _penalty = _edition_details(name)
    normalized = re.sub(r"[^a-z0-9]+", " ", unidecode(base).casefold())
    return " ".join(normalized.split())


def _track_identity(name: str) -> str:
    """Normalize edition suffixes when mapping tracks between releases."""
    return release_identity(name)


def _is_non_studio_title(name: str) -> bool:
    """Conservatively identify releases that are not studio albums or EPs."""
    return any(pattern.search(name) for pattern in NON_STUDIO_PATTERNS)


def _release_candidate(
    raw: object,
    artist_id: str,
) -> DiscographyRelease | None:
    """Parse one primary-artist studio album or EP candidate."""
    if not isinstance(raw, dict):
        return None
    artists = _artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or spotify_id).strip()
    if not spotify_id or not uri or not name or _is_non_studio_title(name):
        return None

    total_tracks = _positive_int(raw.get("total_tracks"))
    raw_type = str(raw.get("album_type") or "").casefold()
    if raw_type == "album":
        release_type = "Album"
    elif raw_type in {"single", "ep"} and (
        raw_type == "ep" or total_tracks >= 4 or EP_MARKER.search(name)
    ):
        release_type = "EP"
    else:
        return None

    release_date = str(raw.get("release_date") or "Unknown")
    _base, edition_rank = _edition_details(name)
    return DiscographyRelease(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=release_type,
        release_date=release_date,
        chronology_date=release_date,
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        identity=release_identity(name),
        saved=False,
        plain=edition_rank == 0,
        edition_rank=edition_rank,
    )


def _release_date_key(value: str) -> tuple[int, int, int, str]:
    """Sort partial Spotify dates chronologically, with unknown dates last."""
    if value == "Unknown":
        return (1, 9999, 12, value)
    try:
        parts = [int(part) for part in value.split("-")]
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        parsed = date(year, month, day)
    except ValueError, IndexError:
        return (1, 9999, 12, value)
    return (0, parsed.toordinal(), 0, value)


def _load_saved_statuses(
    sp: Spotify,
    releases: list[DiscographyRelease],
    retry_call: RetryCall,
) -> dict[str, bool]:
    """Read saved-album status in conservative Spotify batches."""
    statuses: dict[str, bool] = {}
    ids = [release.spotify_id for release in releases]
    for start in range(0, len(ids), SAVED_ALBUM_BATCH_SIZE):
        batch = ids[start : start + SAVED_ALBUM_BATCH_SIZE]
        response = retry_call(
            partial(sp.current_user_saved_albums_contains, batch),
            f"checking {len(batch)} saved Slow Listening releases",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise SlowListeningError("Spotify returned invalid saved-album statuses.")
        statuses.update(
            {
                spotify_id: bool(saved)
                for spotify_id, saved in zip(batch, response, strict=True)
            }
        )
    return statuses


def _preferred_edition(
    editions: list[DiscographyRelease],
) -> DiscographyRelease:
    """Prefer saved editions, then plain and minimally decorated editions."""
    return min(
        editions,
        key=lambda release: (
            not release.saved,
            not release.plain,
            release.edition_rank,
            release.total_tracks,
            _release_date_key(release.release_date),
            release.name.casefold(),
            release.spotify_id,
        ),
    )


def _tie_key(artist_id: str, chronology_date: str) -> str:
    """Return the restart-state key for one equal-date release group."""
    return f"{artist_id}:{chronology_date}"


def load_discography(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[DiscographyRelease, ...]:
    """Load, filter, collapse, and chronologically sort an artist catalog."""
    candidates: dict[str, DiscographyRelease] = {}
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
            f"loading Slow Listening releases for {artist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise SlowListeningError("Spotify returned invalid artist releases.")
        raw_items = response["items"]
        for raw_release in raw_items:
            candidate = _release_candidate(raw_release, artist_id)
            if candidate is not None:
                candidates[candidate.spotify_id] = candidate
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise SlowListeningError("Spotify returned an empty artist release page.")

    releases = list(candidates.values())
    saved = _load_saved_statuses(sp, releases, retry_call)
    releases = [
        replace(release, saved=saved.get(release.spotify_id, False))
        for release in releases
    ]

    editions_by_identity: dict[str, list[DiscographyRelease]] = defaultdict(list)
    for release in releases:
        editions_by_identity[release.identity].append(release)

    selected: list[DiscographyRelease] = []
    for editions in editions_by_identity.values():
        preferred = _preferred_edition(editions)
        chronology_date = min(
            (edition.release_date for edition in editions),
            key=_release_date_key,
        )
        selected.append(replace(preferred, chronology_date=chronology_date))

    return tuple(
        sorted(
            selected,
            key=lambda release: (
                _release_date_key(release.chronology_date),
                release.release_type,
                release.name.casefold(),
                release.spotify_id,
            ),
        )
    )


def _ordered_date_group(
    artist_id: str,
    releases: tuple[DiscographyRelease, ...],
    order_reader: ReleaseOrderReader,
    release_orders: dict[str, object],
    order_saved: Callable[[], None],
) -> tuple[DiscographyRelease, ...]:
    """Resolve an equal-date group only when a transition reaches it."""
    if len(releases) < 2:
        return releases

    release_date = releases[0].chronology_date
    preference_key = _tie_key(artist_id, release_date)
    expected_ids = {release.spotify_id for release in releases}
    stored = release_orders.get(preference_key)
    stored_ids = (
        tuple(str(spotify_id) for spotify_id in stored)
        if isinstance(stored, list)
        else ()
    )
    if len(stored_ids) != len(releases) or set(stored_ids) != expected_ids:
        stored_ids = order_reader(release_date, releases)
        if len(stored_ids) != len(releases) or set(stored_ids) != expected_ids:
            raise SlowListeningError("Release ordering must include every option.")
        release_orders[preference_key] = list(stored_ids)
        order_saved()

    by_id = {release.spotify_id: release for release in releases}
    return tuple(by_id[spotify_id] for spotify_id in stored_ids)


def _next_release(
    current_release: DiscographyRelease,
    discography: tuple[DiscographyRelease, ...],
    order_reader: ReleaseOrderReader,
    release_orders: dict[str, object],
    order_saved: Callable[[], None],
) -> DiscographyRelease | None:
    """Choose the next release, prompting only at this album boundary."""
    date_groups: dict[
        tuple[int, int, int, str],
        list[DiscographyRelease],
    ] = defaultdict(list)
    for release in discography:
        date_groups[_release_date_key(release.chronology_date)].append(release)

    ordered_dates = sorted(date_groups)
    current_date_key = _release_date_key(current_release.chronology_date)
    try:
        current_date_index = ordered_dates.index(current_date_key)
    except ValueError:
        return None

    current_group = _ordered_date_group(
        current_release.primary_artist_id,
        tuple(date_groups[current_date_key]),
        order_reader,
        release_orders,
        order_saved,
    )
    current_index = next(
        (
            index
            for index, release in enumerate(current_group)
            if release.spotify_id == current_release.spotify_id
        ),
        None,
    )
    if current_index is None:
        return None
    if current_index + 1 < len(current_group):
        return current_group[current_index + 1]

    if current_date_index + 1 >= len(ordered_dates):
        return None
    next_group = tuple(date_groups[ordered_dates[current_date_index + 1]])
    return _ordered_date_group(
        current_release.primary_artist_id,
        next_group,
        order_reader,
        release_orders,
        order_saved,
    )[0]


def _as_release_candidate(
    release: DiscographyRelease,
) -> new_wine.ReleaseCandidate:
    """Convert a selected release for the shared ordered-track loader."""
    return new_wine.ReleaseCandidate(
        spotify_id=release.spotify_id,
        uri=release.uri,
        name=release.name,
        release_type=release.release_type,
        release_date=release.release_date,
        total_tracks=release.total_tracks,
        primary_artist_id=release.primary_artist_id,
        primary_artist_name=release.primary_artist_name,
    )


def load_release_tracks(
    sp: Spotify,
    release: DiscographyRelease,
    retry_call: RetryCall,
) -> tuple[new_wine.ReleaseTrack, ...]:
    """Load one selected edition in Spotify disc and track order."""
    try:
        return new_wine.load_release_tracks(
            sp,
            _as_release_candidate(release),
            retry_call,
        )
    except new_wine.NewWineError as exc:
        raise SlowListeningError(str(exc)) from exc


def _track_index(
    tracks: tuple[new_wine.ReleaseTrack, ...],
    source: new_wine.PlaylistTrack,
) -> int | None:
    """Map the playlist item to a selected edition by id, then title."""
    for index, track in enumerate(tracks):
        if track.spotify_id == source.spotify_id:
            return index
    source_identity = _track_identity(source.name)
    matches = [
        index
        for index, track in enumerate(tracks)
        if _track_identity(track.name) == source_identity
    ]
    return matches[0] if len(matches) == 1 else None


def _default_state() -> dict[str, object]:
    """Return empty versioned restart state."""
    return {
        "version": STATE_VERSION,
        "release_orders": {},
        "active_run": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load restart state without silently discarding malformed data."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlowListeningStateError(
            f"Slow Listening state is invalid: {path}"
        ) from exc
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("release_orders"), dict)
    ):
        raise SlowListeningStateError(f"Slow Listening state is invalid: {path}")
    return raw


def save_state(
    state: dict[str, object],
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist restart state atomically."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise SlowListeningStateError(
            f"Could not save Slow Listening state: {path}"
        ) from exc


def append_log(
    run_id: str,
    result: FlushResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable transition record."""
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
        raise SlowListeningStateError(
            f"Could not write Slow Listening log: {path}"
        ) from exc


def _new_run(
    playlist_id: str,
    tracks: tuple[new_wine.PlaylistTrack, ...],
) -> dict[str, object]:
    """Snapshot no more than the first two current playlist entries."""
    selected = tracks[:MAX_TRACKS_PER_RUN]
    return {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "entries": [
            {
                "source": asdict(track),
                "status": "pending",
                "plan": None,
                "skipped_candidates": [],
            }
            for track in selected
        ],
    }


def _source_from_record(raw: object) -> new_wine.PlaylistTrack:
    """Rebuild one snapshotted playlist source."""
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise SlowListeningStateError("Slow Listening run has an invalid source.")
    release = new_wine.ReleaseCandidate(**raw["release"])
    return new_wine.PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=release,
    )


def _release_from_record(raw: object) -> DiscographyRelease | None:
    """Rebuild an optional selected release from a saved plan."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SlowListeningStateError("Slow Listening run has an invalid release.")
    return DiscographyRelease(**raw)


def _track_from_record(raw: object) -> new_wine.ReleaseTrack | None:
    """Rebuild an optional target track from a saved plan."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SlowListeningStateError("Slow Listening run has an invalid target.")
    return new_wine.ReleaseTrack(**raw)


def _add_playlist_track(
    sp: Spotify,
    playlist_id: str,
    track: new_wine.ReleaseTrack,
    retry_call: RetryCall,
) -> None:
    """Add a replacement before removing its source."""
    retry_call(
        lambda: sp._post(
            f"playlists/{playlist_id}/items",
            payload={"uris": [track.uri]},
        ),
        f"adding {track.name} to Slow Listening",
    )


def _remove_playlist_track(
    sp: Spotify,
    playlist_id: str,
    source: new_wine.PlaylistTrack,
    retry_call: RetryCall,
) -> None:
    """Remove the processed source after its replacement is secure."""
    retry_call(
        lambda: sp._delete(
            f"playlists/{playlist_id}/items",
            payload={"items": [{"uri": source.uri}]},
        ),
        f"removing {source.name} from Slow Listening",
    )


def _result_from_plan(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    *,
    dry_run: bool,
) -> FlushResult:
    """Convert a durable plan into a public result."""
    target = _track_from_record(plan.get("target"))
    release = _release_from_record(plan.get("target_release"))
    raw_skipped_candidates = plan.get("skipped_candidates")
    skipped_candidates = (
        tuple(
            str(candidate)
            for candidate in raw_skipped_candidates
            if isinstance(candidate, str)
        )
        if isinstance(raw_skipped_candidates, list)
        else ()
    )
    return FlushResult(
        source_track=source.name,
        source_release=source.release.name,
        artist=source.primary_artist_name,
        action=cast(FlushAction, str(plan["action"])),
        target_track=target.name if target is not None else None,
        target_release=release.name if release is not None else None,
        skipped_candidates=skipped_candidates,
        reason=str(plan["reason"]) if plan.get("reason") else None,
        dry_run=dry_run,
    )


def _build_plan(
    sp: Spotify,
    source: new_wine.PlaylistTrack,
    discography: tuple[DiscographyRelease, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[new_wine.ReleaseTrack, ...]],
    order_reader: ReleaseOrderReader,
    release_orders: dict[str, object],
    order_saved: Callable[[], None],
    action_reader: TrackActionReader,
    skipped_candidate_ids: set[str],
    candidate_skipped: Callable[[str], None],
) -> dict[str, object] | None:
    """Plan the next chronological track or final completion."""
    source_identity = release_identity(source.release.name)
    release_index = next(
        (
            index
            for index, release in enumerate(discography)
            if release.identity == source_identity
        ),
        None,
    )
    if release_index is None:
        return {
            "action": "skip",
            "target": None,
            "target_release": None,
            "reason": "current release is not an eligible studio album or EP",
        }

    current_release = discography[release_index]
    current_tracks = track_cache.get(current_release.spotify_id)
    if current_tracks is None:
        current_tracks = load_release_tracks(sp, current_release, retry_call)
        track_cache[current_release.spotify_id] = current_tracks
    source_index = _track_index(current_tracks, source)
    if source_index is None:
        return {
            "action": "skip",
            "target": None,
            "target_release": asdict(current_release),
            "reason": "current track could not be mapped to the preferred edition",
        }

    target_release = current_release
    target_tracks = current_tracks
    target_index = source_index + 1
    skipped_candidates: list[str] = []

    while True:
        if target_index >= len(target_tracks):
            next_release = _next_release(
                target_release,
                discography,
                order_reader,
                release_orders,
                order_saved,
            )
            if next_release is None:
                return {
                    "action": "complete",
                    "target": None,
                    "target_release": asdict(target_release),
                    "skipped_candidates": skipped_candidates,
                    "reason": (
                        "all remaining studio tracks were skipped"
                        if skipped_candidates
                        else "last track of the last studio release"
                    ),
                    "completion_acknowledged": False,
                }
            target_release = next_release
            next_tracks = track_cache.get(target_release.spotify_id)
            if next_tracks is None:
                next_tracks = load_release_tracks(sp, target_release, retry_call)
                track_cache[target_release.spotify_id] = next_tracks
            if not next_tracks:
                return {
                    "action": "skip",
                    "target": None,
                    "target_release": asdict(target_release),
                    "skipped_candidates": skipped_candidates,
                    "reason": "next release has no playable tracks",
                }
            target_tracks = next_tracks
            target_index = 0

        target = target_tracks[target_index]
        target_label = f"{target.name} ({target_release.name})"
        if target.spotify_id in skipped_candidate_ids:
            skipped_candidates.append(target_label)
            target_index += 1
            continue

        choice = action_reader(source, target, target_release)
        if choice == CHOICE_QUIT:
            return None
        if choice == CHOICE_ADVANCE:
            return {
                "action": "advance",
                "target": asdict(target),
                "target_release": asdict(target_release),
                "skipped_candidates": skipped_candidates,
                "reason": None,
            }
        if choice != CHOICE_SKIP:
            raise SlowListeningError(
                "Track action must be add, skip candidate, or quit."
            )

        skipped_candidate_ids.add(target.spotify_id)
        candidate_skipped(target.spotify_id)
        skipped_candidates.append(target_label)
        target_index += 1


def flush_slow_listening(
    sp: Spotify,
    playlist_id: str,
    order_reader: ReleaseOrderReader,
    completion_notifier: CompletionNotifier,
    *,
    action_reader: TrackActionReader | None = None,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
) -> FlushSummary:
    """Advance the first two Slow Listening entries once each."""
    retry = retry_call or (lambda operation, _description: operation())
    choose_action = action_reader or (lambda _source, _target, _release: CHOICE_ADVANCE)
    try:
        live_tracks = new_wine.load_playlist_tracks(sp, playlist_id, retry)
    except new_wine.NewWineError as exc:
        raise SlowListeningError(str(exc)) from exc
    live_ids = {track.spotify_id for track in live_tracks}

    resumed = False
    state = _default_state() if dry_run else load_state(state_path)
    active_run = state.get("active_run")
    if (
        not dry_run
        and isinstance(active_run, dict)
        and active_run.get("status") == "active"
        and active_run.get("playlist_id") == playlist_id
    ):
        run = active_run
        resumed = True
    else:
        run = _new_run(playlist_id, live_tracks)
        if not dry_run:
            state["active_run"] = run
            save_state(state, state_path)

    raw_entries = run.get("entries")
    if not isinstance(raw_entries, list):
        raise SlowListeningStateError("Slow Listening run has invalid entries.")
    release_orders = state.get("release_orders")
    if not isinstance(release_orders, dict):
        raise SlowListeningStateError("Slow Listening release orders are invalid.")

    run_id = str(run["run_id"])
    catalog_cache: dict[str, tuple[DiscographyRelease, ...]] = {}
    track_cache: dict[str, tuple[new_wine.ReleaseTrack, ...]] = {}
    results: list[FlushResult] = []
    total = len(raw_entries)
    paused = False

    def persist_order() -> None:
        if not dry_run:
            save_state(state, state_path)

    def persist_skipped_candidate(
        spotify_id: str,
        skipped_candidates: list[str],
    ) -> None:
        skipped_candidates.append(spotify_id)
        if not dry_run:
            save_state(state, state_path)

    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise SlowListeningStateError("Slow Listening run has an invalid entry.")
        if raw_entry.get("status") in {"completed", "skipped"}:
            continue
        source = _source_from_record(raw_entry.get("source"))
        if progress_callback is not None:
            progress_callback(
                index - 1,
                total,
                f"{source.primary_artist_name} - {source.name}",
            )

        raw_plan = raw_entry.get("plan")
        plan = raw_plan if isinstance(raw_plan, dict) else None
        if plan is None:
            raw_skipped_candidates = raw_entry.setdefault(
                "skipped_candidates",
                [],
            )
            if not isinstance(raw_skipped_candidates, list) or not all(
                isinstance(candidate, str) for candidate in raw_skipped_candidates
            ):
                raise SlowListeningStateError(
                    "Slow Listening run has invalid skipped candidates."
                )
            skipped_candidate_records = cast(
                list[str],
                raw_skipped_candidates,
            )
            skipped_candidate_ids = set(skipped_candidate_records)

            discography = catalog_cache.get(source.primary_artist_id)
            if discography is None:
                discography = load_discography(
                    sp,
                    source.primary_artist_id,
                    retry,
                )
                catalog_cache[source.primary_artist_id] = discography
            plan = _build_plan(
                sp,
                source,
                discography,
                retry,
                track_cache,
                order_reader,
                release_orders,
                persist_order,
                choose_action,
                skipped_candidate_ids,
                partial(
                    persist_skipped_candidate,
                    skipped_candidates=skipped_candidate_records,
                ),
            )
            if plan is None:
                paused = True
                break

        if raw_entry.get("plan") is None:
            raw_entry["plan"] = plan
            if not dry_run:
                save_state(state, state_path)

        action = str(plan["action"])
        target = _track_from_record(plan.get("target"))
        target_release = _release_from_record(plan.get("target_release"))

        if action == "skip":
            result = _result_from_plan(source, plan, dry_run=dry_run)
            results.append(result)
            append_log(run_id, result, log_path)
            echo(
                f"Skipped {source.primary_artist_name} - {source.name}: "
                f"{result.reason}."
            )
            if not dry_run:
                raw_entry["status"] = "skipped"
                save_state(state, state_path)
            continue

        source_present = source.spotify_id in live_ids
        if source_present and action == "advance" and target is not None:
            if target.spotify_id not in live_ids:
                if not dry_run:
                    _add_playlist_track(sp, playlist_id, target, retry)
                live_ids.add(target.spotify_id)
                echo(
                    f"{'Would add' if dry_run else 'Added'} next track: "
                    f"{target.name} ({target_release.name if target_release else '?'})"
                )
            if not dry_run:
                _remove_playlist_track(sp, playlist_id, source, retry)
            live_ids.discard(source.spotify_id)
            echo(
                f"{'Would remove' if dry_run else 'Removed'} previous track: "
                f"{source.name}"
            )
        elif source_present and action == "complete":
            if not dry_run:
                _remove_playlist_track(sp, playlist_id, source, retry)
            live_ids.discard(source.spotify_id)
            echo(
                f"{'Would complete' if dry_run else 'Completed'} "
                f"{source.primary_artist_name}: {source.name} was the final track."
            )
        elif not source_present:
            if (
                action == "advance"
                and target is not None
                and target.spotify_id not in live_ids
            ):
                raise SlowListeningStateError(
                    f"{source.name} is absent but its planned replacement "
                    f"{target.name} is not in Slow Listening."
                )
            echo(f"Source already removed; completing saved plan for {source.name}.")

        if (
            not dry_run
            and action == "complete"
            and not bool(plan.get("completion_acknowledged"))
        ):
            completion_notifier(source)
            plan["completion_acknowledged"] = True
            save_state(state, state_path)
            try:
                refreshed_tracks = new_wine.load_playlist_tracks(
                    sp,
                    playlist_id,
                    retry,
                )
            except new_wine.NewWineError as exc:
                raise SlowListeningError(str(exc)) from exc
            live_ids = {track.spotify_id for track in refreshed_tracks}

        result = _result_from_plan(source, plan, dry_run=dry_run)
        results.append(result)
        append_log(run_id, result, log_path)
        if not dry_run:
            raw_entry["status"] = "completed"
            save_state(state, state_path)
        if progress_callback is not None:
            progress_callback(index, total, f"Completed {source.name}")

    if (
        not dry_run
        and not paused
        and all(
            isinstance(entry, dict) and entry.get("status") in {"completed", "skipped"}
            for entry in raw_entries
        )
    ):
        run["status"] = "completed"
        run["completed_at"] = datetime.now(UTC).isoformat()
        save_state(state, state_path)

    return FlushSummary(
        run_id=run_id,
        total=total,
        processed=len(results),
        advanced=sum(result.action == "advance" for result in results),
        completed_artists=sum(result.action == "complete" for result in results),
        skipped=sum(result.action == "skip" for result in results),
        paused=paused,
        dry_run=dry_run,
        resumed=resumed,
        results=tuple(results),
    )
