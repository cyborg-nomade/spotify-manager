"""Audit removed albums for credited artists and future releases."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep

from spotipy import Spotify

# UFI
from spotify_manager.loaders_savers import load_stats_history_file
from spotify_manager.loaders_savers import load_total_albums_new_file
from spotify_manager.loaders_savers import load_total_artists_file
from spotify_manager.loaders_savers import save_stats_history
from spotify_manager.loaders_savers import save_total_albums_new_file
from spotify_manager.loaders_savers import save_total_artists_file
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.routines.review_album_limits import REMOVED_ALBUMS_LOG_PATH
from spotify_manager.routines.review_album_limits import TRANSIENT_MAX_ATTEMPTS
from spotify_manager.routines.review_album_limits import TRANSIENT_RETRY_DELAY_SECONDS
from spotify_manager.routines.review_album_limits import AlbumArtist
from spotify_manager.routines.review_album_limits import SpotifyRateLimitError
from spotify_manager.routines.review_album_limits import SpotifyTransientServerError
from spotify_manager.routines.review_album_limits import current_stats_history_key
from spotify_manager.routines.review_album_limits import retry_spotify_server_errors
from spotify_manager.utils.growth import calculate_growth
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


@dataclass(frozen=True)
class RemovedAlbumRecord:
    """Album identity retained by the removal log."""

    spotify_id: str
    album: str
    artist: str


@dataclass
class RecoveryState:
    """Restart-safe progress reconstructed from the recovery log."""

    processed_album_ids: set[str]
    checked_artist_ids: set[str]


@dataclass(frozen=True)
class RecoverySummary:
    """Counts from one recovery run."""

    processed: int
    unavailable: int
    multi_artist_albums: int
    artists_checked: int
    artists_followed: int
    future_releases: int
    albums_restored: int


def load_removed_album_records(
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
) -> list[RemovedAlbumRecord]:
    """Load unique removed albums in their original review order."""
    records: list[RemovedAlbumRecord] = []
    seen_ids: set[str] = set()

    with open(log_path) as log_file:
        for line_number, line in enumerate(log_file, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {log_path} at line {line_number}."
                ) from exc

            spotify_id = str(entry.get("spotify_id", "")).strip()
            if not spotify_id or spotify_id in seen_ids:
                continue

            seen_ids.add(spotify_id)
            records.append(
                RemovedAlbumRecord(
                    spotify_id=spotify_id,
                    album=str(entry.get("album", spotify_id)),
                    artist=str(entry.get("artist", "Unknown artist")),
                )
            )

    return records


def load_recovery_state(log_path: Path = RECOVERY_LOG_PATH) -> RecoveryState:
    """Reconstruct completed album and artist work from an append-only log."""
    state = RecoveryState(processed_album_ids=set(), checked_artist_ids=set())
    if not log_path.exists():
        return state

    with open(log_path) as log_file:
        for line in log_file:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            spotify_id = str(entry.get("spotify_id", "")).strip()
            if not spotify_id:
                continue
            if entry.get("event") == "album_processed":
                state.processed_album_ids.add(spotify_id)
            elif entry.get("event") == "artist_checked":
                state.checked_artist_ids.add(spotify_id)

    return state


def append_recovery_events(
    events: list[dict[str, object]],
    log_path: Path = RECOVERY_LOG_PATH,
) -> None:
    """Append completed recovery work so an interrupted run can resume."""
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
    """Return whether Spotify's possibly partial release date is provably future."""
    if not release_date:
        return False

    current_date = today or date.today()
    parts = release_date.split("-")
    inferred_precision = {1: "year", 2: "month", 3: "day"}.get(len(parts))
    effective_precision = precision or inferred_precision

    try:
        numbers = tuple(int(part) for part in parts)
        if effective_precision == "year" and len(numbers) >= 1:
            return numbers[0] > current_date.year
        if effective_precision == "month" and len(numbers) >= 2:
            return numbers[:2] > (current_date.year, current_date.month)
        if effective_precision == "day" and len(numbers) >= 3:
            return date(*numbers[:3]) > current_date
    except TypeError, ValueError:
        return False

    return False


