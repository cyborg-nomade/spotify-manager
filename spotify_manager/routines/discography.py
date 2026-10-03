"""Public Discography compatibility facade and original synchronous SDK seams."""

from collections.abc import Callable
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast

from spotipy import Spotify

from spotify_manager.application.discography_values import (
    DiscographyCancelledError as DiscographyCancelledError,
)
from spotify_manager.application.discography_values import (
    DiscographyConfigError as DiscographyConfigError,
)
from spotify_manager.application.discography_values import (
    DiscographyError as DiscographyError,
)
from spotify_manager.application.discography_values import (
    DiscographyRunSummary as DiscographyRunSummary,
)
from spotify_manager.application.discography_values import (
    DiscographyStateError as DiscographyStateError,
)
from spotify_manager.bootstrap import discography as composition
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain import discography_batches
from spotify_manager.domain import discography_catalog
from spotify_manager.domain import discography_history
from spotify_manager.domain.discography_values import QUEUE_ORDER as QUEUE_ORDER
from spotify_manager.domain.discography_values import (
    START_QUEUE_ROTATION as START_QUEUE_ROTATION,
)
from spotify_manager.domain.discography_values import ArtistMarkers as ArtistMarkers
from spotify_manager.domain.discography_values import ArtistSelection as ArtistSelection
from spotify_manager.domain.discography_values import CatalogRelease as CatalogRelease
from spotify_manager.domain.discography_values import DiscographyPlan as DiscographyPlan
from spotify_manager.domain.discography_values import (
    HistoricalArtist as HistoricalArtist,
)
from spotify_manager.domain.discography_values import (
    HistoricalArtistSelection as HistoricalArtistSelection,
)
from spotify_manager.domain.discography_values import MarkerQueueName as MarkerQueueName
from spotify_manager.domain.discography_values import QueueArtist as QueueArtist
from spotify_manager.domain.discography_values import QueueName as QueueName
from spotify_manager.infrastructure import discography_files
from spotify_manager.infrastructure import discography_records
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_wine
from spotify_manager.routines import something_old


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "discography_routine_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "discography_routine_log.jsonl"
DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH
STATE_VERSION = 1
RELEASE_PAGE_LIMIT = 10
SAVED_ALBUM_BATCH_SIZE = 20
PLAYLIST_MUTATION_BATCH_SIZE = 100
WEEK_RELEASES = 10

QUEUE_LABELS: dict[MarkerQueueName, str] = {
    "newfoundland": "Newfoundland",
    "memory_lane": "Memory Lane",
    "requeue": "The Requeue",
    "queue_3": "The Queue 3",
}
RetryCall = Callable[[Callable[[], object], str], object]
ReleaseSelector = Callable[[QueueArtist, tuple[CatalogRelease, ...]], tuple[str, ...]]
ProgressCallback = Callable[[str], None]
RandomIndexReader = Callable[[int, int], blast_from_past.RandomIndexSet]
HistoricalArtistChoiceReader = something_old.ArtistSearchChoiceReader
LIVE_PATTERN = discography_records.LIVE_PATTERN
COMPILATION_PATTERN = discography_records.COMPILATION_PATTERN


def parse_playlist_id(reference: str | None, setting_name: str) -> str:
    """Extract a playlist id and translate shared configuration errors.

    Args:
        reference: Original configured playlist reference.
        setting_name: Original configured playlist reference.

    Returns:
        Original validated source identities.

    Raises:
        DiscographyConfigError: An original reference is absent or invalid.
    """
    try:
        return new_wine.parse_playlist_id(reference, setting_name)
    except new_wine.NewWineConfigError as exc:
        raise DiscographyConfigError(str(exc)) from exc


