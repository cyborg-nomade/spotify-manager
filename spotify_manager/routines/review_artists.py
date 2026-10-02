"""Restart-safe review of followed artists and listening queues."""

from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep as default_sleep

from pydantic import BaseModel
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.artist_review_catalog import FirstTrack
from spotify_manager.application.artist_review_catalog import RawReleasePage
from spotify_manager.application.artist_review_catalog import ReleasePage
from spotify_manager.application.artist_review_catalog import search_releases
from spotify_manager.application.artist_review_membership import MembershipPage
from spotify_manager.application.artist_review_membership import (
    playlist_membership as gather_membership,
)
from spotify_manager.application.artist_review_recovery import flush_moves
from spotify_manager.application.artist_review_recovery import flush_unfollows
from spotify_manager.application.artist_review_session import record_completion
from spotify_manager.application.artist_review_values import (
    ArtistReviewPaths as ArtistReviewPaths,
)
from spotify_manager.application.artist_review_values import (
    ArtistReviewState as ArtistReviewState,
)
from spotify_manager.application.artist_review_values import (
    ArtistReviewSummary as ArtistReviewSummary,
)
from spotify_manager.application.artist_review_values import (
    ReviewCounts as ReviewCounts,
)
from spotify_manager.application.artist_review_values import (
    summary_from_counts as summary_from_counts,
)
from spotify_manager.application.library_statistics import (
    period_report as select_period_report,
)
from spotify_manager.application.library_statistics import (
    report_with_unfollowed_artists,
)
from spotify_manager.bootstrap import artist_review as composition

# UFI
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.artist_review_selection import (
    ambiguous_track_choices as ambiguous_track_choices,
)
from spotify_manager.domain.artist_review_selection import log_int as log_int
from spotify_manager.domain.artist_review_selection import (
    normalize_name as normalize_name,
)
from spotify_manager.domain.artist_review_selection import (
    release_date_key as release_date_key,
)
from spotify_manager.domain.artist_review_selection import (
    spotify_search_query as spotify_search_query,
)
from spotify_manager.domain.artist_review_values import (
    ArtistReviewConfigError as ArtistReviewConfigError,
)
from spotify_manager.domain.artist_review_values import (
    ArtistReviewError as ArtistReviewError,
)
from spotify_manager.domain.artist_review_values import (
    InvalidReviewChoiceError as InvalidReviewChoiceError,
)
from spotify_manager.domain.artist_review_values import (
    PlaylistMembership as PlaylistMembership,
)
from spotify_manager.domain.artist_review_values import QueuePlaylists as QueuePlaylists
from spotify_manager.domain.artist_review_values import (
    ReleaseCandidate as ReleaseCandidate,
)
from spotify_manager.domain.artist_review_values import TrackCandidate as TrackCandidate
from spotify_manager.domain.artist_review_values import (
    parse_playlist_id as parse_playlist_id,
)
from spotify_manager.infrastructure import artist_review_files as review_files
from spotify_manager.infrastructure import artist_review_records as catalog_records
from spotify_manager.infrastructure import artist_review_state as review_state
from spotify_manager.infrastructure.artist_review_records import (
    artist_ids as artist_ids,
)
from spotify_manager.infrastructure.artist_review_records import (
    first_artist_name as first_artist_name,
)
from spotify_manager.infrastructure.artist_review_records import (
    release_candidate as release_candidate,
)
from spotify_manager.infrastructure.artist_review_records import (
    release_type as release_type,
)
from spotify_manager.infrastructure.artist_review_records import (
    track_candidate as track_candidate,
)
from spotify_manager.infrastructure.library_records import current_stats_history_key
from spotify_manager.infrastructure.spotify.retry import TRANSIENT_MAX_ATTEMPTS
from spotify_manager.infrastructure.spotify.retry import TRANSIENT_RETRY_DELAY_SECONDS
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.infrastructure.spotify.retry import SpotifyTransientServerError
from spotify_manager.infrastructure.spotify.retry import (
    retry_spotify_server_errors as retry_spotify_server_errors,
)
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryArtist


SEARCH_LIMIT = 10
SEARCH_MAX_PAGES = 3
ARTIST_ALBUM_PAGE_LIMIT = 10
PLAYLIST_PAGE_LIMIT = 50
PLAYLIST_MUTATION_BATCH_SIZE = 100
UNFOLLOW_BATCH_SIZE = 40