def spotify_album_artists(album: dict[str, object]) -> list[AlbumArtist]:
    """Extract all distinct credited artists from Spotify album metadata."""
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
    """Split a list into API-sized batches."""
    return [items[start : start + size] for start in range(0, len(items), size)]


def period_report(stats_history: dict[str, StatsReport]) -> tuple[str, StatsReport]:
    """Return today's report, creating a clean period from the latest report."""
    key = current_stats_history_key()
    if key in stats_history:
        return key, stats_history[key]

    source = next(reversed(stats_history.values()))
    return key, source.model_copy(
        update={
            "albums_stats": source.albums_stats.model_copy(
                update={"removed_albums": 0, "added_albums": 0, "growth": 0.0}
            ),
            "artists_stats": source.artists_stats.model_copy(
                update={"removed_artists": 0, "added_artists": 0, "growth": 0.0}
            ),
            "tracks_stats": source.tracks_stats.model_copy(
                update={"removed_tracks": 0, "added_tracks": 0, "growth": 0.0}
            ),
        }
    )


def sync_stats_history_counts(
    total_albums: int | None = None,
    total_artists: int | None = None,
) -> bool:
    """Synchronize recovery changes with the current stats-history period."""
    stats_history = load_stats_history_file()
    if not stats_history:
        return False

    key, report = period_report(stats_history)
    albums_stats = report.albums_stats
    artists_stats = report.artists_stats

    if total_albums is not None:
        previous_total = (
            albums_stats.total_saved_albums
            - albums_stats.added_albums
            + albums_stats.removed_albums
        )
        albums_stats = albums_stats.model_copy(
            update={
                "total_saved_albums": total_albums,
                "added_albums": max(
                    0,
                    total_albums - previous_total + albums_stats.removed_albums,
                ),
                "growth": calculate_growth(total_albums, previous_total),
            }
        )

    if total_artists is not None:
        previous_total = (
            artists_stats.total_followed_artists
            - artists_stats.added_artists
            + artists_stats.removed_artists
        )
        artists_stats = artists_stats.model_copy(
            update={
                "total_followed_artists": total_artists,
                "added_artists": max(
                    0,
                    total_artists - previous_total + artists_stats.removed_artists,
                ),
                "growth": calculate_growth(total_artists, previous_total),
            }
        )

    followed_artist_count = max(1, artists_stats.total_followed_artists)
    stats_history[key] = report.model_copy(
        update={
            "albums_stats": albums_stats,
            "artists_stats": artists_stats,
            "avg_albums_per_artists": (
                albums_stats.total_saved_albums // followed_artist_count
            ),
            "avg_liked_tracks_per_artists": (
                report.tracks_stats.total_liked_tracks // followed_artist_count
            ),
        }
    )
    save_stats_history(stats_history)
    return True


