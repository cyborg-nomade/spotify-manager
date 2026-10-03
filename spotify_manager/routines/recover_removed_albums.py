"""Audit removed albums for credited artists and future releases."""

import json
from collections.abc import Callable
from collections.abc import Iterable
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep
from typing import cast

from spotipy import Spotify

from spotify_manager.application.library_statistics import (
    period_report as select_period_report,
)
from spotify_manager.application.library_statistics import report_with_recovered_counts
from spotify_manager.application.recovery_values import RecoveryState as RecoveryState
from spotify_manager.application.recovery_values import (
    RecoverySummary as RecoverySummary,
)
from spotify_manager.application.recovery_values import (
    RemovedAlbumRecord as RemovedAlbumRecord,
)

# UFI
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain import library as library_policy
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.infrastructure.library_records import current_stats_history_key
from spotify_manager.infrastructure.spotify.retry import TRANSIENT_MAX_ATTEMPTS
from spotify_manager.infrastructure.spotify.retry import TRANSIENT_RETRY_DELAY_SECONDS
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.infrastructure.spotify.retry import SpotifyTransientServerError
from spotify_manager.infrastructure.spotify.retry import (
    retry_spotify_server_errors as retry_spotify_server_errors,
)
from spotify_manager.loaders_savers import load_stats_history_file
from spotify_manager.loaders_savers import (
    load_total_albums_new_file as load_total_albums_new_file,
)
from spotify_manager.loaders_savers import (
    load_total_artists_file as load_total_artists_file,
)
from spotify_manager.loaders_savers import save_stats_history
from spotify_manager.loaders_savers import save_total_albums_new_file
from spotify_manager.loaders_savers import save_total_artists_file
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key


RECOVERY_LOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "files"
    / "removed_albums_recovery_log.jsonl"
)
ALBUM_BATCH_SIZE = 20
ARTIST_BATCH_SIZE = 40

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
Sleep = Callable[[float], None]


def load_removed_album_records(
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
) -> list[RemovedAlbumRecord]:
    """Load unique removed albums in their original review order.

    Args:
        log_path: Original removal audit destination.

    Returns:
        The first usable record for each observed identifier.

    Raises:
        OSError: The audit cannot be opened or read.
        ValueError: A nonblank line contains invalid JSON.
    """
    with open(log_path) as log_file:
        return _removed_records(log_file, log_path)


def _removed_record(
    line: str, line_number: int, path: Path
) -> RemovedAlbumRecord | None:
    if not line.strip():
        return None
    try:
        entry = cast(dict[str, object], json.loads(line))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path} at line {line_number}.") from exc
    spotify_id = str(entry.get("spotify_id", "")).strip()
    if not spotify_id:
        return None
    return RemovedAlbumRecord(
        spotify_id,
        str(entry.get("album", spotify_id)),
        str(entry.get("artist", "Unknown artist")),
    )


def _removed_records(lines: Iterable[str], path: Path) -> list[RemovedAlbumRecord]:
    records: list[RemovedAlbumRecord] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        record = _removed_record(line, line_number, path)
        if record is None or record.spotify_id in seen_ids:
            continue
        seen_ids.add(record.spotify_id)
        records.append(record)
    return records


def load_recovery_state(log_path: Path = RECOVERY_LOG_PATH) -> RecoveryState:
    """Reconstruct completed album and artist work from an append-only log.

    Args:
        log_path: Original recovery audit destination.

    Returns:
        Completed identities, ignoring malformed JSON and unknown events.

    Raises:
        OSError: An existing audit cannot be read.
    """
    state = RecoveryState(processed_album_ids=set(), checked_artist_ids=set())
    if not log_path.exists():
        return state

    with open(log_path) as log_file:
        for line in log_file:
            _apply_recovery_line(state, line)
    return state


def _apply_recovery_line(state: RecoveryState, line: str) -> None:
    try:
        entry = cast(dict[str, object], json.loads(line))
    except json.JSONDecodeError:
        return
    spotify_id = str(entry.get("spotify_id", "")).strip()
    if not spotify_id:
        return
    if entry.get("event") == "album_processed":
        state.processed_album_ids.add(spotify_id)
    elif entry.get("event") == "artist_checked":
        state.checked_artist_ids.add(spotify_id)


