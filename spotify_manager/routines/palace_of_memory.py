"""Fill Palace of Memory from saved albums and Last.fm history."""

from collections.abc import Callable
from datetime import UTC
from datetime import date
from datetime import datetime as datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_values import (
    AlphabeticalCursorUpdate as AlphabeticalCursorUpdate,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemoryConfigError as PalaceOfMemoryConfigError,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemoryDataError as PalaceOfMemoryDataError,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemoryError as PalaceOfMemoryError,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemoryStateError as PalaceOfMemoryStateError,
)
from spotify_manager.application.palace_values import (
    PalaceOfMemorySummary as PalaceOfMemorySummary,
)
from spotify_manager.application.palace_values import (
    SavedAlbumRefresh as SavedAlbumRefresh,
)
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService

# UFI
from spotify_manager.domain import history as history_policy
from spotify_manager.domain import palace_albums
from spotify_manager.domain import palace_history
from spotify_manager.domain.history import HistoricalAlbum as HistoricalAlbum
from spotify_manager.domain.palace_values import (
    HistoricalAlbumSelection as HistoricalAlbumSelection,
)
from spotify_manager.domain.palace_values import PalaceAlbumResult as PalaceAlbumResult
from spotify_manager.domain.palace_values import SelectionAction as SelectionAction
from spotify_manager.domain.palace_values import SelectionSource as SelectionSource
from spotify_manager.domain.palace_values import SpotifyAlbum as SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack as SpotifyFirstTrack
from spotify_manager.infrastructure import palace_catalog
from spotify_manager.infrastructure import palace_cursor
from spotify_manager.infrastructure import palace_files
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


