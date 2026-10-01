"""Discover new Spotify releases from the user's most-scrobbled artists."""

import hashlib
import json
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
from typing import Protocol

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.release_check_values import (
    ReleaseCheckConfigError as ReleaseCheckConfigError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckError as ReleaseCheckError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckSpotifyError as ReleaseCheckSpotifyError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckStateError as ReleaseCheckStateError,
)
from spotify_manager.application.release_check_values import (
    ReleaseCheckSummary as ReleaseCheckSummary,
)

# UFI
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain import release_check as release_policy
from spotify_manager.domain.artist_mapping import (
    SpotifyArtistCandidate as SpotifyArtistCandidate,
)
from spotify_manager.domain.release_check import (
    ALWAYS_EXCLUDED_RELEASE as ALWAYS_EXCLUDED_RELEASE,
)
from spotify_manager.domain.release_check import DELUXE_RELEASE as DELUXE_RELEASE
from spotify_manager.domain.release_check import EDITION_RELEASE as EDITION_RELEASE
from spotify_manager.domain.release_check import EP_MARKER as EP_MARKER
from spotify_manager.domain.release_check import LIVE_RELEASE as LIVE_RELEASE
from spotify_manager.domain.release_check_values import PendingSingle as PendingSingle
from spotify_manager.domain.release_check_values import PlaylistAction as PlaylistAction
from spotify_manager.domain.release_check_values import PlaylistEntry as PlaylistEntry
from spotify_manager.domain.release_check_values import (
    PlaylistMembership as PlaylistMembership,
)
from spotify_manager.domain.release_check_values import (
    PlaylistSnapshot as PlaylistSnapshot,
)
from spotify_manager.domain.release_check_values import RankedArtist as RankedArtist
from spotify_manager.domain.release_check_values import (
    ReleaseCandidate as ReleaseCandidate,
)
from spotify_manager.domain.release_check_values import (
    ReleaseCheckResult as ReleaseCheckResult,
)
from spotify_manager.domain.release_check_values import ReleaseTrack as ReleaseTrack
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import composer_playlists
from spotify_manager.routines import scrobble_history


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "release_check_state.json"
DEFAULT_STATE_BACKUP_DIR = FILES_DIR / "release_check_state_backups"
DEFAULT_LOG_PATH = FILES_DIR / "release_check_log.jsonl"
STATE_VERSION = 1
MIN_ARTIST_SCROBBLES = 100
NEW_VINTAGE_ARTIST_LIMIT = 50
ALL_SINGLES_ARTIST_LIMIT = 20
ARTIST_SEARCH_LIMIT = 10
ARTIST_RELEASE_PAGE_LIMIT = 10
RELEASE_TRACK_PAGE_LIMIT = 50
PLAYLIST_PAGE_LIMIT = 50
PLAYLIST_WRITE_LIMIT = 100
ARTIST_PROGRESS_CHECKPOINT_INTERVAL = 100
CHOICE_ADD = "add"
CHOICE_PENDING = "pending"
CHOICE_SKIP = "skip"
CHOICE_SKIP_ARTIST = "skip-artist"
CHOICE_QUIT = "quit"
CHOICE_SEARCH_PREFIX = "search:"

ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]


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


ArtistChoiceReader = Callable[
    [RankedArtist, tuple[SpotifyArtistCandidate, ...]],
    str,
]
ReleaseChoiceReader = Callable[
    [RankedArtist, ReleaseCandidate, ReleaseTrack, tuple[str, ...], bool],
    str,
]


def _direct_retry(operation: Callable[[], object], _description: str) -> object:
    """Call Spotify directly when no outer retry policy is supplied."""
    return operation()


def rank_lastfm_artists(
    history: tuple[blast_from_past.Scrobble, ...],
) -> tuple[RankedArtist, ...]:
    """Rank original normalized artists before applying the configured minimum.

    Args:
        history: Original ordered canonical plays.

    Returns:
        Original ranked eligible artists and majority display spellings.
    """
    return release_policy.rank_artists(history, MIN_ARTIST_SCROBBLES)