def add_artists_to_local_files(
    artists: list[AlbumArtist],
    total_artists: list[YourLibraryArtist],
    known_artist_ids: set[str],
) -> set[str]:
    """Persist newly discovered followed artists in one API-sized batch."""
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
    """Live-check, follow, and locally persist all unchecked artists."""
    distinct_artists = {
        artist.spotify_id: artist
        for artist in artists
        if artist.spotify_id not in state.checked_artist_ids
    }
    checked_count = 0
    followed_count = 0

    for artist_batch in chunked(list(distinct_artists.values()), ARTIST_BATCH_SIZE):
        artist_ids = [artist.spotify_id for artist in artist_batch]
        statuses = list(
            retry_call(
                partial(sp.current_user_following_artists, artist_ids),
                f"checking {len(artist_ids)} credited artists",
            )
        )
        if len(statuses) != len(artist_batch):
            raise RuntimeError("Spotify returned an incomplete artist-follow response.")

        missing_artists = [
            artist
            for artist, is_followed in zip(artist_batch, statuses, strict=True)
            if not is_followed
        ]
        if missing_artists and not dry_run:
            retry_call(
                partial(
                    sp.user_follow_artists,
                    [artist.spotify_id for artist in missing_artists],
                ),
                f"following {len(missing_artists)} credited artists",
            )

        if dry_run:
            added_local_ids: set[str] = set()
        else:
            added_local_ids = add_artists_to_local_files(
                artist_batch,
                total_artists,
                known_artist_ids,
            )

        timestamp = datetime.now(UTC).isoformat()
        events: list[dict[str, object]] = []
        for artist, was_followed in zip(artist_batch, statuses, strict=True):
            followed_now = not was_followed
            if followed_now:
                prefix = "Would follow" if dry_run else "Followed"
                echo(f"{prefix} credited artist: {artist.name}")
                followed_count += 1
            events.append(
                {
                    "event": "artist_checked",
                    "checked_at": timestamp,
                    "spotify_id": artist.spotify_id,
                    "artist": artist.name,
                    "was_followed": bool(was_followed),
                    "followed_now": followed_now and not dry_run,
                    "recorded_locally": artist.spotify_id in added_local_ids,
                }
            )

        state.checked_artist_ids.update(artist_ids)
        checked_count += len(artist_batch)
        if not dry_run:
            append_recovery_events(events, recovery_log_path)

    return checked_count, followed_count


