"""Plan round-week discography batches from three ordered artist queues."""

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import cast

from spotipy import Spotify

# UFI
from spotify_manager.routines import new_wine
from spotify_manager.routines import slow_listening


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "discography_routine_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "discography_routine_log.jsonl"
STATE_VERSION = 1
RELEASE_PAGE_LIMIT = 10
SAVED_ALBUM_BATCH_SIZE = 20
PLAYLIST_MUTATION_BATCH_SIZE = 100
WEEK_RELEASES = 10

QueueName = Literal["newfoundland", "memory_lane", "requeue"]
MarkerQueueName = Literal["newfoundland", "memory_lane", "requeue", "queue_3"]
QUEUE_ORDER: tuple[QueueName, ...] = (
    "newfoundland",
    "memory_lane",
    "requeue",
)
START_QUEUE_ROTATION: tuple[QueueName, ...] = (
    "newfoundland",
    "requeue",
    "memory_lane",
)
QUEUE_LABELS: dict[MarkerQueueName, str] = {
    "newfoundland": "Newfoundland",
    "memory_lane": "Memory Lane",
    "requeue": "The Requeue",
    "queue_3": "The Queue 3",
}

RetryCall = Callable[[Callable[[], object], str], object]
ReleaseSelector = Callable[
    ["QueueArtist", tuple["CatalogRelease", ...]],
    tuple[str, ...],
]
ProgressCallback = Callable[[str], None]

LIVE_PATTERN = re.compile(
    r"(?:^live(?:!|$|\s)|\blive\b|\bao vivo\b|\ben vivo\b|"
    r"\bin concert\b|\bunplugged\b)",
    re.IGNORECASE,
)
COMPILATION_PATTERN = re.compile(
    r"\b(?:anthology|best of|collection|compilation|greatest hits|rarities)\b",
    re.IGNORECASE,
)


class DiscographyError(RuntimeError):
    """Base error for discography planning and queue updates."""


class DiscographyConfigError(DiscographyError):
    """Raised when one of the three source playlists is not configured."""


class DiscographyStateError(DiscographyError):
    """Raised when discography state or logs cannot be persisted safely."""


class DiscographyCancelledError(DiscographyError):
    """Raised when release selection is cancelled."""


@dataclass(frozen=True)
class CatalogRelease:
    """One canonical album or EP available for an artist's batch."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    chronology_date: str
    total_tracks: int
    identity: str
    saved: bool
    plain: bool
    edition_rank: int
    default: bool


@dataclass(frozen=True)
class QueueArtist:
    """One primary artist represented in an ordered source playlist."""

    spotify_id: str
    name: str
    queue: QueueName


@dataclass(frozen=True)
class ArtistMarkers:
    """Playlist marker URIs belonging to one selected artist."""

    queue: MarkerQueueName
    playlist_id: str
    uris: tuple[str, ...]


@dataclass(frozen=True)
class ArtistSelection:
    """One artist and the exact releases chosen for the listening batch."""

    spotify_id: str
    name: str
    source_queue: QueueName
    releases: tuple[CatalogRelease, ...]
    markers: tuple[ArtistMarkers, ...]

    @property
    def release_count(self) -> int:
        """Return the selected canonical release count."""
        return len(self.releases)

    @property
    def days(self) -> float:
        """Return listening days at two releases per day."""
        return self.release_count / 2


@dataclass(frozen=True)
class DiscographyPlan:
    """The next batch selected according to queue order and week packing."""

    start_queue: QueueName
    next_queue: QueueName
    artists: tuple[ArtistSelection, ...]
    total_releases: int
    open_slots: int

    @property
    def days(self) -> float:
        """Return total listening days at two releases per day."""
        return self.total_releases / 2

    @property
    def fills_round_week(self) -> bool:
        """Return whether the plan ends on a positive multiple of ten."""
        return self.total_releases > 0 and self.open_slots == 0


@dataclass(frozen=True)
class DiscographyRunSummary:
    """Outcome of applying a confirmed discography plan."""

    removed_artists: int
    removed_markers: int
    next_queue: QueueName


def parse_playlist_id(reference: str | None, setting_name: str) -> str:
    """Extract a playlist id and translate shared configuration errors."""
    try:
        return new_wine.parse_playlist_id(reference, setting_name)
    except new_wine.NewWineConfigError as exc:
        raise DiscographyConfigError(str(exc)) from exc


def parse_playlist_ids(
    newfoundland: str | None,
    memory_lane: str | None,
    requeue: str | None,
) -> dict[QueueName, str]:
    """Parse all three configured source playlist references."""
    return {
        "newfoundland": parse_playlist_id(
            newfoundland,
            "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
        ),
        "memory_lane": parse_playlist_id(
            memory_lane,
            "DISCOGRAPHY_MEMORY_LANE_PLAYLIST",
        ),
        "requeue": parse_playlist_id(
            requeue,
            "DISCOGRAPHY_REQUEUE_PLAYLIST",
        ),
    }


def _default_state() -> dict[str, object]:
    """Return the initial queue-priority state."""
    return {"version": STATE_VERSION, "next_queue": "requeue"}


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load persisted queue priority without hiding malformed state."""
    if not path.exists():
        return _default_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscographyStateError(f"Discography state is invalid: {path}") from exc
    if (
        not isinstance(state, dict)
        or state.get("version") != STATE_VERSION
        or state.get("next_queue") not in QUEUE_ORDER
    ):
        raise DiscographyStateError(f"Discography state is invalid: {path}")
    return state