def _positive_int(raw: object) -> int | None:
    """Return a non-negative Spotify integer when present."""
    from spotify_manager.infrastructure.release_check_catalog import positive_int

    return positive_int(raw)


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Return Spotify artist ids and names in credit order."""
    from spotify_manager.infrastructure.release_check_catalog import artist_pairs

    return artist_pairs(raw)


def _spotify_artist(
    raw: object,
    rank: int,
    expected_name: str,
) -> SpotifyArtistCandidate | None:
    """Parse one complete artist search result."""
    from spotify_manager.infrastructure.release_check_catalog import parse_artist

    return parse_artist(raw, rank, expected_name)


def search_spotify_artists(
    sp: Spotify,
    artist: RankedArtist,
    retry_call: RetryCall,
    search_text: str | None = None,
) -> tuple[SpotifyArtistCandidate, ...]:
    """Read original Spotify artist candidates with unchanged query and retry semantics.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original ranked Last.fm evidence.
        retry_call: Original retry policy.
        search_text: Optional explicit original custom query.

    Returns:
        Original complete observations with original unfiltered search ranks.

    Raises:
        ReleaseCheckSpotifyError: Original response lacks its search items list.
    """
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
    from spotify_manager.infrastructure.release_check_catalog import parse_artist_search

    return parse_artist_search(response, artist.name, _spotify_artist)


def resolve_spotify_artist(
    sp: Spotify,
    artist: RankedArtist,
    choice_reader: ArtistChoiceReader | None,
    retry_call: RetryCall,
) -> SpotifyArtistCandidate | str | None:
    """Resolve original artist mappings with repeated explicit custom searches.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original ranked Last.fm evidence.
        choice_reader: Original interaction, absent for noninteractive runs.
        retry_call: Original catalog retry policy.

    Returns:
        Original selected mapping, control response or absent noninteractive result.

    Raises:
        ReleaseCheckSpotifyError: Original mapping or choice is invalid.
    """
    from spotify_manager.bootstrap.artist_mapping import resolve_artist

    return resolve_artist(sp, artist, choice_reader, retry_call)


def _release_type(raw_type: object, total_tracks: int, name: str) -> str:
    """Distinguish albums, EPs, and singles from Spotify metadata."""
    return release_policy.release_type(raw_type, total_tracks, name)


def _release_candidate(
    raw: object,
    artist_id: str,
) -> ReleaseCandidate | None:
    """Parse one release whose first credited artist is the target."""
    from spotify_manager.infrastructure.release_check_catalog import parse_release

    return parse_release(raw, artist_id)


def release_date_interval(release: ReleaseCandidate) -> tuple[date, date] | None:
    """Resolve the original possible interval for Spotify date precision.

    Args:
        release: Original precision-preserving metadata.

    Returns:
        Inclusive original date interval, or no valid date.
    """
    return release_policy.release_date_interval(release)


def release_scope_reason(release: ReleaseCandidate, artist_rank: int) -> str | None:
    """Apply original title exclusions and configured artist-rank boundary.

    Args:
        release: Original observed release.
        artist_rank: Original global Last.fm rank.

    Returns:
        Original exclusion reason, or eligibility.
    """
    return release_policy.release_scope_reason(
        release, artist_rank, NEW_VINTAGE_ARTIST_LIMIT
    )


def load_recent_catalog(
    sp: Spotify,
    artist: RankedArtist,
    spotify_artist: SpotifyArtistCandidate,
    checked_from: date,
    retry_call: RetryCall,
) -> tuple[ReleaseCandidate, ...]:
    """Load recent and future releases from every Spotify catalog page."""
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
            if interval[1] >= checked_from:
                releases[candidate.spotify_id] = candidate
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty release page for {artist.name}."
            )
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
    from spotify_manager.infrastructure.release_check_catalog import parse_track

    return parse_track(raw, fallback_position)


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
    """Resolve the first original announced record containing the selected single.

    Args:
        sp: Caller-owned Spotify client.
        single_track: Original selected single marker.
        future_releases: Original ordered announced records.
        retry_call: Original track observation retry policy.
        track_cache: Optional original caller-owned track cache.

    Returns:
        Original first matching record or no match.

    Raises:
        ReleaseCheckSpotifyError: Original track observation is unusable.
    """
    from spotify_manager.bootstrap.release_catalog import matching_future_record

    return matching_future_record(
        sp, single_track, future_releases, retry_call, track_cache
    )


def _default_state() -> dict[str, Any]:
    """Return an empty versioned release-check state."""
    return {
        "version": STATE_VERSION,
        "updated_at": None,
        "last_successful_check_at": None,
        "last_checked_through": None,
        "artist_mappings": {},
        "skipped_artists": {},
        "processed_releases": {},
        "pending_singles": {},
        "active_run": None,
    }


def validate_state(raw: object) -> dict[str, Any]:
    """Validate and normalize one release-check state payload."""
    if isinstance(raw, dict):
        raw = deepcopy(raw)
        # Earlier version 1 payloads predate these additive durability fields.
        raw.setdefault("updated_at", None)
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
        raise ReleaseCheckStateError("Release-check state is invalid.")
    return raw


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    """Load restart state without silently discarding malformed data."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return validate_state(raw)
    except (OSError, json.JSONDecodeError, ReleaseCheckStateError) as exc:
        raise ReleaseCheckStateError(f"Release-check state is invalid: {path}") from exc


