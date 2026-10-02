"""Advance the first two Slow Listening entries through studio discographies."""

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import cast

from spotipy import Spotify

from spotify_manager.application.slow_listening import new_run
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.application.slow_listening_values import FlushResult as FlushResult
from spotify_manager.application.slow_listening_values import (
    FlushSummary as FlushSummary,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningCancelledError as SlowListeningCancelledError,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningConfigError as SlowListeningConfigError,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningError as SlowListeningError,
)
from spotify_manager.application.slow_listening_values import (
    SlowListeningStateError as SlowListeningStateError,
)
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService

# UFI
from spotify_manager.domain import releases as release_policy
from spotify_manager.domain.catalog import DiscographyRelease as DiscographyRelease
from spotify_manager.domain.catalog import release_candidate
from spotify_manager.domain.slow_listening import track_index
from spotify_manager.infrastructure import studio_records
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

EDITION_QUALIFIER = release_policy.EDITION_QUALIFIER
BRACKETED_SUFFIX = release_policy.BRACKETED_SUFFIX
DASHED_SUFFIX = release_policy.DASHED_SUFFIX
TRAILING_EDITION = release_policy.TRAILING_EDITION
EP_MARKER = release_policy.EP_MARKER
NON_STUDIO_PATTERNS = release_policy.NON_STUDIO_PATTERNS

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


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Slow Listening playlist identifier.

    Args:
        reference: Original URL, URI or bare identifier.

    Returns:
        Validated playlist identifier.

    Raises:
        SlowListeningConfigError: The reference is absent or invalid.
    """
    try:
        return new_wine.parse_playlist_id(reference, "SLOW_LISTENING_PLAYLIST")
    except new_wine.NewWineConfigError as exc:
        raise SlowListeningConfigError(str(exc)) from exc


def _positive_int(raw: object, fallback: int = 0) -> int:
    return studio_records.positive_int(raw, fallback)


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    return studio_records.artist_pairs(raw)


def _edition_details(name: str) -> tuple[str, int]:
    return release_policy.edition_details(name)


def release_identity(name: str) -> str:
    """Return the shared edition-neutral release identity.

    Args:
        name: Original release title.

    Returns:
        Normalized title shared by plain and decorated editions.
    """
    return release_policy.release_identity(name)


def _track_identity(name: str) -> str:
    """Normalize edition suffixes when mapping tracks between releases."""
    return release_identity(name)


def _is_non_studio_title(name: str) -> bool:
    return release_policy.is_non_studio_title(name)


def _release_candidate(
    raw: object,
    artist_id: str,
) -> DiscographyRelease | None:
    return studio_records.studio_release(raw, artist_id)


def _release_date_key(value: str) -> tuple[int, int, int, str]:
    return release_policy.studio_date_key(value)


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
        for spotify_id, saved in zip(batch, response, strict=True):
            statuses[spotify_id] = bool(saved)
    return statuses


def _tie_key(artist_id: str, chronology_date: str) -> str:
    """Return the restart-state key for one equal-date release group."""
    return f"{artist_id}:{chronology_date}"


def _artist_release_page(
    sp: Spotify, artist_id: str, offset: int, retry_call: RetryCall
) -> dict[str, object]:
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
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise SlowListeningError("Spotify returned invalid artist releases.")
    return cast(dict[str, object], response)


def _collect_candidates(
    raw_items: list[object], artist_id: str, candidates: dict[str, DiscographyRelease]
) -> None:
    for raw_release in raw_items:
        candidate = _release_candidate(raw_release, artist_id)
        if candidate is not None:
            candidates[candidate.spotify_id] = candidate


def _load_candidates(
    sp: Spotify, artist_id: str, retry_call: RetryCall
) -> list[DiscographyRelease]:
    candidates: dict[str, DiscographyRelease] = {}
    offset = 0
    while True:
        response = _artist_release_page(sp, artist_id, offset, retry_call)
        raw_items = cast(list[object], response["items"])
        _collect_candidates(raw_items, artist_id, candidates)
        offset += len(raw_items)
        if not response.get("next"):
            return list(candidates.values())
        if not raw_items:
            raise SlowListeningError("Spotify returned an empty artist release page.")


def load_discography(
    sp: Spotify, artist_id: str, retry_call: RetryCall
) -> tuple[DiscographyRelease, ...]:
    """Gather catalog facts and delegate edition selection to the pure policy.

    Args:
        sp: Existing synchronous client.
        artist_id: Artist whose primary-credit releases are eligible.
        retry_call: Original retry policy, preserving descriptions and read order.

    Returns:
        Selected studio editions in the existing chronological order.

    Raises:
        SlowListeningError: Catalog or membership responses are malformed.
    """
    from spotify_manager.infrastructure.legacy.studio_catalog import StudioCatalogAccess

    return StudioCatalogAccess(sp, retry_call).discography(artist_id)


def _ordered_date_group(
    artist_id: str,
    releases: tuple[DiscographyRelease, ...],
    order_reader: ReleaseOrderReader,
    release_orders: dict[str, object],
    order_saved: Callable[[], None],
) -> tuple[DiscographyRelease, ...]:
    return ReleaseOrdering(order_reader, release_orders, order_saved).ordered(
        artist_id, releases
    )


def _next_release(
    current_release: DiscographyRelease,
    discography: tuple[DiscographyRelease, ...],
    order_reader: ReleaseOrderReader,
    release_orders: dict[str, object],
    order_saved: Callable[[], None],
) -> DiscographyRelease | None:
    return ReleaseOrdering(order_reader, release_orders, order_saved).following(
        current_release, discography
    )


def _as_release_candidate(
    release: DiscographyRelease,
) -> new_wine.ReleaseCandidate:
    """Convert a selected release for the shared ordered-track loader."""
    return release_candidate(release)


def load_release_tracks(
    sp: Spotify,
    release: DiscographyRelease,
    retry_call: RetryCall,
) -> tuple[new_wine.ReleaseTrack, ...]:
    """Load one selected edition in Spotify disc and track order.

    Args:
        sp: Caller-owned synchronous client.
        release: Selected studio edition.
        retry_call: Existing retry and cancellation callback.

    Returns:
        Playable tracks in their original order.

    Raises:
        SlowListeningError: Shared release-track parsing fails.
    """
    from spotify_manager.infrastructure.legacy.studio_catalog import StudioCatalogAccess

    return StudioCatalogAccess(sp, retry_call).tracks(release)


def _default_state() -> dict[str, object]:
    """Return empty versioned restart state."""
    return {
        "version": STATE_VERSION,
        "release_orders": {},
        "active_run": None,
    }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, object]:
    """Load restart state without discarding malformed data.

    Args:
        path: Original local namespace path.

    Returns:
        Existing namespace or fresh defaults for a missing file.

    Raises:
        SlowListeningStateError: Reading, decoding or validation fails.
    """
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlowListeningStateError(
            f"Slow Listening state is invalid: {path}"
        ) from exc
    try:
        return validate_state(raw)
    except SlowListeningStateError as exc:
        raise SlowListeningStateError(
            f"Slow Listening state is invalid: {path}"
        ) from exc


def validate_state(raw: object) -> dict[str, object]:
    """Validate the Slow Listening namespace independently of storage.

    Args:
        raw: Decoded namespace payload.

    Returns:
        Original mapping with unknown fields preserved.

    Raises:
        SlowListeningStateError: Version or release-order fields are invalid.
    """
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("release_orders"), dict)
    ):
        raise SlowListeningStateError("Slow Listening state is invalid.")
    return raw


def save_state(
    state: dict[str, object],
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist restart state atomically.

    Args:
        state: Complete current namespace.
        path: Original local namespace destination.

    Raises:
        SlowListeningStateError: Writing or replacing the file fails.
    """
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


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="slow_listening",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def append_log(
    run_id: str,
    result: FlushResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable transition record with its original timestamp.

    Args:
        run_id: Durable execution identifier.
        result: Planned or completed transition, including previews.
        path: Original audit destination.

    Raises:
        SlowListeningStateError: Creating or appending to the audit fails.
    """
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
    playlist_id: str, tracks: tuple[new_wine.PlaylistTrack, ...]
) -> dict[str, object]:
    return new_run(playlist_id, tracks, _clock)


def _track_index(
    tracks: tuple[new_wine.ReleaseTrack, ...], source: new_wine.PlaylistTrack
) -> int | None:
    return track_index(tracks, source)


def _add_playlist_track(
    sp: Spotify,
    playlist_id: str,
    track: new_wine.ReleaseTrack,
    retry_call: RetryCall,
) -> None:
    """Add a replacement before removing its source."""
    retry_call(
        partial(_post_track, sp, playlist_id, track),
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
        partial(_delete_track, sp, playlist_id, source),
        f"removing {source.name} from Slow Listening",
    )


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
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> FlushSummary:
    """Advance the first two Slow Listening entries through explicit integrations.

    Args:
        sp: Caller-owned synchronous Spotify client.
        playlist_id: Configured Slow Listening playlist.
        order_reader: Operator's equal-date release ordering callback.
        completion_notifier: Completion acknowledgement callback.
        action_reader: Optional per-track advance, skip or quit callback.
        dry_run: Preview without playlist or checkpoint writes; audits are retained.
        echo: Existing message sink.
        progress_callback: Optional progress/cancellation callback.
        retry_call: Optional original retry policy.
        state_path: Original durable namespace location.
        state_service: Optional explicit shared-state service.
        log_path: Original audit destination.

    Returns:
        Unchanged summary including pause, resume and result fields.

    Raises:
        SlowListeningError: Observations, choices or durable state are invalid.
    """
    from spotify_manager.bootstrap.slow_listening import run_slow_listening

    return run_slow_listening(
        sp,
        playlist_id,
        order_reader,
        completion_notifier,
        action_reader,
        dry_run,
        echo,
        progress_callback,
        retry_call,
        state_path,
        state_service,
        log_path,
        _clock,
    )


def _clock() -> datetime:
    return datetime.now(UTC)


def _post_track(sp: Spotify, playlist_id: str, track: new_wine.ReleaseTrack) -> object:
    return sp._post(f"playlists/{playlist_id}/items", payload={"uris": [track.uri]})


def _delete_track(
    sp: Spotify, playlist_id: str, source: new_wine.PlaylistTrack
) -> object:
    return sp._delete(
        f"playlists/{playlist_id}/items", payload={"items": [{"uri": source.uri}]}
    )
