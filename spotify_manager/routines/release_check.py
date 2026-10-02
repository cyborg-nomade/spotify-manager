"""Discover new Spotify releases from the user's most-scrobbled artists."""

import hashlib
import json
from collections.abc import Callable
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
    from spotify_manager.infrastructure.release_pages import load_catalog_pages

    return load_catalog_pages(
        partial(_read_catalog_page, sp, artist, spotify_artist, retry_call),
        _release_candidate,
        artist.name,
        spotify_artist.spotify_id,
        checked_from,
    )


def _read_catalog_page(
    sp: Spotify,
    artist: RankedArtist,
    spotify_artist: SpotifyArtistCandidate,
    retry_call: RetryCall,
    offset: int,
) -> object:
    return retry_call(
        partial(
            sp.artist_albums,
            spotify_artist.spotify_id,
            include_groups="album,single",
            limit=ARTIST_RELEASE_PAGE_LIMIT,
            offset=offset,
        ),
        f"loading releases for {artist.name} at offset {offset}",
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
    from spotify_manager.infrastructure.release_pages import load_track_pages

    return load_track_pages(
        partial(_read_track_page, sp, release, retry_call),
        _track_candidate,
        release.name,
        first_only,
        RELEASE_TRACK_PAGE_LIMIT,
    )


def _read_track_page(
    sp: Spotify,
    release: ReleaseCandidate,
    retry_call: RetryCall,
    offset: int,
    limit: int,
) -> object:
    from spotify_manager.infrastructure.release_pages import MissingReleaseTracksError

    try:
        return retry_call(
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
        raise MissingReleaseTracksError from exc


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
    from spotify_manager.infrastructure.release_state_codec import default_state

    return default_state(STATE_VERSION)


def validate_state(raw: object) -> dict[str, Any]:
    """Validate and normalize one release-check state payload."""
    from spotify_manager.infrastructure.release_state_codec import validate_state

    return validate_state(raw, STATE_VERSION)


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
    from spotify_manager.infrastructure.release_state_codec import active_artists

    return active_artists(active)


def _mapped_artist(raw: object) -> SpotifyArtistCandidate | None:
    """Parse one persisted Last.fm-to-Spotify mapping."""
    from spotify_manager.infrastructure.release_state_codec import mapped_artist

    return mapped_artist(raw)


def _pending_single(raw: object) -> PendingSingle | None:
    """Parse one pending single from restart state."""
    from spotify_manager.infrastructure.release_state_codec import pending_single

    return pending_single(raw)


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
    from spotify_manager.infrastructure.release_pages import load_playlist_pages

    parsed = load_playlist_pages(
        partial(_read_playlist_page, sp, playlist_id, retry_call),
        _playlist_entry,
        playlist_id,
    )
    return PlaylistSnapshot(parsed, _membership(parsed))


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
    from spotify_manager.application.release_results import release_result

    return release_result(
        artist,
        spotify_artist,
        release,
        track=track,
        linked_future_release=linked_future_release,
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
    from spotify_manager.bootstrap.release_run import run_release_review

    return run_release_review(
        opening,
        state_access,
        sp,
        playlists,
        log_path,
        artist_choice_reader,
        release_choice_reader,
        progress_callback,
        retry_call,
        dry_run,
    )


def _read_playlist_page(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
    offset: int,
) -> object:
    return retry_call(
        partial(
            sp._get,
            f"playlists/{playlist_id}/items",
            limit=PLAYLIST_PAGE_LIMIT,
            offset=offset,
        ),
        f"loading playlist {playlist_id} at offset {offset}",
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
