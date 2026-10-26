"""Discover new Spotify releases from the user's most-scrobbled artists."""

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Protocol

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.artist_mapping import (
    ArtistChoiceReader as ArtistChoiceReader,
)
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.runtime import ReviewProgress
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
from spotify_manager.application.release_review import (
    ReleaseChoiceReader as ReleaseChoiceReader,
)

# UFI
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import StateLocation
from spotify_manager.core.state.compat import routine_state_from
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
from spotify_manager.infrastructure.release_readers import SpotifyReleasePages
from spotify_manager.infrastructure.release_readers import SpotifyReleasePlaylist
from spotify_manager.infrastructure.release_readers import SpotifyReleaseTracks
from spotify_manager.infrastructure.routine_state_codecs import ReleaseCheckStateCodec
from spotify_manager.interfaces.requests.release_check import ReleaseCheckCallbacks
from spotify_manager.interfaces.requests.release_check import ReleaseCheckOptions
from spotify_manager.interfaces.requests.release_check import ReleaseCheckResources
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history


type ProgressCallback = ReviewProgress


type RetryCall = Retry


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
    for attempt in retry_call.attempts(f"searching Spotify artists with {query}"):
        with attempt:
            response = sp.search(
                q=query, type="artist", limit=ARTIST_SEARCH_LIMIT, offset=0
            )
    from spotify_manager.infrastructure.release_check_catalog import parse_artist_search

    return parse_artist_search(response, artist.name)


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
    from spotify_manager.interfaces.operations.release_check import resolve_artist

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
    """Load recent and future releases from every Spotify catalog page.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original artist catalog reference.
        spotify_artist: Resolved Spotify artist identity.
        checked_from: Earliest release date to include.
        retry_call: Retry and cancellation hook.

    Returns:
        Original operation result.
    """
    from spotify_manager.infrastructure.release_pages import load_catalog_pages

    return load_catalog_pages(
        SpotifyReleasePages(sp, artist, spotify_artist, retry_call),
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
    for attempt in retry_call.attempts(
        f"loading releases for {artist.name} at offset {offset}"
    ):
        with attempt:
            response = sp.artist_albums(
                spotify_artist.spotify_id,
                include_groups="album,single",
                limit=ARTIST_RELEASE_PAGE_LIMIT,
                offset=offset,
            )
    return response


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
    """Load tracks in Spotify disc and track order.

    Args:
        sp: Caller-owned Spotify client.
        release: Selected release metadata.
        retry_call: Retry and cancellation hook.
        first_only: Whether to read only the first track.

    Returns:
        Original operation result.
    """
    from spotify_manager.infrastructure.release_pages import load_track_pages

    return load_track_pages(
        SpotifyReleaseTracks(sp, release, retry_call),
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
        response = _request_track_page(retry_call, offset, release, sp, limit)
        return response
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
    return routine_state_from(
        "release_check",
        ReleaseCheckStateCodec(),
        StateLocation(state_path, DEFAULT_STATE_PATH, state_service),
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
    """Parse one playlist item with original URI and ordering semantics."""
    from spotify_manager.infrastructure.release_check_catalog import (
        parse_playlist_entry,
    )

    return parse_playlist_entry(raw_entry)


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
        SpotifyReleasePlaylist(sp, playlist_id, retry_call),
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
    for attempt in retry_call.attempts(f"deduplicating playlist {playlist_id}"):
        with attempt:
            sp._put(
                f"playlists/{playlist_id}/items",
                payload={"uris": [entry.uri for entry in first_batch]},
            )
    for offset in range(PLAYLIST_WRITE_LIMIT, len(entries), PLAYLIST_WRITE_LIMIT):
        batch = entries[offset : offset + PLAYLIST_WRITE_LIMIT]
        _append_replacement_batch(retry_call, playlist_id, offset, sp, batch)


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
    for attempt in retry_call.attempts(
        f"adding {track.name} to playlist {playlist_id}"
    ):
        with attempt:
            sp._post(f"playlists/{playlist_id}/items", payload={"uris": [track.uri]})
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
    options: ReleaseCheckOptions,
    callbacks: ReleaseCheckCallbacks,
    resources: ReleaseCheckResources | None = None,
) -> ReleaseCheckSummary:
    """Refresh Last.fm, discover releases, and update both playlists safely.

    Args:
    sp: Caller-owned client.
    lastfm: Caller-owned client.
    options: Destinations and execution mode.
    callbacks: Operator decisions, notifications and retry ownership.
    resources: Persistent files and checkpoint authority.

    Returns:
    The original typed summary and accepted effects.

    Raises:
    RuntimeError: Observations, selections or persistence cannot complete.
    """
    from spotify_manager.interfaces.operations.release_check import (
        run_release_check as operation,
    )

    return operation(sp, lastfm, options, callbacks, resources)


def _read_playlist_page(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
    offset: int,
) -> object:
    for attempt in retry_call.attempts(
        f"loading playlist {playlist_id} at offset {offset}"
    ):
        with attempt:
            response = sp._get(
                f"playlists/{playlist_id}/items",
                limit=PLAYLIST_PAGE_LIMIT,
                offset=offset,
            )
    return response


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


def _request_track_page(
    retry_call: RetryCall,
    offset: int,
    release: ReleaseCandidate,
    sp: Spotify,
    limit: int,
) -> object:
    for attempt in retry_call.attempts(
        f"loading tracks from {release.name} at offset {offset}"
    ):
        with attempt:
            return sp.album_tracks(release.spotify_id, limit=limit, offset=offset)
    raise AssertionError("Retry scopes must include an attempt")


def _append_replacement_batch(
    retry_call: RetryCall,
    playlist_id: str,
    offset: int,
    sp: Spotify,
    batch: tuple[PlaylistEntry, ...],
) -> None:
    for attempt in retry_call.attempts(
        f"restoring playlist {playlist_id} at offset {offset}"
    ):
        with attempt:
            sp._post(
                f"playlists/{playlist_id}/items",
                payload={"uris": [entry.uri for entry in batch]},
            )