def _default_state() -> dict[str, object]:
    """Return empty serialized recovery progress."""
    return {
        "version": 1,
        "processed_album_ids": [],
        "checked_artist_ids": [],
    }


def validate_state(raw: object) -> dict[str, object]:
    """Validate removed-album recovery progress independently of storage.

    Args:
        raw: Untrusted stored payload; existing tolerant validation is preserved.

    Returns:
        The original validated document, including unknown fields.
    """
    if (
        not isinstance(raw, dict)
        or raw.get("version") != 1
        or not isinstance(raw.get("processed_album_ids"), list)
        or not isinstance(raw.get("checked_artist_ids"), list)
        or not all(isinstance(item, str) for item in raw["processed_album_ids"])
        or not all(isinstance(item, str) for item in raw["checked_artist_ids"])
    ):
        raise ValueError("Removed-album recovery state is invalid.")
    return raw


def _serialize_state(state: RecoveryState) -> dict[str, object]:
    """Serialize mutable recovery progress for central persistence."""
    return {
        "version": 1,
        "processed_album_ids": sorted(state.processed_album_ids),
        "checked_artist_ids": sorted(state.checked_artist_ids),
    }


def _deserialize_state(raw: object) -> RecoveryState:
    """Create mutable recovery progress from validated state."""
    normalized = validate_state(raw)
    processed = normalized["processed_album_ids"]
    checked = normalized["checked_artist_ids"]
    assert isinstance(processed, list)
    assert isinstance(checked, list)
    return RecoveryState(set(processed), set(checked))


def _load_log_state(log_path: Path) -> dict[str, object]:
    """Reconstruct legacy state from the append-only audit log."""
    return _serialize_state(load_recovery_state(log_path))


def _save_log_state(_state: dict[str, object], _log_path: Path) -> None:
    """Keep explicit legacy paths log-backed; events are written separately."""


