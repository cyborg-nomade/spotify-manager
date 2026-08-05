"""Fill Palace of Memory from saved albums and Last.fm history."""

import json
import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Literal

from spotipy import Spotify

# UFI
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import analyse_library as library_analysis
from spotify_manager.routines import blast_from_past


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_ALBUMS_PATH = FILES_DIR / "albums_total_new.json"
DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH
DEFAULT_STATE_PATH = FILES_DIR / "palace_of_memory_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "palace_of_memory_log.jsonl"
DEFAULT_ALBUM_BACKUPS_DIR = FILES_DIR / "palace_of_memory_album_backups"
DEFAULT_ALBUM_REFRESH_LOG_PATH = FILES_DIR / "palace_of_memory_album_refresh_log.jsonl"
ALPHABETICAL_COUNT = 5
HISTORY_COUNT = 5
SAVED_ALBUM_PAGE_SIZE = 50
SPOTIFY_SEARCH_LIMIT = 10
ALBUM_MATCH_THRESHOLD = 0.9

ProgressCallback = Callable[[str], None]
Echo = Callable[[str], None]
RetryCall = Callable[[Callable[[], object], str], object]
RandomIndexReader = Callable[[int, int], blast_from_past.RandomIndexSet]
SelectionSource = Literal["alphabetical", "history"]
SelectionAction = Literal[
    "added",
    "already present",
    "duplicate selection",
    "no match",
]


class PalaceOfMemoryError(RuntimeError):
    """Base error for Palace of Memory runs."""


class PalaceOfMemoryConfigError(PalaceOfMemoryError):
    """Raised when the playlist setting is missing or invalid."""


class PalaceOfMemoryDataError(PalaceOfMemoryError):
    """Raised when a local mirror or Spotify response is unusable."""


class PalaceOfMemoryStateError(PalaceOfMemoryError):
    """Raised when the alphabetical cursor cannot be read or persisted."""


@dataclass(frozen=True)
class HistoricalAlbum:
    """One album in a date's Last.fm ranking."""

    artist: str
    album: str
    scrobbles: int


@dataclass(frozen=True)
class HistoricalAlbumSelection:
    """One Random.org date mapped to a ranked Last.fm album."""

    selected_date: date
    date_index: int
    albums_on_date: int
    position: int
    album: HistoricalAlbum


@dataclass(frozen=True)
class SpotifyAlbum:
    """One Spotify album selected for first-track resolution."""

    spotify_id: str
    uri: str
    artist: str
    album: str
    saved: bool
    similarity: float


@dataclass(frozen=True)
class SpotifyFirstTrack:
    """The first playable track in Spotify disc and track order."""

    spotify_id: str
    uri: str
    name: str


@dataclass(frozen=True)
class PalaceAlbumResult:
    """One alphabetical or historical album selection and its outcome."""

    source: SelectionSource
    artist: str
    album: str
    spotify_album: SpotifyAlbum | None
    first_track: SpotifyFirstTrack | None
    action: SelectionAction
    selected_date: date | None = None
    date_index: int | None = None
    albums_on_date: int | None = None
    history_position: int | None = None
    scrobbles: int | None = None


@dataclass(frozen=True)
class SavedAlbumRefresh:
    """Result of rebuilding the canonical saved-album mirror."""

    checked_at: datetime
    previous: int
    current: int
    added: int
    removed: int
    skipped: int
    persisted: bool
    backup_path: str | None


@dataclass(frozen=True)
class AlphabeticalCursorUpdate:
    """A manually persisted next position in the saved-album ordering."""

    next_index: int
    next_album: YourLibraryAlbum
    album_refresh: SavedAlbumRefresh