def add_album_to_local_files(
    album: dict[str, object],
    record: RemovedAlbumRecord,
    total_albums: list[YourLibraryAlbum],
    known_album_ids: set[str],
) -> bool:
    """Restore one future release to albums_total_new.json when absent."""
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
) -> RecoverySummary:
    """Recover artist follows and future releases from removed-album history."""
    records = load_removed_album_records(removal_log_path)
    state = load_recovery_state(recovery_log_path)
    total_artists = load_total_artists_file()
    total_albums = load_total_albums_new_file()
    known_artist_ids = {artist.spotify_id for artist in total_artists}
    known_album_ids = {album.spotify_id for album in total_albums}
    total_count = len(records)
    completed_count = len(
        state.processed_album_ids.intersection(record.spotify_id for record in records)
    )

    def retry_call[T](operation: Callable[[], T], description: str) -> T:
        return retry_spotify_server_errors(
            operation,
            description,
            echo,
            sleep,
            transient_retry_delay_seconds,
            transient_max_attempts,
        )

    pending_records = [
        record
        for record in records
        if record.spotify_id not in state.processed_album_ids
    ]
    if limit is not None:
        pending_records = pending_records[:limit]
        total_count = completed_count + len(pending_records)
    if progress_callback is not None:
        progress_callback(completed_count, total_count)
    processed_count = 0
    unavailable_count = 0
    multi_artist_count = 0
    artists_checked_count = 0
    artists_followed_count = 0
    future_release_count = 0
    restored_count = 0

    for record_batch in chunked(pending_records, ALBUM_BATCH_SIZE):
        album_ids = [record.spotify_id for record in record_batch]
        response = retry_call(
            partial(sp.albums, album_ids),
            f"fetching metadata for {len(album_ids)} removed albums",
        )
        raw_albums = response.get("albums", [])
        if not isinstance(raw_albums, list):
            raise RuntimeError("Spotify returned an invalid albums response.")
        albums = [*raw_albums, *([None] * (len(record_batch) - len(raw_albums)))]

        batch_artists: list[AlbumArtist] = []
        for album in albums:
            if isinstance(album, dict):
                batch_artists.extend(spotify_album_artists(album))

        checked, followed = ensure_artists_followed(
            sp,
            batch_artists,
            state,
            total_artists,
            known_artist_ids,
            retry_call,
            echo,
            recovery_log_path,
            dry_run,
        )
        artists_checked_count += checked
        artists_followed_count += followed

        for record, album in zip(record_batch, albums, strict=True):
            timestamp = datetime.now(UTC).isoformat()
            if not isinstance(album, dict):
                unavailable_count += 1
                echo(
                    f"Album unavailable from Spotify: {record.album} - {record.artist}"
                )
                event = {
                    "event": "album_processed",
                    "processed_at": timestamp,
                    "status": "unavailable",
                    "spotify_id": record.spotify_id,
                    "album": record.album,
                    "artist": record.artist,
                }
            else:
                artists = spotify_album_artists(album)
                if len(artists) > 1:
                    multi_artist_count += 1
                    names = ", ".join(artist.name for artist in artists)
                    echo(
                        f"Multiple credited artists ({len(artists)}): "
                        f"{album.get('name') or record.album} - {names}"
                    )

                release_date_value = album.get("release_date")
                release_date = (
                    str(release_date_value) if release_date_value is not None else None
                )
                precision_value = album.get("release_date_precision")
                precision = (
                    str(precision_value) if precision_value is not None else None
                )
                future_release = release_is_in_future(
                    release_date,
                    precision,
                    today=today,
                )
                already_saved = False
                restored = False
                local_album_added = False

                if future_release:
                    future_release_count += 1
                    saved_response = retry_call(
                        partial(
                            sp.current_user_saved_albums_contains,
                            [record.spotify_id],
                        ),
                        f"checking future release {record.album}",
                    )
                    already_saved = bool(saved_response[0]) if saved_response else False
                    if not already_saved:
                        if dry_run:
                            echo(
                                f"Would restore future release ({release_date}): "
                                f"{record.album} - {record.artist}"
                            )
                            restored_count += 1
                        else:
                            retry_call(
                                partial(
                                    sp.current_user_saved_albums_add,
                                    [record.spotify_id],
                                ),
                                f"restoring future release {record.album}",
                            )
                            restored = True
                            restored_count += 1

                    if not dry_run:
                        local_album_added = add_album_to_local_files(
                            album,
                            record,
                            total_albums,
                            known_album_ids,
                        )
                        if restored:
                            echo(
                                f"Restored future release ({release_date}): "
                                f"{record.album} - {record.artist}"
                            )
                        elif already_saved:
                            echo(
                                f"Future release already saved ({release_date}): "
                                f"{record.album} - {record.artist}"
                            )

                event = {
                    "event": "album_processed",
                    "processed_at": timestamp,
                    "status": "available",
                    "spotify_id": record.spotify_id,
                    "album": str(album.get("name") or record.album),
                    "artist": record.artist,
                    "credited_artists": [
                        {"spotify_id": artist.spotify_id, "name": artist.name}
                        for artist in artists
                    ],
                    "release_date": release_date,
                    "release_date_precision": precision,
                    "future_release": future_release,
                    "already_saved": already_saved,
                    "restored": restored,
                    "local_album_added": local_album_added,
                }

            if not dry_run:
                append_recovery_events([event], recovery_log_path)
            state.processed_album_ids.add(record.spotify_id)
            completed_count += 1
            processed_count += 1
            if progress_callback is not None:
                progress_callback(completed_count, total_count)

    mode = "Dry run complete" if dry_run else "Recovery complete"
    echo(
        f"{mode}. Processed: {processed_count}. Unavailable: {unavailable_count}. "
        f"Multi-artist albums: {multi_artist_count}. "
        f"Artists checked: {artists_checked_count}. "
        f"Artists followed: {artists_followed_count}. "
        f"Future releases: {future_release_count}. Restored: {restored_count}."
    )
    return RecoverySummary(
        processed=processed_count,
        unavailable=unavailable_count,
        multi_artist_albums=multi_artist_count,
        artists_checked=artists_checked_count,
        artists_followed=artists_followed_count,
        future_releases=future_release_count,
        albums_restored=restored_count,
    )


__all__ = [
    "RECOVERY_LOG_PATH",
    "RecoverySummary",
    "SpotifyRateLimitError",
    "SpotifyTransientServerError",
    "recover_removed_albums",
    "release_is_in_future",
]