def save_next_queue(
    next_queue: QueueName,
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist the next source queue through an atomic replacement."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(
                {"version": STATE_VERSION, "next_queue": next_queue},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise DiscographyStateError(
            f"Could not save discography state: {path}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _queue_cycle(start: QueueName) -> tuple[QueueName, ...]:
    """Return queue names in cyclic order from the persisted starting point."""
    index = QUEUE_ORDER.index(start)
    return QUEUE_ORDER[index:] + QUEUE_ORDER[:index]


def _next_queue(queue: QueueName) -> QueueName:
    """Return the queue immediately after the given queue."""
    return QUEUE_ORDER[(QUEUE_ORDER.index(queue) + 1) % len(QUEUE_ORDER)]


def _next_start_queue(queue: QueueName) -> QueueName:
    """Rotate the starting priority independently from within-run packing."""
    index = START_QUEUE_ROTATION.index(queue)
    return START_QUEUE_ROTATION[(index + 1) % len(START_QUEUE_ROTATION)]


def _load_artist_queues(
    spotify: Spotify,
    playlist_ids: dict[QueueName, str],
    retry_call: RetryCall,
    queue_3_playlist_id: str | None = None,
) -> tuple[
    dict[QueueName, tuple[QueueArtist, ...]],
    dict[str, tuple[ArtistMarkers, ...]],
]:
    """Load ordered, primary-artist queues and every matching marker URI."""
    queues: dict[QueueName, tuple[QueueArtist, ...]] = {}
    markers: dict[str, list[ArtistMarkers]] = defaultdict(list)
    for queue in QUEUE_ORDER:
        try:
            tracks = new_wine.load_playlist_tracks(
                spotify,
                playlist_ids[queue],
                retry_call,
            )
        except new_wine.NewWineError as exc:
            raise DiscographyError(str(exc)) from exc

        artist_order: list[str] = []
        artist_names: dict[str, str] = {}
        artist_uris: dict[str, list[str]] = defaultdict(list)
        for track in tracks:
            artist_id = track.primary_artist_id
            if artist_id not in artist_names:
                artist_order.append(artist_id)
                artist_names[artist_id] = track.primary_artist_name
            if track.uri not in artist_uris[artist_id]:
                artist_uris[artist_id].append(track.uri)
        queues[queue] = tuple(
            QueueArtist(
                spotify_id=artist_id,
                name=artist_names[artist_id],
                queue=queue,
            )
            for artist_id in artist_order
        )
        for artist_id in artist_order:
            markers[artist_id].append(
                ArtistMarkers(
                    queue=queue,
                    playlist_id=playlist_ids[queue],
                    uris=tuple(artist_uris[artist_id]),
                )
            )
    if queue_3_playlist_id is not None:
        try:
            queue_3_tracks = new_wine.load_playlist_tracks(
                spotify,
                queue_3_playlist_id,
                retry_call,
            )
        except new_wine.NewWineError as exc:
            raise DiscographyError(str(exc)) from exc
        queue_3_uris: dict[str, list[str]] = defaultdict(list)
        for track in queue_3_tracks:
            if track.uri not in queue_3_uris[track.primary_artist_id]:
                queue_3_uris[track.primary_artist_id].append(track.uri)
        for artist_id, uris in queue_3_uris.items():
            markers[artist_id].append(
                ArtistMarkers(
                    queue="queue_3",
                    playlist_id=queue_3_playlist_id,
                    uris=tuple(uris),
                )
            )

    return queues, {artist_id: tuple(groups) for artist_id, groups in markers.items()}


def _positive_int(value: object) -> int:
    """Return a positive integer or zero for malformed Spotify fields."""
    return value if isinstance(value, int) and value > 0 else 0


def _catalog_release(raw: object, artist_id: str) -> CatalogRelease | None:
    """Parse a canonical candidate, excluding true non-EP singles."""
    if not isinstance(raw, dict):
        return None
    artists = slow_listening._artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or spotify_id).strip()
    if not spotify_id or not name:
        return None
    uri = str(raw.get("uri") or f"spotify:album:{spotify_id}").strip()
    total_tracks = _positive_int(raw.get("total_tracks"))
    album_type = str(raw.get("album_type") or "").casefold()
    album_group = str(raw.get("album_group") or "").casefold()
    standard = slow_listening._release_candidate(raw, artist_id)
    is_ep = album_type == "ep" or (
        album_type == "single"
        and (total_tracks >= 4 or slow_listening.EP_MARKER.search(name))
    )
    is_compilation = album_type == "compilation" or album_group == "compilation"
    if album_type == "single" and not is_ep:
        return None
    if standard is not None:
        release_type = standard.release_type
    elif is_compilation or COMPILATION_PATTERN.search(name):
        release_type = "Compilation"
    elif LIVE_PATTERN.search(name):
        release_type = "Live"
    elif album_type == "album" or is_ep:
        release_type = "Other"
    else:
        return None

    release_date = str(raw.get("release_date") or "Unknown")
    _base, edition_rank = slow_listening._edition_details(name)
    return CatalogRelease(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=release_type,
        release_date=release_date,
        chronology_date=release_date,
        total_tracks=total_tracks,
        identity=slow_listening.release_identity(name),
        saved=False,
        plain=edition_rank == 0,
        edition_rank=edition_rank,
        default=standard is not None,
    )


def _preferred_release(editions: list[CatalogRelease]) -> CatalogRelease:
    """Choose one edition with the same saved/plain preference as Slow Listening."""
    return min(
        editions,
        key=lambda release: (
            not release.saved,
            not release.plain,
            release.edition_rank,
            release.total_tracks,
            slow_listening._release_date_key(release.release_date),
            release.name.casefold(),
            release.spotify_id,
        ),
    )


def load_release_catalog(
    spotify: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[CatalogRelease, ...]:
    """Load canonical albums and EPs, including optional non-studio releases."""
    candidates: dict[str, CatalogRelease] = {}
    offset = 0
    while True:
        response = retry_call(
            partial(
                spotify.artist_albums,
                artist_id,
                include_groups="album,single,compilation",
                limit=RELEASE_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading discography releases for {artist_id} at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise DiscographyError("Spotify returned invalid artist releases.")
        raw_items = response["items"]
        for raw_release in raw_items:
            candidate = _catalog_release(raw_release, artist_id)
            if candidate is not None:
                candidates[candidate.spotify_id] = candidate
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise DiscographyError("Spotify returned an empty artist release page.")

    releases = list(candidates.values())
    saved_by_id: dict[str, bool] = {}
    for start in range(0, len(releases), SAVED_ALBUM_BATCH_SIZE):
        batch = releases[start : start + SAVED_ALBUM_BATCH_SIZE]
        album_ids = [release.spotify_id for release in batch]
        statuses = retry_call(
            partial(spotify.current_user_saved_albums_contains, album_ids),
            f"checking {len(album_ids)} saved discography releases",
        )
        if not isinstance(statuses, list) or len(statuses) != len(album_ids):
            raise DiscographyError("Spotify returned invalid saved-album statuses.")
        saved_by_id.update(
            {
                album_id: bool(saved)
                for album_id, saved in zip(album_ids, statuses, strict=True)
            }
        )
    releases = [
        replace(release, saved=saved_by_id.get(release.spotify_id, False))
        for release in releases
    ]

    grouped: dict[tuple[str, str], list[CatalogRelease]] = defaultdict(list)
    for release in releases:
        category = "standard" if release.default else release.release_type.casefold()
        grouped[(category, release.identity)].append(release)

    selected: list[CatalogRelease] = []
    for editions in grouped.values():
        preferred = _preferred_release(editions)
        chronology_date = min(
            (edition.release_date for edition in editions),
            key=slow_listening._release_date_key,
        )
        selected.append(
            replace(
                preferred,
                chronology_date=chronology_date,
                default=any(edition.default for edition in editions),
            )
        )
    return tuple(
        sorted(
            selected,
            key=lambda release: (
                slow_listening._release_date_key(release.chronology_date),
                release.release_type,
                release.name.casefold(),
                release.spotify_id,
            ),
        )
    )


def parse_release_indexes(value: str, total: int) -> tuple[int, ...]:
    """Parse comma-separated indexes and inclusive ranges."""
    indexes: list[int] = []
    seen: set[int] = set()
    for part in (item.strip() for item in value.split(",")):
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            if len(bounds) != 2:
                raise ValueError("invalid range")
            start, end = (int(bound.strip()) for bound in bounds)
            if start > end:
                raise ValueError("range start exceeds range end")
            values = range(start, end + 1)
        else:
            index = int(part)
            values = range(index, index + 1)
        for index in values:
            if index < 1 or index > total:
                raise ValueError("release number out of range")
            if index not in seen:
                indexes.append(index)
                seen.add(index)
    return tuple(indexes)


def format_release_indexes(indexes: tuple[int, ...]) -> str:
    """Compress ordered indexes into a short range expression."""
    if not indexes:
        return "n"
    ordered = sorted(set(indexes))
    ranges: list[str] = []
    start = previous = ordered[0]
    for index in ordered[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = index
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def build_discography_plan(
    spotify: Spotify,
    playlist_ids: dict[QueueName, str],
    release_selector: ReleaseSelector,
    *,
    queue_3_playlist_id: str | None = None,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
) -> DiscographyPlan:
    """Build the next round-week batch without changing Spotify or state."""
    retry = retry_call or (lambda operation, _description: operation())
    state = load_state(state_path)
    start_queue = cast(QueueName, state["next_queue"])
    if progress_callback is not None:
        progress_callback("Loading discography artist queues")
    queues, markers = _load_artist_queues(
        spotify,
        playlist_ids,
        retry,
        queue_3_playlist_id,
    )

    catalogs: dict[str, tuple[CatalogRelease, ...]] = {}
    choices: dict[str, tuple[CatalogRelease, ...]] = {}

    def catalog_for(candidate: QueueArtist) -> tuple[CatalogRelease, ...]:
        cached = catalogs.get(candidate.spotify_id)
        if cached is not None:
            return cached
        if progress_callback is not None:
            progress_callback(f"Loading {candidate.name}'s release catalog")
        catalog = load_release_catalog(spotify, candidate.spotify_id, retry)
        catalogs[candidate.spotify_id] = catalog
        return catalog

    def resolve(candidate: QueueArtist) -> tuple[CatalogRelease, ...]:
        cached = choices.get(candidate.spotify_id)
        if cached is not None:
            return cached
        catalog = catalog_for(candidate)
        selected_ids = release_selector(candidate, catalog)
        available_ids = {release.spotify_id for release in catalog}
        if len(set(selected_ids)) != len(selected_ids) or not set(
            selected_ids
        ).issubset(available_ids):
            raise DiscographyError(
                f"Release selection for {candidate.name} was not valid."
            )
        selected_set = set(selected_ids)
        selected = tuple(
            release for release in catalog if release.spotify_id in selected_set
        )
        choices[candidate.spotify_id] = selected
        return selected

    def default_count(candidate: QueueArtist) -> int:
        """Return the silent canonical count used while scanning for a fit."""
        return sum(release.default for release in catalog_for(candidate))

    selected_artists: list[ArtistSelection] = []
    selected_ids: set[str] = set()
    declined_ids: set[str] = set()

    def select(candidate: QueueArtist) -> ArtistSelection | None:
        releases = resolve(candidate)
        if not releases:
            return None
        artist_markers = markers.get(candidate.spotify_id, ())
        if not any(marker.queue == "newfoundland" for marker in artist_markers):
            artist_markers = tuple(
                marker for marker in artist_markers if marker.queue != "queue_3"
            )
        return ArtistSelection(
            spotify_id=candidate.spotify_id,
            name=candidate.name,
            source_queue=candidate.queue,
            releases=releases,
            markers=artist_markers,
        )

    first: ArtistSelection | None = None
    for queue in _queue_cycle(start_queue):
        for candidate in queues[queue]:
            if candidate.spotify_id in selected_ids | declined_ids:
                continue
            first = select(candidate)
            if first is not None:
                break
            declined_ids.add(candidate.spotify_id)
        if first is not None:
            break
    if first is None:
        return DiscographyPlan(
            start_queue=start_queue,
            next_queue=start_queue,
            artists=(),
            total_releases=0,
            open_slots=0,
        )

    selected_artists.append(first)
    selected_ids.add(first.spotify_id)
    total = first.release_count
    last_queue = first.source_queue

    while (remaining := (-total) % WEEK_RELEASES) != 0:
        match: ArtistSelection | None = None
        for queue in _queue_cycle(_next_queue(last_queue)):
            for candidate in queues[queue]:
                if candidate.spotify_id in selected_ids | declined_ids:
                    continue
                if not 0 < default_count(candidate) <= remaining:
                    continue
                candidate_selection = select(candidate)
                if candidate_selection is None:
                    declined_ids.add(candidate.spotify_id)
                    continue
                match = candidate_selection
                break
            if match is not None:
                break
        if match is None:
            break
        selected_artists.append(match)
        selected_ids.add(match.spotify_id)
        total += match.release_count
        last_queue = match.source_queue

    return DiscographyPlan(
        start_queue=start_queue,
        next_queue=_next_start_queue(start_queue),
        artists=tuple(selected_artists),
        total_releases=total,
        open_slots=(-total) % WEEK_RELEASES,
    )


def _append_log(
    selection: ArtistSelection,
    next_queue: QueueName,
    path: Path,
) -> None:
    """Append one successfully removed artist with the exact release set."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "artist_id": selection.spotify_id,
        "artist": selection.name,
        "source_queue": selection.source_queue,
        "releases": [asdict(release) for release in selection.releases],
        "markers": [asdict(marker) for marker in selection.markers],
        "next_queue": next_queue,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise DiscographyStateError(
            f"Could not write discography routine log: {path}"
        ) from exc


def apply_discography_plan(
    spotify: Spotify,
    plan: DiscographyPlan,
    *,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
) -> DiscographyRunSummary:
    """Remove confirmed artists' markers and advance priority after each artist."""
    retry = retry_call or (lambda operation, _description: operation())
    removed_markers = 0
    for selection in plan.artists:
        if progress_callback is not None:
            progress_callback(f"Removing {selection.name} from discography queues")
        for marker_group in selection.markers:
            uris = list(dict.fromkeys(marker_group.uris))
            for start in range(0, len(uris), PLAYLIST_MUTATION_BATCH_SIZE):
                batch = uris[start : start + PLAYLIST_MUTATION_BATCH_SIZE]
                retry(
                    partial(
                        spotify._delete,
                        f"playlists/{marker_group.playlist_id}/items",
                        payload={"items": [{"uri": uri} for uri in batch]},
                    ),
                    (
                        f"removing {selection.name} from "
                        f"{QUEUE_LABELS[marker_group.queue]}"
                    ),
                )
                removed_markers += len(batch)
        _append_log(selection, plan.next_queue, log_path)
    save_next_queue(plan.next_queue, state_path)
    return DiscographyRunSummary(
        removed_artists=len(plan.artists),
        removed_markers=removed_markers,
        next_queue=plan.next_queue,
    )