@dataclass(frozen=True)
class PalaceOfMemorySummary:
    """Completed Palace of Memory planning or mutation."""

    generated_at: datetime
    playlist_id: str
    dry_run: bool
    cutoff_date: date
    available_dates: int
    alphabetical_start_index: int
    alphabetical_next_index: int
    alphabetical_cursor_overridden: bool
    playlist_length_before: int
    playlist_length_after: int
    album_refresh: SavedAlbumRefresh
    results: tuple[PalaceAlbumResult, ...]

    @property
    def added(self) -> int:
        """Return the number of first tracks added or projected."""
        return sum(result.action == "added" for result in self.results)


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Palace of Memory playlist id."""
    try:
        return blast_from_past.parse_playlist_id(
            reference,
            "PALACE_OF_MEMORY_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise PalaceOfMemoryConfigError(str(exc)) from exc


def palace_cutoff(today: date | None = None) -> date:
    """Return December 31 of the year before the current year."""
    current_date = today or datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    return date(current_date.year - 1, 12, 31)


def load_saved_albums(path: Path = DEFAULT_ALBUMS_PATH) -> tuple[YourLibraryAlbum, ...]:
    """Load the alphabetically ordered saved-album mirror."""
    try:
        with path.open(encoding="utf-8") as album_file:
            payload = json.load(album_file)
    except OSError as exc:
        raise PalaceOfMemoryDataError(f"Could not read saved albums: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PalaceOfMemoryDataError(
            f"Saved albums are invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {path}"
        ) from exc
    if not isinstance(payload, list):
        raise PalaceOfMemoryDataError(f"Saved albums must be a JSON list: {path}")
    try:
        albums = tuple(YourLibraryAlbum.model_validate(item) for item in payload)
    except (TypeError, ValueError) as exc:
        raise PalaceOfMemoryDataError(f"Saved albums are invalid: {path}") from exc
    if len(albums) < ALPHABETICAL_COUNT:
        raise PalaceOfMemoryDataError(
            f"At least {ALPHABETICAL_COUNT} saved albums are required."
        )
    return albums


def _append_refresh_log(path: Path, refresh: SavedAlbumRefresh) -> None:
    """Record every live saved-album preflight, including unchanged mirrors."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(
                json.dumps(
                    asdict(refresh),
                    ensure_ascii=False,
                    default=lambda value: value.isoformat(),
                )
                + "\n"
            )
    except OSError as exc:
        raise PalaceOfMemoryStateError(
            f"Could not write saved-album refresh log: {path}"
        ) from exc