def parse_playlist_id(reference: str | None) -> str:
    """Extract the original configured Palace playlist identity.

    Args:
        reference: Original playlist id, URI or URL.

    Returns:
        Original parsed destination identity.

    Raises:
        PalaceOfMemoryConfigError: The original reference is missing or invalid.
    """
    try:
        return blast_from_past.parse_playlist_id(
            reference,
            "PALACE_OF_MEMORY_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise PalaceOfMemoryConfigError(str(exc)) from exc


def palace_cutoff(today: date | None = None) -> date:
    """Resolve the original previous-year cutoff using the Berlin calendar.

    Args:
        today: Original optional effective local date.

    Returns:
        December 31 of the original previous calendar year.

    Raises:
        ValueError: The original date cannot represent a previous year.
    """
    current_date = today or datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    return palace_history.cutoff(current_date)


def load_saved_albums(path: Path = DEFAULT_ALBUMS_PATH) -> tuple[YourLibraryAlbum, ...]:
    """Load the original complete canonical mirror in file order.

    Args:
        path: Original canonical saved-album JSON location.

    Returns:
        Original validated saved models without sorting the loaded file.

    Raises:
        PalaceOfMemoryDataError: The original file, models or population is invalid.
    """
    return palace_files.load_saved_albums(path, ALPHABETICAL_COUNT)


def _append_refresh_log(path: Path, refresh: SavedAlbumRefresh) -> None:
    """Record every live saved-album preflight, including unchanged mirrors."""
    palace_files.append_audit(path, refresh, "saved-album refresh log")


def refresh_saved_albums(
    spotify: Spotify,
    *,
    path: Path = DEFAULT_ALBUMS_PATH,
    backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
    """Refresh original canonical saved facts before alphabetical selection.

    Args:
        spotify: Caller-owned Spotify client.
        path: Original canonical mirror location.
        backups_dir: Original replaced-mirror backup directory.
        log_path: Original preflight audit location.
        retry_call: Original optional read retry policy.
        progress_callback: Original optional paging presenter.

    Returns:
        Original refreshed mirror and complete preflight outcome.

    Raises:
        PalaceOfMemoryError: Original live paging, replacement or audit fails.
    """
    from spotify_manager.interfaces.operations.palace_of_memory import (
        refresh_saved_albums as operation,
    )

    return operation(
        spotify,
        path=path,
        backups_dir=backups_dir,
        log_path=log_path,
        retry_call=retry_call,
        progress_callback=progress_callback,
    )


def _default_state() -> dict[str, object]:
    """Return an empty Palace cursor state."""
    return {}


def validate_state(payload: object) -> dict[str, object]:
    """Validate original cursor shape while retaining all unknown fields.

    Args:
        payload: Original decoded durable namespace.

    Returns:
        Original complete mutable dictionary, including bool index tolerance.

    Raises:
        PalaceOfMemoryStateError: The original root or fallback index is invalid.
    """
    return palace_cursor.validate_state(payload)


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Read original legacy cursor authority for migration or explicit paths.

    Args:
        path: Original durable cursor location.

    Returns:
        Original validated mutable document, or empty when missing.

    Raises:
        PalaceOfMemoryStateError: The original file cannot be read or validated.
    """
    return palace_cursor.load_state(path)


def _cursor_index(
    payload: dict[str, object],
    albums: tuple[YourLibraryAlbum, ...],
) -> int:
    validate_state(payload)
    last_album_id = str(payload.get("last_alphabetical_album_id") or "")
    fallback = payload.get("next_alphabetical_index", 0)
    if not isinstance(fallback, int) or fallback < 0:
        raise PalaceOfMemoryStateError("Palace state has an invalid index.")
    return palace_albums.cursor_index(albums, last_album_id, fallback)


def _load_cursor(path: Path, albums: tuple[YourLibraryAlbum, ...]) -> int:
    """Resolve the next alphabetical index from legacy durable state."""
    return _cursor_index(load_state(path), albums)


def select_alphabetical_albums(
    albums: tuple[YourLibraryAlbum, ...],
    start_index: int,
    count: int = ALPHABETICAL_COUNT,
) -> tuple[YourLibraryAlbum, ...]:
    """Select original consecutive mirror positions with wraparound.

    Args:
        albums: Original canonical saved-album order.
        start_index: Original starting position.
        count: Original selected count.

    Returns:
        Original complete selected saved-album models.

    Raises:
        ValueError: The original count cannot fit within the mirror.
    """
    return palace_albums.alphabetical(albums, start_index, count)


def resolve_alphabetical_start(
    albums: tuple[YourLibraryAlbum, ...],
    reference: str,
) -> int:
    """Resolve an original position, album reference or exact display label.

    Args:
        albums: Original complete refreshed canonical mirror.
        reference: Original requested manual starting reference.

    Returns:
        Original unambiguous zero-based position.

    Raises:
        PalaceOfMemoryConfigError: The original reference is invalid or ambiguous.
    """
    return palace_cursor.resolve_start(albums, reference)


def rank_albums(
    scrobbles: list[blast_from_past.Scrobble],
) -> tuple[HistoricalAlbum, ...]:
    """Rank loaded scrobbles using the pure historical album policy.

    Args:
        scrobbles: Ordered plays from one date.

    Returns:
        Ranked albums retaining first-seen display names.
    """
    return history_policy.rank_albums(scrobbles)


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
    """Gather original eligible album ranks and Random.org date selections.

    Args:
        count: Original requested historical selection size.
        path: Original complete scrobble export location.
        today: Original optional effective local date.
        random_index_reader: Original caller-owned index reader.
        progress_callback: Original optional stage presenter.

    Returns:
        Original generated time, cutoff, eligible count and ordered album facts.

    Raises:
        PalaceOfMemoryError: Original history, population or random source fails.
        IndexError: An original custom index is out of range.
    """
    from spotify_manager.interfaces.operations.palace_of_memory import (
        select_historical_albums as operation,
    )

    return operation(
        count=count,
        path=path,
        today=today,
        random_index_reader=random_index_reader,
        progress_callback=progress_callback,
    )


def _saved_album_match(
    artist: str,
    album: str,
    saved_albums: tuple[YourLibraryAlbum, ...],
) -> SpotifyAlbum | None:
    return palace_albums.preferred_saved(
        artist, album, saved_albums, ALBUM_MATCH_THRESHOLD
    )


def _spotify_artist_names(raw_album: dict[str, object]) -> tuple[str, ...]:
    """Extract ordered artist names from one Spotify album result."""
    return palace_catalog.artist_names(raw_album)


def search_spotify_album(
    spotify: Spotify,
    artist: str,
    album: str,
    retry_call: RetryCall,
) -> SpotifyAlbum | None:
    """Resolve original exact-artist historical editions by title and search rank.

    Args:
        spotify: Caller-owned Spotify client.
        artist: Original expected artist display spelling.
        album: Original historical album title.
        retry_call: Original read retry boundary.

    Returns:
        Original preferred qualified edition or none for no safe match.

    Raises:
        PalaceOfMemoryDataError: The original search response shape is invalid.
    """
    clean_artist = artist.replace('"', " ").strip()
    clean_album = album.replace('"', " ").strip()
    response = retry_call(
        partial(_search_album, spotify, clean_album, clean_artist),
        f"searching Spotify for {artist} - {album}",
    )
    return palace_albums.preferred_catalog(
        artist,
        album,
        palace_catalog.album_search(response, album),
        ALBUM_MATCH_THRESHOLD,
    )


def load_first_track(
    spotify: Spotify,
    album: SpotifyAlbum,
    retry_call: RetryCall,
) -> SpotifyFirstTrack:
    """Read the original first complete playable marker in response order.

    Args:
        spotify: Caller-owned Spotify client.
        album: Original resolved historical or saved release.
        retry_call: Original read retry boundary.

    Returns:
        Original first complete marker without reordering or paging ahead.

    Raises:
        PalaceOfMemoryDataError: Original track data is invalid or has no marker.
    """
    response = retry_call(
        partial(_first_album_page, spotify, album),
        f"loading the first track of {album.album}",
    )
    return palace_catalog.first_track(response, album)


def _classify_results(
    planned: list[PalaceAlbumResult],
    playlist_track_ids: frozenset[str],
) -> tuple[tuple[PalaceAlbumResult, ...], tuple[SpotifyFirstTrack, ...]]:
    return palace_albums.classify(planned, playlist_track_ids)


def _save_cursor(
    path: Path,
    next_index: int,
    last_album: YourLibraryAlbum,
) -> None:
    """Atomically persist the next alphabetical position."""
    save_state(_cursor_payload(next_index, last_album), path)


def _cursor_payload(
    next_index: int,
    last_album: YourLibraryAlbum,
) -> dict[str, object]:
    """Build the complete durable Palace cursor payload."""
    return palace_cursor.cursor_record(next_index, last_album, datetime.now(UTC))


def save_state(
    payload: dict[str, object],
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Atomically replace original complete legacy cursor authority.

    Args:
        payload: Original complete replacement namespace.
        path: Original durable cursor location.

    Raises:
        PalaceOfMemoryStateError: Original validation or replacement fails.
    """
    palace_cursor.save_state(payload, path)


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="palace_of_memory",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def set_alphabetical_cursor(
    spotify: Spotify,
    position: int,
    *,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    album_backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    album_refresh_log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AlphabeticalCursorUpdate:
    """Refresh live facts before persisting the original manual next position.

    Args:
        spotify: Caller-owned Spotify client.
        position: Original one-based requested next position.
        albums_path: Original canonical mirror location.
        state_path: Original cursor location.
        state_service: Original optional shared state authority.
        album_backups_dir: Original mirror backup directory.
        album_refresh_log_path: Original live preflight audit location.
        retry_call: Original optional retry policy.
        progress_callback: Original optional stage presenter.

    Returns:
        Original next position, full saved model and live preflight outcome.

    Raises:
        PalaceOfMemoryError: Original preflight, position or checkpoint fails.
    """
    from spotify_manager.interfaces.operations.palace_of_memory import (
        set_alphabetical_cursor as operation,
    )

    return operation(
        spotify,
        position,
        albums_path=albums_path,
        state_path=state_path,
        state_service=state_service,
        album_backups_dir=album_backups_dir,
        album_refresh_log_path=album_refresh_log_path,
        retry_call=retry_call,
        progress_callback=progress_callback,
    )


def _append_log(path: Path, summary: PalaceOfMemorySummary) -> None:
    """Append one completed real run to the audit log."""
    palace_files.append_audit(path, summary, "Palace log")


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
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    album_backups_dir: Path = DEFAULT_ALBUM_BACKUPS_DIR,
    album_refresh_log_path: Path = DEFAULT_ALBUM_REFRESH_LOG_PATH,
    random_index_reader: RandomIndexReader = blast_from_past.fetch_random_indexes,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    echo: Echo = print,
) -> PalaceOfMemorySummary:
    """Gather original alphabetical and historical markers and apply live authority.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Original destination identity.
        dry_run: Original preview behavior, including live mirror publication.
        alphabetical_start: Original optional manual starting reference.
        today: Original optional effective local date.
        albums_path: Original canonical saved mirror location.
        scrobbles_path: Original full scrobble export location.
        state_path: Original cursor location.
        state_service: Original optional shared cursor authority.
        log_path: Original successful completion audit location.
        album_backups_dir: Original mirror backup directory.
        album_refresh_log_path: Original preflight audit location.
        random_index_reader: Original caller-owned historical index reader.
        retry_call: Original retry policy, including append retries.
        progress_callback: Original optional stage presenter.
        echo: Original accepted-append presenter.

    Returns:
        Original complete ordered selection, live classification and refresh outcome.

    Raises:
        PalaceOfMemoryError: Original preflight, selection, checkpoint or audit fails.
    """
    from spotify_manager.interfaces.operations.palace_of_memory import (
        fill_palace_of_memory as operation,
    )

    return operation(
        spotify,
        playlist_id,
        dry_run=dry_run,
        alphabetical_start=alphabetical_start,
        today=today,
        albums_path=albums_path,
        scrobbles_path=scrobbles_path,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        album_backups_dir=album_backups_dir,
        album_refresh_log_path=album_refresh_log_path,
        random_index_reader=random_index_reader,
        retry_call=retry_call,
        progress_callback=progress_callback,
        echo=echo,
    )


def _direct_retry(operation: Callable[[], object], _description: str) -> object:
    return operation()


def _read_palace_playlist(
    spotify: Spotify,
    playlist_id: str,
    retry: RetryCall,
    recheck: bool,
) -> blast_from_past.PlaylistState:
    description = (
        "rechecking Palace of Memory" if recheck else "loading Palace of Memory"
    )
    playlist = retry(
        partial(blast_from_past.load_playlist_state, spotify, playlist_id), description
    )
    if not isinstance(playlist, blast_from_past.PlaylistState):
        raise PalaceOfMemoryDataError("Spotify returned invalid Palace playlist data.")
    return playlist


def _append_first_tracks(
    spotify: Spotify,
    playlist_id: str,
    pending: tuple[SpotifyFirstTrack, ...],
    retry: RetryCall,
) -> None:
    retry(
        partial(_post_first_tracks, spotify, playlist_id, pending),
        "adding first tracks to Palace of Memory",
    )


def _post_first_tracks(
    spotify: Spotify,
    playlist_id: str,
    pending: tuple[SpotifyFirstTrack, ...],
) -> object:
    return spotify._post(
        f"playlists/{playlist_id}/items",
        payload={"uris": [track.uri for track in pending]},
    )


def _read_saved_album_page(
    spotify: Spotify,
    current_offset: int,
) -> object:
    return spotify.current_user_saved_albums(
        limit=SAVED_ALBUM_PAGE_SIZE,
        offset=current_offset,
    )


def _replace_saved_albums(
    path: Path,
    backups_dir: Path,
    refreshed: tuple[YourLibraryAlbum, ...],
) -> str | None:
    return palace_files.replace_saved_albums(
        path,
        backups_dir,
        refreshed,
        partial(datetime.now, UTC),
        library_analysis.write_models,
    )


def _search_album(spotify: Spotify, clean_album: str, clean_artist: str) -> object:
    return spotify.search(
        q=f'album:"{clean_album}" artist:"{clean_artist}"',
        type="album",
        limit=SPOTIFY_SEARCH_LIMIT,
        offset=0,
    )


def _first_album_page(spotify: Spotify, album: SpotifyAlbum) -> object:
    return spotify.album_tracks(album.spotify_id, limit=50, offset=0)