CHOICE_SKIP = "skip"
CHOICE_QUIT = "quit"
CHOICE_DECLINE = "decline"

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
TrackChoiceReader = Callable[[YourLibraryArtist, tuple["TrackCandidate", ...]], str]
ReleaseChoiceReader = Callable[
    [YourLibraryArtist, tuple["ReleaseCandidate", ...], bool], str
]
Sleep = Callable[[float], None]
RetryCall = Callable[[Callable[[], object], str], object]


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_PATHS = ArtistReviewPaths.for_files_dir(FILES_DIR)


def utc_now() -> str:
    """Return a JSON-friendly UTC timestamp.

    Returns:
        Original ISO-8601 UTC timestamp.
    """
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    """Return a sortable review run identifier.

    Returns:
        Original sortable invocation identifier.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def load_json(path: Path, default: object) -> object:
    """Load JSON or return a default when the file is absent.

    Args:
        path: Original complete local file location.
        default: Original same fallback object when the file is absent.

    Returns:
        Original decoded JSON or the same missing-file default.

    Raises:
        ArtistReviewError: An original required boundary is invalid.
    """
    return review_files.load_json(path, default)


def write_json_atomic(path: Path, value: object) -> None:
    """Atomically replace a JSON file.

    Args:
        path: Original complete local file location.
        value: Original complete JSON-serializable value.
    """
    review_files.write_json_atomic(path, value)


def append_events(path: Path, events: list[dict[str, object]]) -> None:
    """Append audit events as JSON Lines.

    Args:
        path: Original complete local file location.
        events: Original complete audit events in write order.
    """
    review_files.append_events(path, events)


def event(run_id: str, event_name: str, **details: object) -> dict[str, object]:
    """Build one timestamped audit event.

    Args:
        run_id: Original sortable invocation identity.
        event_name: Original audit event category.
        details: Original complete decision fields.

    Returns:
        Original complete timestamped audit event.
    """
    return {
        "timestamp": utc_now(),
        "run_id": run_id,
        "event": event_name,
        **details,
    }


def load_models[T: BaseModel](path: Path, model_type: type[T]) -> list[T]:
    """Load a JSON list of Pydantic models.

    Args:
        path: Original complete local file location.
        model_type: Original complete library validation model.

    Returns:
        Original complete validated models in stored order.

    Raises:
        ArtistReviewError: An original required boundary is invalid.
    """
    return review_files.load_models(path, model_type, load_json)


def save_artists(path: Path, artists: list[YourLibraryArtist]) -> None:
    """Persist followed artists in the established sort order.

    Args:
        path: Original complete local file location.
        artists: Original caller-owned current followed-artist list.
    """
    review_files.save_artists(
        path,
        artists,
        write_json_atomic,
        partial(publish_managed_path, source="artist review"),
    )


def load_review_state(log_path: Path) -> ArtistReviewState:
    """Reconstruct completed artists and unfinished unfollow plans.

    Args:
        log_path: Original explicit legacy audit file.

    Returns:
        Original replayed completed and pending progress.
    """
    return review_files.load_review_state(log_path)


def _default_state() -> dict[str, object]:
    """Return empty serialized artist-review progress."""
    return review_state.default_state()


def validate_state(raw: object) -> dict[str, object]:
    """Validate artist-review progress independently of storage.

    Args:
        raw: Original untrusted complete checkpoint.

    Returns:
        Original same valid checkpoint without normalization.

    Raises:
        ArtistReviewError: An original required boundary is invalid.
    """
    return review_state.validate_state(raw)


def _serialize_state(state: ArtistReviewState) -> dict[str, object]:
    """Serialize mutable review progress for the central state document."""
    return review_state.serialize_state(state)


def _deserialize_state(raw: object) -> ArtistReviewState:
    """Create mutable review progress from validated serialized state."""
    return review_state.deserialize_state(raw)


def _load_log_state(log_path: Path) -> dict[str, object]:
    """Reconstruct the legacy state representation from its audit log."""
    return _serialize_state(load_review_state(log_path))


def _save_log_state(_state: dict[str, object], _log_path: Path) -> None:
    """Keep explicit legacy paths log-backed; events are written separately."""


def _state_access(
    paths: ArtistReviewPaths,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test log."""
    return routine_state(
        name="review_artists",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=paths.log,
        default_legacy_path=DEFAULT_PATHS.log,
        legacy_loader=_load_log_state,
        legacy_saver=_save_log_state,
        service=state_service,
    )