def refresh_saved_albums(
    spotify: Spotify,
    *,
    path: Path = DEFAULT_ALBUMS_PATH,
    backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
    """Rebuild the canonical saved-album mirror from Spotify before selection."""
    retry = retry_call or (lambda operation, _description: operation())
    try:
        previous = load_saved_albums(path) if path.exists() else ()
    except PalaceOfMemoryDataError:
        previous = ()

    albums: list[YourLibraryAlbum] = []
    skipped = 0
    offset = 0
    while True:
        if progress_callback is not None:
            progress_callback(f"Refreshing saved albums at offset {offset}")

        def load_page(current_offset: int = offset) -> object:
            return spotify.current_user_saved_albums(
                limit=SAVED_ALBUM_PAGE_SIZE,
                offset=current_offset,
            )

        response = retry(
            load_page,
            f"refreshing saved albums at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise PalaceOfMemoryDataError(
                f"Spotify returned an invalid saved-album page at offset {offset}."
            )
        raw_items = response["items"]
        converted = [
            album
            for raw_item in raw_items
            if (album := library_analysis.album_from_saved_item(raw_item)) is not None
        ]
        albums.extend(converted)
        skipped += len(raw_items) - len(converted)
        offset += len(raw_items)
        if not raw_items and response.get("next"):
            raise PalaceOfMemoryDataError(
                "Spotify returned an empty saved-album page with a next link."
            )
        if not raw_items or not response.get("next"):
            break

    refreshed = tuple(
        sorted(
            library_analysis.deduplicate_models(albums),
            key=library_analysis.album_sort_key,
        )
    )
    if len(refreshed) < ALPHABETICAL_COUNT:
        raise PalaceOfMemoryDataError(
            f"Spotify returned fewer than {ALPHABETICAL_COUNT} saved albums."
        )

    previous_ids = {album.spotify_id for album in previous}
    current_ids = {album.spotify_id for album in refreshed}
    changed = tuple(previous) != refreshed
    backup_path: Path | None = None
    if changed:
        try:
            if path.exists():
                backups_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backups_dir / (
                    datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                    + "-albums_total_new.json"
                )
                shutil.copy2(path, backup_path)
            library_analysis.write_models(path, refreshed)
        except OSError as exc:
            raise PalaceOfMemoryStateError(
                f"Could not publish refreshed saved albums: {path}"
            ) from exc

    refresh = SavedAlbumRefresh(
        checked_at=datetime.now(UTC),
        previous=len(previous),
        current=len(refreshed),
        added=len(current_ids - previous_ids),
        removed=len(previous_ids - current_ids),
        skipped=skipped,
        persisted=changed,
        backup_path=str(backup_path) if backup_path is not None else None,
    )
    _append_refresh_log(log_path, refresh)
    return refreshed, refresh


def _load_cursor(path: Path, albums: tuple[YourLibraryAlbum, ...]) -> int:
    """Resolve the next alphabetical index from durable state."""
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8") as state_file:
            payload = json.load(state_file)
    except OSError as exc:
        raise PalaceOfMemoryStateError(f"Could not read Palace state: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PalaceOfMemoryStateError(
            f"Palace state is invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise PalaceOfMemoryStateError(f"Palace state must be an object: {path}")

    last_album_id = str(payload.get("last_alphabetical_album_id") or "")
    if last_album_id:
        for index, album in enumerate(albums):
            if album.spotify_id == last_album_id:
                return (index + 1) % len(albums)

    fallback = payload.get("next_alphabetical_index", 0)
    if not isinstance(fallback, int) or fallback < 0:
        raise PalaceOfMemoryStateError(
            f"Palace state has an invalid alphabetical index: {path}"
        )
    return fallback % len(albums)


def select_alphabetical_albums(
    albums: tuple[YourLibraryAlbum, ...],
    start_index: int,
    count: int = ALPHABETICAL_COUNT,
) -> tuple[YourLibraryAlbum, ...]:
    """Select the next saved albums, wrapping at the end of the mirror."""
    if count < 1 or count > len(albums):
        raise ValueError("count must fit within the saved album mirror")
    return tuple(
        albums[(start_index + offset) % len(albums)] for offset in range(count)
    )


def resolve_alphabetical_start(
    albums: tuple[YourLibraryAlbum, ...],
    reference: str,
) -> int:
    """Resolve a manual 1-based position, Spotify id, or exact album label."""
    value = reference.strip()
    if not value:
        raise PalaceOfMemoryConfigError("Alphabetical start cannot be empty.")

    if value.isdecimal():
        position = int(value)
        if not 1 <= position <= len(albums):
            raise PalaceOfMemoryConfigError(
                f"Alphabetical position must be between 1 and {len(albums)}."
            )
        return position - 1

    spotify_id = value
    if value.startswith("spotify:album:"):
        spotify_id = value.removeprefix("spotify:album:").split("?", 1)[0]
    elif "open.spotify.com/album/" in value:
        spotify_id = value.split("open.spotify.com/album/", 1)[1]
        spotify_id = spotify_id.split("?", 1)[0].split("/", 1)[0]
    for index, album in enumerate(albums):
        if album.spotify_id == spotify_id:
            return index

    exact_value = " ".join(value.casefold().split())
    matches = [
        index
        for index, album in enumerate(albums)
        if " ".join(album.album.casefold().split()) == exact_value
        or " ".join(f"{album.artist} - {album.album}".casefold().split()) == exact_value
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        examples = "; ".join(
            f"{albums[index].artist} - {albums[index].album} "
            f"({albums[index].spotify_id})"
            for index in matches[:5]
        )
        raise PalaceOfMemoryConfigError(
            f"Alphabetical start is ambiguous; use a Spotify album id: {examples}"
        )
    raise PalaceOfMemoryConfigError(
        f"Alphabetical start was not found in the refreshed saved albums: {reference}"
    )


def rank_albums(
    scrobbles: list[blast_from_past.Scrobble],
) -> tuple[HistoricalAlbum, ...]:
    """Reproduce a date's album ranking by descending scrobble count."""
    names: dict[tuple[str, str], tuple[str, str]] = {}
    counts: Counter[tuple[str, str]] = Counter()
    for scrobble in scrobbles:
        if not scrobble.album.strip():
            continue
        key = (
            blast_from_past.normalize_name(scrobble.artist),
            blast_from_past.normalize_name(scrobble.album),
        )
        if not all(key):
            continue
        names.setdefault(key, (scrobble.artist, scrobble.album))
        counts[key] += 1
    ranked = [
        HistoricalAlbum(
            artist=names[key][0],
            album=names[key][1],
            scrobbles=count,
        )
        for key, count in counts.items()
    ]
    ranked.sort(
        key=lambda item: (
            -item.scrobbles,
            blast_from_past.normalize_name(item.album),
            blast_from_past.normalize_name(item.artist),
        )
    )
    return tuple(ranked)


def select_historical_albums(
    *,
    count: int = HISTORY_COUNT,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = blast_from_past.fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
) -> tuple[
    datetime,
    date,
    int,
    tuple[HistoricalAlbumSelection, ...],
]:
    """Select ranked albums from unique Random.org dates."""
    if progress_callback is not None:
        progress_callback("Loading Last.fm album history")
    try:
        scrobbles_by_date = blast_from_past.load_scrobbles_by_date(path)
    except blast_from_past.LastFmExportError as exc:
        raise PalaceOfMemoryDataError(str(exc)) from exc
    cutoff = palace_cutoff(today)
    rankings = {
        scrobble_date: ranked
        for scrobble_date, scrobbles in scrobbles_by_date.items()
        if blast_from_past.FIRST_ELIGIBLE_DATE <= scrobble_date <= cutoff
        and (ranked := rank_albums(scrobbles))
    }
    available_dates = sorted(rankings)
    if count > len(available_dates):
        raise PalaceOfMemoryDataError(
            f"Only {len(available_dates)} album-bearing dates are available "
            f"through {cutoff.isoformat()}."
        )

    if progress_callback is not None:
        progress_callback("Requesting five unique date indexes from Random.org")
    try:
        random_indexes = random_index_reader(len(available_dates), count)
    except (ValueError, blast_from_past.RandomOrgError) as exc:
        raise PalaceOfMemoryError(str(exc)) from exc

    selections: list[HistoricalAlbumSelection] = []
    for date_index in random_indexes.indexes:
        selected_date = available_dates[date_index]
        albums = rankings[selected_date]
        selected_offset = random_indexes.generated_at.second % len(albums)
        selections.append(
            HistoricalAlbumSelection(
                selected_date=selected_date,
                date_index=date_index,
                albums_on_date=len(albums),
                position=selected_offset + 1,
                album=albums[selected_offset],
            )
        )
    return (
        random_indexes.generated_at,
        cutoff,
        len(available_dates),
        tuple(selections),
    )


def _saved_album_match(
    artist: str,
    album: str,
    saved_albums: tuple[YourLibraryAlbum, ...],
) -> SpotifyAlbum | None:
    """Prefer an edition already present in the saved-album mirror."""
    expected_artist = blast_from_past.normalize_name(artist)
    candidates: list[SpotifyAlbum] = []
    for saved in saved_albums:
        if blast_from_past.normalize_name(saved.artist) != expected_artist:
            continue
        similarity = blast_from_past.name_similarity(album, saved.album)
        if similarity < ALBUM_MATCH_THRESHOLD:
            continue
        candidates.append(
            SpotifyAlbum(
                spotify_id=saved.spotify_id,
                uri=saved.uri,
                artist=saved.artist,
                album=saved.album,
                saved=True,
                similarity=similarity,
            )
        )
    return max(candidates, key=lambda item: item.similarity, default=None)


def _spotify_artist_names(raw_album: dict[str, object]) -> tuple[str, ...]:
    """Extract ordered artist names from one Spotify album result."""
    raw_artists = raw_album.get("artists")
    if not isinstance(raw_artists, list):
        return ()
    return tuple(
        str(raw_artist.get("name"))
        for raw_artist in raw_artists
        if isinstance(raw_artist, dict) and raw_artist.get("name")
    )


def search_spotify_album(
    spotify: Spotify,
    artist: str,
    album: str,
    retry_call: RetryCall,
) -> SpotifyAlbum | None:
    """Resolve one historical album with exact artist and 90% album matching."""
    clean_artist = artist.replace('"', " ").strip()
    clean_album = album.replace('"', " ").strip()
    response = retry_call(
        lambda: spotify.search(
            q=f'album:"{clean_album}" artist:"{clean_artist}"',
            type="album",
            limit=SPOTIFY_SEARCH_LIMIT,
            offset=0,
        ),
        f"searching Spotify for {artist} - {album}",
    )
    if not isinstance(response, dict):
        raise PalaceOfMemoryDataError(
            f"Spotify returned invalid search data for {album}."
        )
    page = response.get("albums")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise PalaceOfMemoryDataError(
            f"Spotify returned invalid search data for {album}."
        )

    expected_artist = blast_from_past.normalize_name(artist)
    matches: list[tuple[int, SpotifyAlbum]] = []
    for rank, raw_album in enumerate(page["items"], start=1):
        if not isinstance(raw_album, dict):
            continue
        spotify_id = str(raw_album.get("id") or "").strip()
        uri = str(raw_album.get("uri") or "").strip()
        album_name = str(raw_album.get("name") or "").strip()
        artists = _spotify_artist_names(raw_album)
        if not spotify_id or not uri or not album_name or not artists:
            continue
        if not any(
            blast_from_past.normalize_name(name) == expected_artist for name in artists
        ):
            continue
        similarity = blast_from_past.name_similarity(album, album_name)
        if similarity < ALBUM_MATCH_THRESHOLD:
            continue
        matches.append(
            (
                rank,
                SpotifyAlbum(
                    spotify_id=spotify_id,
                    uri=uri,
                    artist=artists[0],
                    album=album_name,
                    saved=False,
                    similarity=similarity,
                ),
            )
        )
    if not matches:
        return None
    return max(matches, key=lambda item: (item[1].similarity, -item[0]))[1]


def load_first_track(
    spotify: Spotify,
    album: SpotifyAlbum,
    retry_call: RetryCall,
) -> SpotifyFirstTrack:
    """Load the first playable track without reordering Spotify's response."""
    response = retry_call(
        lambda: spotify.album_tracks(album.spotify_id, limit=50, offset=0),
        f"loading the first track of {album.album}",
    )
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise PalaceOfMemoryDataError(
            f"Spotify returned invalid tracks for {album.artist} - {album.album}."
        )
    for raw_track in response["items"]:
        if not isinstance(raw_track, dict):
            continue
        spotify_id = str(raw_track.get("id") or "").strip()
        uri = str(raw_track.get("uri") or "").strip()
        name = str(raw_track.get("name") or "").strip()
        if spotify_id and uri and name:
            return SpotifyFirstTrack(spotify_id=spotify_id, uri=uri, name=name)
    raise PalaceOfMemoryDataError(
        f"No playable first track found for {album.artist} - {album.album}."
    )


def _classify_results(
    planned: list[PalaceAlbumResult],
    playlist_track_ids: frozenset[str],
) -> tuple[tuple[PalaceAlbumResult, ...], tuple[SpotifyFirstTrack, ...]]:
    """Classify resolved first tracks against current and pending tracks."""
    results: list[PalaceAlbumResult] = []
    pending: list[SpotifyFirstTrack] = []
    pending_ids: set[str] = set()
    for result in planned:
        track = result.first_track
        if result.spotify_album is None or track is None:
            action: SelectionAction = "no match"
        elif track.spotify_id in playlist_track_ids:
            action = "already present"
        elif track.spotify_id in pending_ids:
            action = "duplicate selection"
        else:
            action = "added"
            pending_ids.add(track.spotify_id)
            pending.append(track)
        results.append(replace(result, action=action))
    return tuple(results), tuple(pending)


def _save_cursor(
    path: Path,
    next_index: int,
    last_album: YourLibraryAlbum,
) -> None:
    """Atomically persist the next alphabetical position."""
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "next_alphabetical_index": next_index,
        "last_alphabetical_album_id": last_album.spotify_id,
        "last_alphabetical_artist": last_album.artist,
        "last_alphabetical_album": last_album.album,
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as state_file:
            json.dump(payload, state_file, ensure_ascii=False, indent=2)
            state_file.write("\n")
        temporary.replace(path)
    except OSError as exc:
        raise PalaceOfMemoryStateError(f"Could not save Palace state: {path}") from exc


def set_alphabetical_cursor(
    spotify: Spotify,
    position: int,
    *,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    album_backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    album_refresh_log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AlphabeticalCursorUpdate:
    """Refresh saved albums and persist a 1-based next alphabetical position."""
    retry = retry_call or (lambda operation, _description: operation())
    if progress_callback is not None:
        progress_callback("Refreshing the saved-album mirror")
    albums, album_refresh = refresh_saved_albums(
        spotify,
        path=albums_path,
        backups_dir=album_backups_dir,
        log_path=album_refresh_log_path,
        retry_call=retry,
        progress_callback=progress_callback,
    )
    if not 1 <= position <= len(albums):
        raise PalaceOfMemoryConfigError(
            f"Alphabetical cursor must be between 1 and {len(albums)}."
        )

    next_index = position - 1
    previous_album = albums[(next_index - 1) % len(albums)]
    _save_cursor(state_path, next_index, previous_album)
    return AlphabeticalCursorUpdate(
        next_index=next_index,
        next_album=albums[next_index],
        album_refresh=album_refresh,
    )


def _append_log(path: Path, summary: PalaceOfMemorySummary) -> None:
    """Append one completed real run to the audit log."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(
                json.dumps(
                    asdict(summary),
                    ensure_ascii=False,
                    default=lambda value: value.isoformat(),
                )
                + "\n"
            )
    except OSError as exc:
        raise PalaceOfMemoryStateError(f"Could not write Palace log: {path}") from exc


def fill_palace_of_memory(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool = False,
    alphabetical_start: str | None = None,
    today: date | None = None,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    album_backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    album_refresh_log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    random_index_reader: RandomIndexReader = blast_from_past.fetch_random_indexes,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    echo: Echo = print,
) -> PalaceOfMemorySummary:
    """Add five alphabetical and five historical album first tracks."""
    retry = retry_call or (lambda operation, _description: operation())
    if progress_callback is not None:
        progress_callback("Refreshing the saved-album mirror")
    saved_albums, album_refresh = refresh_saved_albums(
        spotify,
        path=albums_path,
        backups_dir=album_backups_dir,
        log_path=album_refresh_log_path,
        retry_call=retry,
        progress_callback=progress_callback,
    )
    start_index = (
        resolve_alphabetical_start(saved_albums, alphabetical_start)
        if alphabetical_start is not None
        else _load_cursor(state_path, saved_albums)
    )
    alphabetical = select_alphabetical_albums(saved_albums, start_index)
    next_index = (start_index + len(alphabetical)) % len(saved_albums)

    generated_at, cutoff, available_dates, historical = select_historical_albums(
        path=scrobbles_path,
        today=today,
        random_index_reader=random_index_reader,
        progress_callback=progress_callback,
    )

    if progress_callback is not None:
        progress_callback("Loading Palace of Memory")
    playlist = retry(
        lambda: blast_from_past.load_playlist_state(spotify, playlist_id),
        "loading Palace of Memory",
    )
    if not isinstance(playlist, blast_from_past.PlaylistState):
        raise PalaceOfMemoryDataError("Spotify returned invalid Palace playlist data.")

    planned: list[PalaceAlbumResult] = []
    track_cache: dict[str, SpotifyFirstTrack] = {}
    for index, album in enumerate(alphabetical, start=1):
        if progress_callback is not None:
            progress_callback(f"Loading alphabetical album {index}/{len(alphabetical)}")
        spotify_album = SpotifyAlbum(
            spotify_id=album.spotify_id,
            uri=album.uri,
            artist=album.artist,
            album=album.album,
            saved=True,
            similarity=1.0,
        )
        track = track_cache.get(spotify_album.spotify_id)
        if track is None:
            track = load_first_track(spotify, spotify_album, retry)
            track_cache[spotify_album.spotify_id] = track
        planned.append(
            PalaceAlbumResult(
                source="alphabetical",
                artist=album.artist,
                album=album.album,
                spotify_album=spotify_album,
                first_track=track,
                action="added",
            )
        )

    for index, selection in enumerate(historical, start=1):
        if progress_callback is not None:
            progress_callback(f"Resolving historical album {index}/{len(historical)}")
        selected = selection.album
        historical_album = _saved_album_match(
            selected.artist,
            selected.album,
            saved_albums,
        )
        if historical_album is None:
            historical_album = search_spotify_album(
                spotify,
                selected.artist,
                selected.album,
                retry,
            )
        historical_track = None
        if historical_album is not None:
            historical_track = track_cache.get(historical_album.spotify_id)
            if historical_track is None:
                historical_track = load_first_track(spotify, historical_album, retry)
                track_cache[historical_album.spotify_id] = historical_track
        planned.append(
            PalaceAlbumResult(
                source="history",
                artist=selected.artist,
                album=selected.album,
                spotify_album=historical_album,
                first_track=historical_track,
                action="added" if historical_track is not None else "no match",
                selected_date=selection.selected_date,
                date_index=selection.date_index,
                albums_on_date=selection.albums_on_date,
                history_position=selection.position,
                scrobbles=selected.scrobbles,
            )
        )

    final_playlist = playlist
    results, pending = _classify_results(planned, playlist.track_ids)
    if not dry_run:
        if progress_callback is not None:
            progress_callback("Rechecking Palace of Memory")
        current_playlist = retry(
            lambda: blast_from_past.load_playlist_state(spotify, playlist_id),
            "rechecking Palace of Memory",
        )
        if not isinstance(current_playlist, blast_from_past.PlaylistState):
            raise PalaceOfMemoryDataError(
                "Spotify returned invalid Palace playlist data."
            )
        final_playlist = current_playlist
        results, pending = _classify_results(planned, current_playlist.track_ids)
        if pending:
            if progress_callback is not None:
                progress_callback(f"Adding {len(pending)} first tracks to Palace")
            retry(
                lambda: spotify._post(
                    f"playlists/{playlist_id}/items",
                    payload={"uris": [track.uri for track in pending]},
                ),
                "adding first tracks to Palace of Memory",
            )
            echo(f"Added {len(pending)} first tracks to Palace of Memory.")

    summary = PalaceOfMemorySummary(
        generated_at=generated_at,
        playlist_id=playlist_id,
        dry_run=dry_run,
        cutoff_date=cutoff,
        available_dates=available_dates,
        alphabetical_start_index=start_index,
        alphabetical_next_index=next_index,
        alphabetical_cursor_overridden=alphabetical_start is not None,
        playlist_length_before=final_playlist.total_items,
        playlist_length_after=final_playlist.total_items + len(pending),
        album_refresh=album_refresh,
        results=results,
    )
    if not dry_run:
        _save_cursor(state_path, next_index, alphabetical[-1])
        _append_log(log_path, summary)
    return summary