def _state_access(
    recovery_log_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test log."""
    return routine_state(
        name="recover_removed_albums",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=recovery_log_path,
        default_legacy_path=RECOVERY_LOG_PATH,
        legacy_loader=_load_log_state,
        legacy_saver=_save_log_state,
        service=state_service,
    )


def append_recovery_events(
    events: list[dict[str, object]],
    log_path: Path = RECOVERY_LOG_PATH,
) -> None:
    """Append completed recovery work so an interrupted run can resume.

    Args:
        events: Original heterogeneous JSON audit events.
        log_path: Original audit file destination.
    """
    if not events:
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as log_file:
        for event in events:
            log_file.write(json.dumps(event, ensure_ascii=False) + "\n")


def release_is_in_future(
    release_date: str | None,
    precision: str | None,
    today: date | None = None,
) -> bool:
    """Evaluate the shared date policy using the original optional local clock.

    Args:
        release_date: Original possibly partial date text.
        precision: Reported Spotify precision, when present.
        today: Optional fixed comparison date.

    Returns:
        Whether the reported precision proves the release is in the future.
    """
    if not release_date:
        return False
    return library_policy.release_is_in_future(
        release_date, precision, today or date.today()
    )


def spotify_album_artists(album: dict[str, object]) -> list[AlbumArtist]:
    """Extract all distinct credited artists from Spotify album metadata.

    Args:
        album: Original validated library item.

    Returns:
        Distinct usable artist identities in original credit order.
    """
    artists: list[AlbumArtist] = []
    seen_ids: set[str] = set()
    raw_artists = album.get("artists")
    if not isinstance(raw_artists, list):
        return artists

    for raw_artist in raw_artists:
        if not isinstance(raw_artist, dict):
            continue
        spotify_id = str(raw_artist.get("id", "")).strip()
        if not spotify_id or spotify_id in seen_ids:
            continue
        seen_ids.add(spotify_id)
        artists.append(
            AlbumArtist(
                spotify_id=spotify_id,
                name=str(raw_artist.get("name") or spotify_id),
            )
        )
    return artists


def chunked[T](items: list[T], size: int) -> list[list[T]]:
    """Split a list into API-sized batches.

    Args:
        items: Original ordered input values.
        size: Original batch size.

    Returns:
        Consecutive batches with the original slicing behavior.
    """
    return [items[start : start + size] for start in range(0, len(items), size)]


def period_report(stats_history: dict[str, StatsReport]) -> tuple[str, StatsReport]:
    """Select the current statistics period or seed it from the last report.

    Args:
        stats_history: Nonempty insertion-ordered statistics history.

    Returns:
        Original period key and existing or reset report.

    Raises:
        StopIteration: No report exists to seed the new period.
    """
    return select_period_report(stats_history, current_stats_history_key())


def sync_stats_history_counts(
    total_albums: int | None = None,
    total_artists: int | None = None,
) -> bool:
    """Persist recovery's count reconciliation at its original boundary.

    Args:
        total_albums: New album count, or None to retain it.
        total_artists: New artist count, or None to retain it.

    Returns:
        Whether a nonempty history was updated.
    """
    stats_history = load_stats_history_file()
    if not stats_history:
        return False
    key, report = period_report(stats_history)
    stats_history[key] = report_with_recovered_counts(
        report, total_albums, total_artists
    )
    save_stats_history(stats_history)
    return True


def add_artists_to_local_files(
    artists: list[AlbumArtist],
    total_artists: list[YourLibraryArtist],
    known_artist_ids: set[str],
) -> set[str]:
    """Persist newly discovered followed artists in one API-sized batch.

    Args:
        artists: Ordered observed artist identities.
        total_artists: Mutable local artist mirror snapshot.
        known_artist_ids: Mutable identifiers already present in the local mirror.

    Returns:
        Identifiers newly inserted into the artist mirror.
    """
    added_ids: set[str] = set()
    for artist in artists:
        if artist.spotify_id in known_artist_ids:
            continue
        total_artists.append(
            YourLibraryArtist(
                name=artist.name,
                uri=f"spotify:artist:{artist.spotify_id}",
            )
        )
        known_artist_ids.add(artist.spotify_id)
        added_ids.add(artist.spotify_id)

    if added_ids:
        total_artists.sort(key=artist_sort_key)
        save_total_artists_file(total_artists)
        sync_stats_history_counts(total_artists=len(total_artists))
    return added_ids


def _artist_statuses(
    sp: Spotify,
    artist_batch: list[AlbumArtist],
    retry_call: Callable[[Callable[[], object], str], object],
) -> list[bool]:
    artist_ids = [artist.spotify_id for artist in artist_batch]
    return cast(
        list[bool],
        retry_call(
            partial(sp.current_user_following_artists, artist_ids),
            f"checking {len(artist_ids)} credited artists",
        ),
    )


def _follow_missing_artists(
    sp: Spotify,
    missing_artists: list[AlbumArtist],
    retry_call: Callable[[Callable[[], object], str], object],
) -> None:
    retry_call(
        partial(
            sp.user_follow_artists, [artist.spotify_id for artist in missing_artists]
        ),
        f"following {len(missing_artists)} credited artists",
    )


def ensure_artists_followed(
    sp: Spotify,
    artists: list[AlbumArtist],
    state: RecoveryState,
    total_artists: list[YourLibraryArtist],
    known_artist_ids: set[str],
    retry_call: Callable[[Callable[[], object], str], object],
    echo: Echo,
    recovery_log_path: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """Recover credited artist follows through the shared application service.

    Args:
        sp: Caller-owned Spotify client.
        artists: Original ordered album credits.
        state: Mutable completed-work state.
        total_artists: Mutable artist mirror snapshot.
        known_artist_ids: IDs already in that mirror.
        retry_call: Original retry callback.
        echo: Original output callback.
        recovery_log_path: Original recovery audit destination.
        dry_run: Preview without remote or durable writes.

    Returns:
        Original completed-check and new-follow counts.

    Raises:
        RuntimeError: Membership is incomplete or an effect fails.
    """
    from spotify_manager.bootstrap.album_recovery import run_artist_recovery

    return run_artist_recovery(
        sp,
        artists,
        state,
        total_artists,
        known_artist_ids,
        retry_call,
        echo,
        recovery_log_path,
        dry_run,
        _clock,
    )


def add_album_to_local_files(
    album: dict[str, object],
    record: RemovedAlbumRecord,
    total_albums: list[YourLibraryAlbum],
    known_album_ids: set[str],
) -> bool:
    """Restore one future release to albums_total_new.json when absent.

    Args:
        album: Original validated library item.
        record: Original removal-log identity and fallback labels.
        total_albums: Mutable local album mirror snapshot.
        known_album_ids: Mutable identifiers already present in the local album mirror.

    Returns:
        Whether this album was inserted into the local mirror.
    """
    if record.spotify_id in known_album_ids:
        return False

    artists = spotify_album_artists(album)
    primary_artist = artists[0].name if artists else record.artist
    total_albums.append(
        YourLibraryAlbum(
            artist=primary_artist,
            album=str(album.get("name") or record.album),
            uri=str(album.get("uri") or f"spotify:album:{record.spotify_id}"),
        )
    )
    known_album_ids.add(record.spotify_id)
    total_albums.sort(key=album_sort_key)
    save_total_albums_new_file(total_albums)
    sync_stats_history_counts(total_albums=len(total_albums))
    return True


def _clock() -> datetime:
    return datetime.now(UTC)


def _today(today: date | None) -> date:
    return today or date.today()


def _fetch_album_metadata(
    sp: Spotify,
    album_ids: list[str],
    retry_call: Callable[[Callable[[], object], str], object],
) -> list[object]:
    response = retry_call(
        partial(sp.albums, album_ids),
        f"fetching metadata for {len(album_ids)} removed albums",
    )
    raw_albums = cast(dict[str, object], response).get("albums", [])
    if not isinstance(raw_albums, list):
        raise RuntimeError("Spotify returned an invalid albums response.")
    return raw_albums


def _saved_album(
    sp: Spotify,
    record: RemovedAlbumRecord,
    retry_call: Callable[[Callable[[], object], str], object],
) -> bool:
    response = retry_call(
        partial(sp.current_user_saved_albums_contains, [record.spotify_id]),
        f"checking future release {record.album}",
    )
    statuses = cast(list[object], response)
    return bool(statuses[0]) if statuses else False


def _restore_album(
    sp: Spotify,
    record: RemovedAlbumRecord,
    retry_call: Callable[[Callable[[], object], str], object],
) -> None:
    retry_call(
        partial(sp.current_user_saved_albums_add, [record.spotify_id]),
        f"restoring future release {record.album}",
    )


def recover_removed_albums(
    sp: Spotify,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    removal_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    recovery_log_path: Path = RECOVERY_LOG_PATH,
    dry_run: bool = False,
    limit: int | None = None,
    today: date | None = None,
    sleep: Sleep = default_sleep,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
    state_service: StateService | None = None,
) -> RecoverySummary:
    """Recover artists and future albums through explicit application dependencies.

    Args:
        sp: Caller-owned synchronous client.
        echo: Existing output sink.
        progress_callback: Optional completion and cancellation callback.
        removal_log_path: Original removal history.
        recovery_log_path: Recovery audit destination.
        dry_run: Preview without remote or durable writes.
        limit: Original pending-record slice limit.
        today: Optional fixed comparison date.
        sleep: Existing retry wait callback.
        transient_retry_delay_seconds: Existing retry delay.
        transient_max_attempts: Existing retry limit.
        state_service: Optional shared-state service.

    Returns:
        Original immutable recovery summary.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyTransientServerError: The existing retry policy is exhausted.
        RuntimeError: A response is malformed or a caller interrupts execution.
    """
    from spotify_manager.interfaces.operations.recover_removed_albums import (
        recover_removed_albums as operation,
    )

    return operation(
        sp,
        echo,
        progress_callback,
        removal_log_path,
        recovery_log_path,
        dry_run,
        limit,
        today,
        sleep,
        transient_retry_delay_seconds,
        transient_max_attempts,
        state_service,
    )


__all__ = [
    "RECOVERY_LOG_PATH",
    "RecoverySummary",
    "SpotifyRateLimitError",
    "SpotifyTransientServerError",
    "recover_removed_albums",
    "release_is_in_future",
]