def state_updated_at(state: dict[str, Any]) -> str | None:
    """Return the best semantic timestamp available for freshness comparison."""
    candidates = [state.get("updated_at"), state.get("last_successful_check_at")]
    active = state.get("active_run")
    if isinstance(active, dict):
        candidates.append(active.get("started_at"))
    parsed: list[tuple[datetime, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        try:
            timestamp = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        parsed.append((timestamp.astimezone(UTC), candidate))
    return max(parsed, default=(datetime.min.replace(tzinfo=UTC), None))[1]


def state_fingerprint(state: dict[str, Any]) -> str:
    """Return a stable digest used by the web restart-recovery handshake."""
    serialized = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    """Persist release-check state atomically."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        state["updated_at"] = datetime.now(UTC).isoformat()
        normalized = validate_state(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise ReleaseCheckStateError(
            f"Could not save release-check state: {path}"
        ) from exc


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="release_check",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def _persist_state(state_access: RoutineState, state: dict[str, Any]) -> None:
    """Checkpoint release state while retaining its semantic freshness field."""
    state["updated_at"] = datetime.now(UTC).isoformat()
    state_access.save(state)


def _checkpoint_completed_artist(
    state_access: RoutineState,
    state: dict[str, Any],
    completed_since_checkpoint: int,
) -> int:
    """Batch read-only artist progress to stay below remote commit limits."""
    pending = completed_since_checkpoint + 1
    if pending < ARTIST_PROGRESS_CHECKPOINT_INTERVAL:
        return pending
    _persist_state(state_access, state)
    return 0


def _checkpoint_dry_run_learning(
    state_access: RoutineState,
    state: dict[str, Any],
    pending_changes: int,
    *,
    force: bool = False,
) -> int:
    """Batch mappings learned by dry runs without exhausting Hub commits."""
    if pending_changes == 0:
        return 0
    if not force and pending_changes < ARTIST_PROGRESS_CHECKPOINT_INTERVAL:
        return pending_changes
    _persist_state(state_access, state)
    return 0


def restore_state(
    state: dict[str, Any],
    path: Path = DEFAULT_STATE_PATH,
    backup_dir: Path = DEFAULT_STATE_BACKUP_DIR,
) -> Path | None:
    """Restore a newer state payload after backing up the server copy."""
    normalized = validate_state(state)
    backup_path: Path | None = None
    try:
        if path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = backup_dir / f"release-check-before-restore-{stamp}.json"
            backup_path.write_bytes(path.read_bytes())
        save_state(normalized, path)
    except OSError as exc:
        raise ReleaseCheckStateError(
            f"Could not restore release-check state: {path}"
        ) from exc
    return backup_path


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


def _playlist_entry(raw_entry: object) -> PlaylistEntry | None:
    """Parse one playlist item while preserving its original URI and order."""
    if not isinstance(raw_entry, dict):
        return None
    raw_track = raw_entry.get("item") or raw_entry.get("track")
    if not isinstance(raw_track, dict):
        return None
    uri = str(raw_track.get("uri") or "").strip()
    if not uri:
        return None
    artists = _artist_pairs(raw_track.get("artists"))
    return PlaylistEntry(
        uri=uri,
        spotify_id=str(raw_track.get("id") or "").strip(),
        name=str(raw_track.get("name") or uri).strip(),
        primary_artist_id=artists[0][0] if artists else None,
        primary_artist_name=artists[0][1] if artists else None,
    )


def _membership(entries: tuple[PlaylistEntry, ...]) -> PlaylistMembership:
    """Build mutable playlist indexes from ordered entries."""
    return release_policy.membership(entries)


def _playlist_snapshot(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> PlaylistSnapshot:
    """Load one destination playlist in order with artist indexes."""
    entries: list[PlaylistEntry] = []
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
            raise ReleaseCheckSpotifyError(
                f"Spotify returned invalid playlist data for {playlist_id}."
            )
        raw_items = response["items"]
        for raw_entry in raw_items:
            entry = _playlist_entry(raw_entry)
            if entry is None:
                raise ReleaseCheckSpotifyError(
                    f"Playlist {playlist_id} contains an item that cannot be "
                    "preserved safely."
                )
            entries.append(entry)
        offset += len(raw_items)
        total = response.get("total")
        has_more = bool(response.get("next"))
        if isinstance(total, int):
            has_more = has_more or offset < total
        if not has_more:
            parsed = tuple(entries)
            return PlaylistSnapshot(parsed, _membership(parsed))
        if not raw_items:
            raise ReleaseCheckSpotifyError(
                f"Spotify returned an empty playlist page for {playlist_id}."
            )


def _playlist_membership(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> PlaylistMembership:
    """Load one destination playlist's lookup indexes."""
    return _playlist_snapshot(sp, playlist_id, retry_call).membership


def _deduplicated_entries(
    entries: tuple[PlaylistEntry, ...],
) -> tuple[PlaylistEntry, ...]:
    """Keep the first Wine Cellar item for each primary Spotify artist."""
    return release_policy.deduplicated_entries(entries)


def _replace_playlist_entries(
    sp: Spotify,
    playlist_id: str,
    entries: tuple[PlaylistEntry, ...],
    retry_call: RetryCall,
) -> None:
    """Replace a playlist in bounded batches while preserving item order."""
    first_batch = entries[:PLAYLIST_WRITE_LIMIT]
    retry_call(
        partial(
            sp._put,
            f"playlists/{playlist_id}/items",
            payload={"uris": [entry.uri for entry in first_batch]},
        ),
        f"deduplicating playlist {playlist_id}",
    )
    for offset in range(PLAYLIST_WRITE_LIMIT, len(entries), PLAYLIST_WRITE_LIMIT):
        batch = entries[offset : offset + PLAYLIST_WRITE_LIMIT]
        retry_call(
            partial(
                sp._post,
                f"playlists/{playlist_id}/items",
                payload={"uris": [entry.uri for entry in batch]},
            ),
            f"restoring playlist {playlist_id} at offset {offset}",
        )


def _deduplicate_wine_cellar(
    sp: Spotify,
    playlist_id: str,
    snapshot: PlaylistSnapshot,
    dry_run: bool,
    retry_call: RetryCall,
) -> tuple[int, PlaylistMembership]:
    """Normalize Wine Cellar to one ordered item per primary artist."""
    kept = _deduplicated_entries(snapshot.entries)
    removed = len(snapshot.entries) - len(kept)
    if removed and not dry_run:
        _replace_playlist_entries(sp, playlist_id, kept, retry_call)
    return removed, _membership(kept)


def _track_key(track: ReleaseTrack) -> tuple[str, str]:
    """Return the same artist/title identity used by playlist scans."""
    return release_policy.track_key(track)


def _track_is_present(
    membership: PlaylistMembership,
    track: ReleaseTrack,
) -> bool:
    """Return whether a playlist already contains this track identity."""
    return release_policy.track_is_present(membership, track)


def _artist_is_present(
    membership: PlaylistMembership,
    spotify_artist: SpotifyArtistCandidate,
) -> bool:
    """Return whether an artist already occupies a playlist slot."""
    return release_policy.artist_is_present(membership, spotify_artist)


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
        membership.primary_artist_ids.add(track.primary_artist_id)
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
    membership.primary_artist_ids.add(track.primary_artist_id)
    return "added"


def _release_identity(release: ReleaseCandidate) -> tuple[str, str, str]:
    """Collapse market duplicates without merging deluxe and plain releases."""
    return release_policy.release_identity(release)


def release_tags(release: ReleaseCandidate) -> tuple[str, ...]:
    """Retain original live-before-deluxe review labels.

    Args:
        release: Original observed display title.

    Returns:
        Original ordered special-release labels.
    """
    return release_policy.release_tags(release)


def _released_during(
    release: ReleaseCandidate,
    checked_from: date,
    checked_through: date,
) -> bool:
    """Return whether a release's precision interval overlaps the check window."""
    return release_policy.released_during(release, checked_from, checked_through)


def _future_record(
    release: ReleaseCandidate,
    checked_through: date,
    artist_rank: int,
) -> bool:
    """Return whether a qualifying album/EP is definitely still unreleased."""
    return release_policy.future_record(release, checked_through, artist_rank)


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
    dry_run: bool,
    *,
    terminal: bool,
) -> None:
    """Audit and apply one release decision to the in-memory checkpoint."""
    if dry_run:
        return
    append_event(log_path, run_id, "release_checked", result=asdict(result))
    if terminal:
        _mark_processed(state, result, checked_at)
        _remove_pending(state, result.release_id)


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
    wine_cellar_duplicates_removed: int,
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
        wine_cellar_duplicates_removed=wine_cellar_duplicates_removed,
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
    state_service: StateService | None = None,
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
    from spotify_manager.bootstrap.release_opening import open_release_run

    opening, state_access = open_release_run(
        lastfm,
        expected_username,
        dry_run,
        state_path,
        state_service,
        log_path,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        now,
        progress_callback,
    )
    generated_at = opening.generated_at
    persisted_state, state = opening.persisted_state, opening.state
    active, artists = opening.active, opening.artists
    checked_from, checked_through = opening.checked_from, opening.checked_through
    run_id, resumed = opening.run_id, opening.resumed
    history_refresh = opening.history_refresh

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
    wine_snapshot = _playlist_snapshot(
        sp,
        playlists.wine_cellar,
        retry_call,
    )
    wine_duplicates_removed, wine_membership = _deduplicate_wine_cellar(
        sp,
        playlists.wine_cellar,
        wine_snapshot,
        dry_run,
        retry_call,
    )
    if wine_duplicates_removed:
        action = "Would remove" if dry_run else "Removed"
        if progress_callback is not None:
            progress_callback(
                len(completed),
                len(artists),
                f"{action} {wine_duplicates_removed} duplicate Wine Cellar track(s)",
            )
        if not dry_run:
            append_event(
                log_path,
                run_id,
                "wine_cellar_deduplicated",
                removed=wine_duplicates_removed,
                retained=len(wine_snapshot.entries) - wine_duplicates_removed,
            )
    vintage_membership = _playlist_membership(
        sp,
        playlists.new_vintage,
        retry_call,
    )
    if progress_callback is not None:
        progress_callback(
            len(completed),
            len(artists),
            "Loading classical composer playlists",
        )
    try:
        owned_playlists = composer_playlists.load_owned_playlists(
            sp,
            retry_call,
            frozenset({playlists.wine_cellar, playlists.new_vintage}),
        )
    except composer_playlists.ComposerPlaylistError as exc:
        raise ReleaseCheckSpotifyError(str(exc)) from exc
    excluded_composer_playlists = frozenset(
        {playlists.wine_cellar, playlists.new_vintage}
    )
    results: list[ReleaseCheckResult] = []
    completed_since_checkpoint = 0
    dry_run_learning_since_checkpoint = 0

    for artist in artists:
        if artist.key in completed:
            continue
        if artist.key in skipped_artists:
            completed.add(artist.key)
            active["completed_artist_keys"] = sorted(completed)
            if not dry_run:
                completed_since_checkpoint = _checkpoint_completed_artist(
                    state_access,
                    state,
                    completed_since_checkpoint,
                )
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
                if dry_run:
                    dry_run_learning_since_checkpoint = _checkpoint_dry_run_learning(
                        state_access,
                        persisted_state,
                        dry_run_learning_since_checkpoint,
                        force=True,
                    )
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
                    wine_cellar_duplicates_removed=wine_duplicates_removed,
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
                    _persist_state(state_access, persisted_state)
                    dry_run_learning_since_checkpoint = 0
                else:
                    append_event(
                        log_path,
                        run_id,
                        "artist_permanently_skipped",
                        artist=artist.name,
                    )
                    _persist_state(state_access, state)
                    completed_since_checkpoint = 0
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
                    completed_since_checkpoint = _checkpoint_completed_artist(
                        state_access,
                        state,
                        completed_since_checkpoint,
                    )
                continue
            assert isinstance(resolved, SpotifyArtistCandidate)
            spotify_artist = resolved
            mappings[artist.key] = asdict(spotify_artist)
            if dry_run:
                persisted_mappings = persisted_state["artist_mappings"]
                assert isinstance(persisted_mappings, dict)
                persisted_mappings[artist.key] = asdict(spotify_artist)
                dry_run_learning_since_checkpoint = _checkpoint_dry_run_learning(
                    state_access,
                    persisted_state,
                    dry_run_learning_since_checkpoint + 1,
                )

        composer_matches = composer_playlists.composer_playlist_candidates(
            spotify_artist.name,
            owned_playlists,
            excluded_playlist_ids=excluded_composer_playlists,
        )
        if composer_matches:
            completed.add(artist.key)
            active["completed_artist_keys"] = sorted(completed)
            if not dry_run:
                completed_since_checkpoint = _checkpoint_completed_artist(
                    state_access,
                    state,
                    completed_since_checkpoint,
                )
            if progress_callback is not None:
                progress_callback(
                    len(completed),
                    len(artists),
                    f"#{artist.rank} {artist.name}: classical composer, skipped",
                )
            continue

        if _artist_is_present(wine_membership, spotify_artist) and not (
            artist.is_new_vintage
        ):
            completed.add(artist.key)
            active["completed_artist_keys"] = sorted(completed)
            if not dry_run:
                completed_since_checkpoint = _checkpoint_completed_artist(
                    state_access,
                    state,
                    completed_since_checkpoint,
                )
            if progress_callback is not None:
                progress_callback(
                    len(completed),
                    len(artists),
                    f"#{artist.rank} {artist.name}: already in Wine Cellar",
                )
            continue

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
        current_release_ids = {
            release.spotify_id for release in current_by_identity.values()
        }
        releases_to_check.extend(
            pending.release
            for release_id, pending in pending_for_artist.items()
            if release_id not in current_release_ids
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
                wine_artist_present = _artist_is_present(
                    wine_membership,
                    spotify_artist,
                )
                destinations: list[str] = []
                if not wine_artist_present:
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
                    if not dry_run:
                        _persist_state(state_access, state)
                        completed_since_checkpoint = 0
                    choice = release_choice_reader(
                        artist,
                        release,
                        track,
                        tuple(destinations),
                        unattached_single,
                    )
                if choice == CHOICE_QUIT:
                    if dry_run:
                        dry_run_learning_since_checkpoint = (
                            _checkpoint_dry_run_learning(
                                state_access,
                                persisted_state,
                                dry_run_learning_since_checkpoint,
                                force=True,
                            )
                        )
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
                        wine_cellar_duplicates_removed=wine_duplicates_removed,
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
                        dry_run,
                        terminal=False,
                    )
                    active["pending_release_id"] = None
                    if not dry_run:
                        _persist_state(state_access, state)
                        completed_since_checkpoint = 0
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
                        dry_run,
                        terminal=True,
                    )
                    active["pending_release_id"] = None
                    if not dry_run:
                        _persist_state(state_access, state)
                        completed_since_checkpoint = 0
                    continue

                wine_action: PlaylistAction = (
                    "artist already present"
                    if wine_artist_present
                    else _add_to_playlist(
                        sp,
                        playlists.wine_cellar,
                        wine_membership,
                        track,
                        dry_run,
                        retry_call,
                    )
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
                dry_run,
                terminal=terminal,
            )
            active["pending_release_id"] = None
            if not dry_run:
                _persist_state(state_access, state)
                completed_since_checkpoint = 0

        completed.add(artist.key)
        active["completed_artist_keys"] = sorted(completed)
        if not dry_run:
            completed_since_checkpoint = _checkpoint_completed_artist(
                state_access,
                state,
                completed_since_checkpoint,
            )
        if progress_callback is not None:
            progress_callback(
                len(completed),
                len(artists),
                f"#{artist.rank} {artist.name}: complete",
            )

    if dry_run:
        _checkpoint_dry_run_learning(
            state_access,
            persisted_state,
            dry_run_learning_since_checkpoint,
            force=True,
        )
    else:
        state["last_successful_check_at"] = datetime.now(UTC).isoformat()
        state["last_checked_through"] = checked_through.isoformat()
        state["active_run"] = None
        _persist_state(state_access, state)
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
        wine_cellar_duplicates_removed=wine_duplicates_removed,
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