def load_cache(path: Path, refresh: bool) -> dict[str, dict[str, object]]:
    """Load reusable catalog metadata, or start fresh when requested.

    Args:
        path: Original complete local file location.
        refresh: Original option to skip the existing metadata cache.

    Returns:
        Original same metadata object or an empty refresh cache.

    Raises:
        ArtistReviewError: An original required boundary is invalid.
    """
    return review_files.load_cache(path, refresh, load_json)


def save_cache(path: Path, cache: dict[str, dict[str, object]]) -> None:
    """Persist the catalog cache after every completed metadata unit.

    Args:
        path: Original complete local file location.
        cache: Original same mutable complete metadata cache.
    """
    write_json_atomic(path, cache)


def ranked_artist_tracks(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[TrackCandidate]:
    """Return Spotify-ranked associated tracks using one search request.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artist: Original complete followed-artist model.
        cache: Original same mutable complete metadata cache.
        cache_path: Original metadata checkpoint destination.
        retry_call: Original caller-owned synchronous retry wrapper.

    Returns:
        Original complete associated ranked tracks.
    """
    return composition.catalog(
        sp, artist, cache, cache_path, retry_call
    ).ranked_tracks()


def search_ranked_releases(
    sp: Spotify,
    artist: YourLibraryArtist,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Collect up to ten associated releases in Spotify search rank order.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artist: Original complete followed-artist model.
        retry_call: Original caller-owned synchronous retry wrapper.

    Returns:
        Original first ten qualifying album/EP search results.
    """
    return search_releases(partial(_read_ranked_page, sp, artist, retry_call))


def ranked_artist_releases(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Return cached Spotify-ranked album/EP candidates with first tracks.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artist: Original complete followed-artist model.
        cache: Original same mutable complete metadata cache.
        cache_path: Original metadata checkpoint destination.
        retry_call: Original caller-owned synchronous retry wrapper.

    Returns:
        Original complete enriched ranked releases.
    """
    return composition.catalog(
        sp, artist, cache, cache_path, retry_call
    ).ranked_releases()


def earliest_artist_releases(
    sp: Spotify,
    artist: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Return the artist's ten earliest releases with resumable pagination.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artist: Original complete followed-artist model.
        cache: Original same mutable complete metadata cache.
        cache_path: Original metadata checkpoint destination.
        retry_call: Original caller-owned synchronous retry wrapper.

    Returns:
        Original ten earliest distinct enriched releases.
    """
    return composition.catalog(
        sp, artist, cache, cache_path, retry_call
    ).earliest_releases()


def enrich_first_tracks(
    sp: Spotify,
    artist: YourLibraryArtist,
    releases: list[ReleaseCandidate],
    cache_key: str,
    cache: dict[str, dict[str, object]],
    cache_path: Path,
    retry_call: RetryCall,
) -> list[ReleaseCandidate]:
    """Fetch only each displayed release's first track and cache the result.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artist: Original complete followed-artist model.
        releases: Original complete mutable release candidates.
        cache_key: Original ranked or chronological catalog namespace.
        cache: Original same mutable complete metadata cache.
        cache_path: Original metadata checkpoint destination.
        retry_call: Original caller-owned synchronous retry wrapper.

    Returns:
        Original same complete mutable candidate list.
    """
    return composition.catalog(sp, artist, cache, cache_path, retry_call).enrich(
        releases, cache_key
    )


def playlist_membership(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> PlaylistMembership:
    """Load one queue once and index its tracks and primary artists.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        playlist_id: Original queue playlist identity.
        retry_call: Original caller-owned synchronous retry wrapper.

    Returns:
        Original complete mutable queue membership indexes.
    """
    return gather_membership(
        playlist_id, partial(_read_membership_page, sp, playlist_id, retry_call)
    )


def add_playlist_item(sp: Spotify, playlist_id: str, track_uri: str) -> object:
    """Add one track through Spotify's current playlist-items endpoint.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        playlist_id: Original queue playlist identity.
        track_uri: Original selected playable marker URI.

    Returns:
        Original accepted Spotify mutation response.
    """
    return sp._post(
        f"playlists/{playlist_id}/items",
        payload={"uris": [track_uri]},
    )


def remove_playlist_items(
    sp: Spotify,
    playlist_id: str,
    track_uris: list[str],
) -> object:
    """Remove specific tracks through Spotify's current playlist endpoint.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        playlist_id: Original queue playlist identity.
        track_uris: Original complete ordered marker removal batch.

    Returns:
        Original accepted Spotify mutation response.
    """
    return sp._delete(
        f"playlists/{playlist_id}/items",
        payload={"items": [{"uri": uri} for uri in track_uris]},
    )


def remove_library_artists(sp: Spotify, artist_uris: list[str]) -> object:
    """Unfollow artists through Spotify's current generic library endpoint.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artist_uris: Original complete ordered unfollow batch.

    Returns:
        Original accepted Spotify mutation response.
    """
    return sp._delete("me/library", uris=",".join(artist_uris))


def update_stats_after_unfollow(
    stats_path: Path,
    total_artists: int,
    removed_count: int,
) -> None:
    """Update the current stats period after a successful unfollow batch.

    Args:
        stats_path: Original statistics history destination.
        total_artists: Original followed count after the accepted batch.
        removed_count: Original successful unfollow batch size.
    """
    raw_history = load_json(stats_path, {})
    if not isinstance(raw_history, dict) or not raw_history:
        return
    history = _stats_reports(raw_history)
    key, report = period_report(history)
    history[key] = report_with_unfollowed_artists(report, total_artists, removed_count)
    payload = {}
    for history_key, value in history.items():
        payload[history_key] = value.model_dump()
    write_json_atomic(stats_path, payload)


def complete_artist(
    state: ArtistReviewState,
    counts: ReviewCounts,
    log_path: Path,
    run_id: str,
    artist: YourLibraryArtist,
    liked_count: int,
    action: str,
    **details: object,
) -> None:
    """Persist a completed artist decision and update invocation counters.

    Args:
        state: Original mutable completed and pending progress.
        counts: Original mutable invocation counters.
        log_path: Original explicit legacy audit file.
        run_id: Original sortable invocation identity.
        artist: Original complete followed-artist model.
        liked_count: Original local liked-track count.
        action: Original completed action category.
        details: Original complete decision fields.
    """
    payload = event(
        run_id,
        "artist_completed",
        artist_id=artist.spotify_id,
        artist=artist.name,
        liked_tracks=liked_count,
        action=action,
        **details,
    )
    record_completion(
        state,
        counts,
        artist.spotify_id,
        action,
        payload,
        partial(append_events, log_path),
    )


def flush_pending_unfollows(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry_call: RetryCall,
    echo: Echo,
) -> list[YourLibraryArtist]:
    """Execute journaled automatic unfollows in API-sized batches.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artists: Original caller-owned current followed-artist list.
        state: Original mutable completed and pending progress.
        counts: Original mutable invocation counters.
        paths: Original complete file locations.
        run_id: Original sortable invocation identity.
        retry_call: Original caller-owned synchronous retry wrapper.
        echo: Original visible progress and action presenter.

    Returns:
        Original current followed artists after recovery.
    """
    session = composition.recovery_session(
        sp,
        artists,
        state,
        counts,
        paths,
        run_id,
        retry_call,
        echo,
    )
    flush_unfollows(session)
    return session.artists


def flush_pending_queue_moves(
    sp: Spotify,
    artists: list[YourLibraryArtist],
    state: ArtistReviewState,
    counts: ReviewCounts,
    paths: ArtistReviewPaths,
    run_id: str,
    retry_call: RetryCall,
    get_membership: Callable[[str], PlaylistMembership],
    echo: Echo,
) -> None:
    """Finish journaled queue-one to queue-two moves idempotently.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        artists: Original caller-owned current followed-artist list.
        state: Original mutable completed and pending progress.
        counts: Original mutable invocation counters.
        paths: Original complete file locations.
        run_id: Original sortable invocation identity.
        retry_call: Original caller-owned synchronous retry wrapper.
        get_membership: Original caller-owned queue membership authority.
        echo: Original visible progress and action presenter.
    """
    session = composition.recovery_session(
        sp,
        artists,
        state,
        counts,
        paths,
        run_id,
        retry_call,
        echo,
    )
    flush_moves(session, get_membership)


def review_artists(
    sp: Spotify,
    playlists: QueuePlaylists,
    track_choice_reader: TrackChoiceReader | None = None,
    release_choice_reader: ReleaseChoiceReader | None = None,
    paths: ArtistReviewPaths = DEFAULT_PATHS,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    refresh_cache: bool = False,
    limit: int | None = None,
    sleep: Sleep = default_sleep,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
    state_service: StateService | None = None,
) -> ArtistReviewSummary:
    """Review followed artists using local counts and targeted Spotify calls.

    Args:
        sp: Original caller-owned synchronous Spotify client.
        playlists: Original parsed three queue identities.
        track_choice_reader: Original optional tied-track decision reader.
        release_choice_reader: Original optional release decision reader.
        paths: Original complete file locations.
        echo: Original visible progress and action presenter.
        progress_callback: Original optional position/total presenter.
        refresh_cache: Original option to rebuild metadata from live reads.
        limit: Original pending-list slice, including zero and negatives.
        sleep: Original blocking retry wait.
        transient_retry_delay_seconds: Original transient retry delay.
        transient_max_attempts: Original maximum transient attempts.
        state_service: Original optional shared state authority.

    Returns:
        Original complete paused or completed ten-field summary.

    Raises:
        ArtistReviewError: An original required boundary is invalid.
    """
    return composition.compose(
        sp,
        playlists,
        paths,
        echo,
        progress_callback,
        track_choice_reader,
        release_choice_reader,
        sleep,
        transient_retry_delay_seconds,
        transient_max_attempts,
        state_service,
    ).run(refresh_cache, limit)


__all__ = [
    "ArtistReviewConfigError",
    "ArtistReviewError",
    "ArtistReviewPaths",
    "ArtistReviewSummary",
    "CHOICE_DECLINE",
    "CHOICE_QUIT",
    "CHOICE_SKIP",
    "DEFAULT_PATHS",
    "InvalidReviewChoiceError",
    "QueuePlaylists",
    "ReleaseCandidate",
    "SpotifyRateLimitError",
    "SpotifyTransientServerError",
    "TrackCandidate",
    "review_artists",
]


def _read_tracks(
    sp: Spotify, artist: YourLibraryArtist, retry_call: RetryCall
) -> list[TrackCandidate]:
    response = retry_call(
        partial(
            sp.search,
            q=spotify_search_query(artist.name),
            type="track",
            limit=SEARCH_LIMIT,
            offset=0,
        ),
        f"searching ranked tracks for {artist.name}",
    )
    return catalog_records.track_page(response, artist.spotify_id, artist.name)


def _read_ranked_page(
    sp: Spotify, artist: YourLibraryArtist, retry_call: RetryCall, offset: int
) -> ReleasePage:
    response = retry_call(
        partial(
            sp.search,
            q=spotify_search_query(artist.name),
            type="album",
            limit=SEARCH_LIMIT,
            offset=offset,
        ),
        f"searching ranked releases for {artist.name} at offset {offset}",
    )
    return catalog_records.release_page(
        response, artist.spotify_id, artist.name, offset
    )


def _read_discography_page(
    sp: Spotify, artist: YourLibraryArtist, retry_call: RetryCall, offset: int
) -> RawReleasePage:
    response = retry_call(
        partial(
            sp.artist_albums,
            artist.spotify_id,
            include_groups="album,single,compilation",
            limit=ARTIST_ALBUM_PAGE_LIMIT,
            offset=offset,
        ),
        f"fetching releases for {artist.name} at offset {offset}",
    )
    return catalog_records.scan_page(response, artist.name)


def _read_first(
    sp: Spotify, retry_call: RetryCall, release: ReleaseCandidate
) -> FirstTrack | None:
    try:
        response = retry_call(
            partial(sp.album_tracks, release.spotify_id, limit=1, offset=0),
            f"fetching the first track of {release.name}",
        )
    except SpotifyException as exc:
        if exc.http_status != 404:
            raise
        response = {"items": []}
    return catalog_records.first_track(response, release.name)


def _read_membership_page(
    sp: Spotify, playlist_id: str, retry_call: RetryCall, offset: int
) -> MembershipPage:
    response = retry_call(
        partial(
            sp._get,
            f"playlists/{playlist_id}/items",
            limit=PLAYLIST_PAGE_LIMIT,
            offset=offset,
        ),
        f"loading queue playlist {playlist_id} at offset {offset}",
    )
    return catalog_records.membership_page(response, playlist_id)


def period_report(stats_history: dict[str, StatsReport]) -> tuple[str, StatsReport]:
    """Select original current-period statistics through the shared policy.

    Args:
        stats_history: Original insertion-ordered complete statistics history.

    Returns:
        Original current key and existing or reset report.

    Raises:
        StopIteration: No report exists to seed a missing period.
    """
    return select_period_report(stats_history, current_stats_history_key())


def _stats_reports(raw: dict[str, object]) -> dict[str, StatsReport]:
    history = {}
    for key, value in raw.items():
        history[key] = StatsReport.model_validate(value)
    return history