def parse_playlist_ids(
    newfoundland: str | None,
    memory_lane: str | None,
    requeue: str | None,
) -> dict[QueueName, str]:
    """Parse all three configured source playlist references.

    Args:
        newfoundland: Original configured playlist reference.
        memory_lane: Original configured playlist reference.
        requeue: Original configured playlist reference.

    Returns:
        Original validated source identities.

    Raises:
        DiscographyConfigError: An original reference is absent or invalid.
    """
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
    return discography_files.default_state()


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load persisted queue priority without hiding malformed state.

    Args:
        path: Original path boundary.

    Returns:
        Original complete compatible result.
    """
    return discography_files.load_state(path)


def validate_state(state: object) -> dict[str, object]:
    """Validate discography queue rotation independently of storage.

    Args:
        state: Original state boundary.

    Returns:
        Original complete compatible result.
    """
    return discography_files.validate_state(state)


def save_state(
    state: dict[str, object],
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist complete discography rotation state.

    Args:
        state: Original state boundary.
        path: Original path boundary.
    """
    normalized = validate_state(state)
    save_next_queue(cast(QueueName, normalized["next_queue"]), path)


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="discography",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def save_next_queue(
    next_queue: QueueName,
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist the next source queue through an atomic replacement.

    Args:
        next_queue: Original next queue boundary.
        path: Original path boundary.
    """
    discography_files.save_next_queue(next_queue, path)


def _queue_cycle(start: QueueName) -> tuple[QueueName, ...]:
    """Return queue names in cyclic order from the persisted starting point."""
    return discography_batches.queue_cycle(start)


def _next_queue(queue: QueueName) -> QueueName:
    """Return the queue immediately after the given queue."""
    return discography_batches.next_queue(queue)


def _next_start_queue(queue: QueueName) -> QueueName:
    """Rotate the starting priority independently from within-run packing."""
    return discography_batches.next_start_queue(queue)


def rank_historical_artists(
    scrobbles: list[blast_from_past.Scrobble],
) -> tuple[HistoricalArtist, ...]:
    """Rank one date's artists by scrobbles, then normalized name.

    Args:
        scrobbles: Original scrobbles boundary.

    Returns:
        Original complete compatible result.
    """
    return discography_history.ranked_artists(scrobbles)


def select_historical_artist(
    *,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = blast_from_past.fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
) -> HistoricalArtistSelection:
    """Apply Palace of Memory's date/seconds rule to Last.fm artists.

    Args:
        path: Original path boundary.
        today: Original today boundary.
        random_index_reader: Original random index reader boundary.
        progress_callback: Original progress callback boundary.

    Returns:
        Original complete compatible result.
    """
    return composition.historical(path, today, random_index_reader, progress_callback)


def resolve_historical_artist(
    spotify: Spotify,
    selection: HistoricalArtistSelection,
    choice_reader: HistoricalArtistChoiceReader | None,
    retry_call: RetryCall,
) -> QueueArtist:
    """Resolve the original historical artist through exact Spotify mapping.

    Args:
        spotify: Original caller-owned SDK client.
        selection: Original complete historical choice.
        choice_reader: Original optional mapping interaction.
        retry_call: Original caller retry boundary.

    Returns:
        Original resolved Memory Lane candidate.

    Raises:
        DiscographyError: Original mapping fails or is cancelled.
    """
    return composition.resolve_artist(spotify, selection, choice_reader, retry_call)


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
    return composition.queues(spotify, playlist_ids, retry_call, queue_3_playlist_id)


def _positive_int(value: object) -> int:
    """Return a positive integer or zero for malformed Spotify fields."""
    return discography_records.positive_int(value)


def _catalog_release(raw: object, artist_id: str) -> CatalogRelease | None:
    """Parse a canonical candidate, excluding true non-EP singles."""
    return discography_records.catalog_release(raw, artist_id)


def _preferred_release(editions: list[CatalogRelease]) -> CatalogRelease:
    """Choose one edition with the same saved/plain preference as Slow Listening."""
    return discography_catalog.preferred_release(editions)


def load_release_catalog(
    spotify: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[CatalogRelease, ...]:
    """Load canonical albums and EPs, including optional non-studio releases.

    Args:
        spotify: Original spotify boundary.
        artist_id: Original artist id boundary.
        retry_call: Original retry call boundary.

    Returns:
        Original complete compatible result.
    """
    return composition.catalog(spotify, artist_id, retry_call)


def parse_release_indexes(value: str, total: int) -> tuple[int, ...]:
    """Parse comma-separated indexes and inclusive ranges.

    Args:
        value: Original value boundary.
        total: Original total boundary.

    Returns:
        Original complete compatible result.
    """
    return discography_batches.parse_indexes(value, total)


def format_release_indexes(indexes: tuple[int, ...]) -> str:
    """Compress ordered indexes into a short range expression.

    Args:
        indexes: Original indexes boundary.

    Returns:
        Original complete compatible result.
    """
    return discography_batches.format_indexes(indexes)


def build_discography_plan(
    spotify: Spotify,
    playlist_ids: dict[QueueName, str],
    release_selector: ReleaseSelector,
    *,
    queue_3_playlist_id: str | None = None,
    historical_artist_choice_reader: HistoricalArtistChoiceReader | None = None,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = blast_from_past.fetch_random_indexes,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
) -> DiscographyPlan:
    """Build the next round-week batch without changing Spotify or state.

    Args:
        spotify: Original spotify boundary.
        playlist_ids: Original playlist ids boundary.
        release_selector: Original release selector boundary.
        queue_3_playlist_id: Original queue 3 playlist id boundary.
        historical_artist_choice_reader: Original historical mapping interaction.
        scrobbles_path: Original scrobbles path boundary.
        today: Original today boundary.
        random_index_reader: Original random index reader boundary.
        retry_call: Original retry call boundary.
        progress_callback: Original progress callback boundary.
        state_path: Original state path boundary.
        state_service: Original state service boundary.

    Returns:
        Original complete compatible result.
    """
    from spotify_manager.interfaces.operations.discography import (
        build_discography_plan as operation,
    )

    return operation(
        spotify,
        playlist_ids,
        release_selector,
        queue_3_playlist_id=queue_3_playlist_id,
        historical_artist_choice_reader=historical_artist_choice_reader,
        scrobbles_path=scrobbles_path,
        today=today,
        random_index_reader=random_index_reader,
        retry_call=retry_call,
        progress_callback=progress_callback,
        state_path=state_path,
        state_service=state_service,
    )


def _append_log(
    selection: ArtistSelection,
    next_queue: QueueName,
    path: Path,
) -> None:
    """Append one successfully removed artist with the exact release set."""
    discography_files.append_log(selection, next_queue, path, datetime.now(UTC))


def apply_discography_plan(
    spotify: Spotify,
    plan: DiscographyPlan,
    *,
    retry_call: RetryCall | None = None,
    progress_callback: ProgressCallback | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> DiscographyRunSummary:
    """Remove confirmed markers, audit each artist, then advance final priority.

    Args:
        spotify: Original spotify boundary.
        plan: Original plan boundary.
        retry_call: Original retry call boundary.
        progress_callback: Original progress callback boundary.
        state_path: Original state path boundary.
        state_service: Original state service boundary.
        log_path: Original log path boundary.

    Returns:
        Original complete compatible result.
    """
    from spotify_manager.interfaces.operations.discography import (
        apply_discography_plan as operation,
    )

    return operation(
        spotify,
        plan,
        retry_call=retry_call,
        progress_callback=progress_callback,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
    )


def _release_page(
    spotify: Spotify, artist_id: str, offset: int, retry_call: RetryCall
) -> object:
    return retry_call(
        partial(
            spotify.artist_albums,
            artist_id,
            include_groups="album,single,compilation",
            limit=RELEASE_PAGE_LIMIT,
            offset=offset,
        ),
        f"loading discography releases for {artist_id} at offset {offset}",
    )


def _saved_batch(
    spotify: Spotify, album_ids: list[str], retry_call: RetryCall
) -> object:
    return retry_call(
        partial(spotify.current_user_saved_albums_contains, album_ids),
        f"checking {len(album_ids)} saved discography releases",
    )


def _remove_batch(
    spotify: Spotify,
    retry: RetryCall,
    selection: ArtistSelection,
    marker_group: ArtistMarkers,
    batch: list[str],
) -> None:
    retry(
        partial(
            spotify._delete,
            f"playlists/{marker_group.playlist_id}/items",
            payload={"items": [{"uri": uri} for uri in batch]},
        ),
        f"removing {selection.name} from {QUEUE_LABELS[marker_group.queue]}",
    )
