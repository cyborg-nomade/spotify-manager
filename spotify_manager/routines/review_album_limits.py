"""Interactive routine for removing albums below the liked-track threshold."""

import asyncio
import json
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Protocol
from typing import cast

from spotipy import Spotify as LegacySpotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.artist_follows import (
    ArtistPersistenceResult as ArtistPersistenceResult,
)
from spotify_manager.application.library_statistics import (
    report_with_followed_artist as report_with_followed_artist,
)
from spotify_manager.application.ports.runtime import CountProgress
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Wait
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.ports.state import BlockingRoutineState
from spotify_manager.core.state.compat import StateLocation
from spotify_manager.core.state.compat import routine_state_from
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist as AlbumArtist
from spotify_manager.infrastructure.async_state import AsyncRoutineState
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.library_records import (
    REMOVED_ALBUMS_LOG_PATH as REMOVED_ALBUMS_LOG_PATH,
)
from spotify_manager.infrastructure.library_records import (
    current_stats_history_key as current_stats_history_key,
)
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.python_compat.album_limits import (
    BlockingAlbumAction as LegacyAlbumAction,
)
from spotify_manager.infrastructure.python_compat.runtime import (
    BlockingWait as LegacyWait,
)
from spotify_manager.infrastructure.routine_state_codecs import (
    ReviewAlbumLimitsStateCodec,
)
from spotify_manager.infrastructure.spotify.retry import (
    RETRY_AFTER_SECONDS_PATTERN as RETRY_AFTER_SECONDS_PATTERN,
)
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_MAX_ATTEMPTS as TRANSIENT_MAX_ATTEMPTS,
)
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_RETRY_DELAY_SECONDS as TRANSIENT_RETRY_DELAY_SECONDS,
)
from spotify_manager.infrastructure.spotify.retry import (
    TRANSIENT_SPOTIFY_STATUSES as TRANSIENT_SPOTIFY_STATUSES,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyRateLimitError as SpotifyRateLimitError,
)
from spotify_manager.infrastructure.spotify.retry import (
    SpotifyTransientServerError as SpotifyTransientServerError,
)
from spotify_manager.infrastructure.spotify.retry import (
    format_retry_after as format_retry_after,
)
from spotify_manager.infrastructure.spotify.retry import (
    format_retry_delay as format_retry_delay,
)
from spotify_manager.infrastructure.spotify.retry import (
    format_transient_spotify_failure as format_transient_spotify_failure,
)
from spotify_manager.infrastructure.spotify.retry import (
    get_retry_after_seconds as get_retry_after_seconds,
)
from spotify_manager.infrastructure.spotify.retry import (
    handle_spotify_exception as handle_spotify_exception,
)
from spotify_manager.infrastructure.spotify.retry import (
    is_transient_spotify_error as is_transient_spotify_error,
)
from spotify_manager.infrastructure.spotify.retry import (
    parse_retry_after_seconds as parse_retry_after_seconds,
)
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.infrastructure.spotify_payloads import AlbumCredits
from spotify_manager.infrastructure.spotify_payloads import ArtistCredit

# UFI
from spotify_manager.interfaces.presenters.album_limits import (
    echo_track_details as echo_track_details,
)
from spotify_manager.interfaces.presenters.album_limits import (
    format_album_label as format_album_label,
)
from spotify_manager.interfaces.presenters.album_limits import (
    format_evaluation_summary as format_evaluation_summary,
)
from spotify_manager.interfaces.presenters.album_limits import (
    read_action as read_action,
)
from spotify_manager.loaders_savers import load_stats_history_file
from spotify_manager.loaders_savers import (
    load_total_albums_new_file as load_total_albums_new_file,
)
from spotify_manager.loaders_savers import load_total_artists_file
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)
from spotify_manager.loaders_savers import save_stats_history
from spotify_manager.loaders_savers import save_total_albums_new_file
from spotify_manager.loaders_savers import save_total_artists_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.utils.sorting import artist_sort_key


type Sleep = Wait


type ProgressCallback = CountProgress


type Echo = Messages


REVIEW_DECISIONS_PATH = (
    Path(__file__).resolve().parent.parent
    / "files"
    / "review_album_limits_decisions.json"
)
TRACK_CONTAINS_BATCH_SIZE = 20


class ActionReader(Protocol):
    """Own the operator interaction for choose action."""

    async def choose_action(
        self, album: YourLibraryAlbum, evaluation: AlbumEvaluation, /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            album: Original interaction value.
            evaluation: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


ReviewDecisions = dict[str, dict[str, object]]


def normalise_name(value: str) -> str:
    """Normalise a name for case-insensitive artist lookups.

    Args:
        value: Original name or payload value.

    Returns:
        Stripped, case-folded original name.
    """
    return value.strip().casefold()


def known_artist_ids_by_name(library: YourLibraryFile) -> dict[str, str]:
    """Read followed artist identities from the original export observations.

    Args:
        library: Validated export, retaining its original artist order.

    Returns:
        Normalized names with the last observed identifier for duplicate names.
    """
    identities = {}
    for artist in library.artists:
        identities[normalise_name(artist.name)] = artist.spotify_id
    return identities


def _artist_candidate(candidates: list[ArtistCredit], name: str) -> ArtistCredit:
    # This original SDK boundary intentionally retains unchecked payload semantics.
    for candidate in candidates:
        if normalise_name(candidate.get("name", "")) == normalise_name(name):
            return candidate
    return candidates[0]


async def _album_artist_metadata(
    sp: Spotify, album: YourLibraryAlbum
) -> ArtistCredit | None:
    try:
        spotify_album = cast(AlbumCredits, await sp.album(album.spotify_id))
    except SpotifyException as exc:
        handle_spotify_exception(exc)
    spotify_artists = spotify_album.get("artists", [])
    if not spotify_artists:
        return None
    return _artist_candidate(spotify_artists, album.artist)


async def async_resolve_album_artist(
    sp: Spotify,
    album: YourLibraryAlbum,
    known_artist_ids: dict[str, str],
) -> AlbumArtist | None:
    """Resolve the artist using original local-name and primary-credit rules.

    Args:
        sp: Caller-owned client.
        album: Original review item.
        known_artist_ids: Mutable run-scoped name cache.

    Returns:
        Resolved identity, or None for absent metadata/identifier.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyException: Other Spotify failures retain their original type.
    """
    known_artist_id = known_artist_ids.get(normalise_name(album.artist))
    if known_artist_id:
        return AlbumArtist(spotify_id=known_artist_id, name=album.artist)

    artist = await _album_artist_metadata(sp, album)
    if artist is None:
        return None
    artist_id = artist.get("id")
    if not artist_id:
        return None

    artist_name = artist.get("name") or album.artist
    known_artist_ids[normalise_name(album.artist)] = artist_id
    known_artist_ids[normalise_name(artist_name)] = artist_id
    return AlbumArtist(spotify_id=artist_id, name=artist_name)


def to_library_artist(artist: AlbumArtist) -> YourLibraryArtist:
    """Convert a followed album artist to the local artist file model.

    Args:
        artist: Resolved Spotify artist identity.

    Returns:
        The original local artist-file model.
    """
    return YourLibraryArtist(
        name=artist.name,
        uri=f"spotify:artist:{artist.spotify_id}",
    )


def add_followed_artist_to_total_file(artist: AlbumArtist) -> bool:
    """Add a newly followed artist to artists_total.json when absent.

    Args:
        artist: Resolved Spotify artist identity.

    Returns:
        Whether the mirror gained this artist.
    """
    total_artists = load_total_artists_file()
    for stored_artist in total_artists:
        if stored_artist.spotify_id == artist.spotify_id:
            return False

    updated_artists = [*total_artists, to_library_artist(artist)]
    save_total_artists_file(sorted(updated_artists, key=artist_sort_key))
    return True


async def async_update_stats_history_for_followed_artist() -> bool:
    """Record one newly followed artist in stats_history.json.

    Returns:
        Whether a nonempty history was updated.
    """
    async with blocking_capacity():
        task = asyncio.create_task(
            asyncio.to_thread(_blocking_update_stats_history_for_followed_artist)
        )
        return await finish_blocking(task)


def _blocking_update_stats_history_for_followed_artist() -> bool:
    """Record one newly followed artist in stats_history.json.

    Returns:
        Whether a nonempty history was updated.
    """
    stats_history = load_stats_history_file()
    if not stats_history:
        return False
    key = current_stats_history_key()
    existing_period = key in stats_history
    source_report = (
        stats_history[key]
        if existing_period
        else next(reversed(stats_history.values()))
    )
    stats_history[key] = report_with_followed_artist(source_report, existing_period)
    save_stats_history(stats_history)
    return True


async def async_record_followed_artist(artist: AlbumArtist) -> ArtistPersistenceResult:
    """Persist a newly followed artist to local files.

    Args:
        artist: Resolved Spotify artist identity.

    Returns:
        Original mirror and statistics publication flags.
    """
    async with blocking_capacity():
        file_operation = asyncio.create_task(
            asyncio.to_thread(add_followed_artist_to_total_file, artist)
        )
        total_artists_updated = await finish_blocking(file_operation)
    if not total_artists_updated:
        return ArtistPersistenceResult(
            total_artists_updated=False,
            stats_history_updated=False,
        )

    return ArtistPersistenceResult(
        total_artists_updated=True,
        stats_history_updated=(await async_update_stats_history_for_followed_artist()),
    )


def remove_first_matching_album(
    albums: list[YourLibraryAlbum], album_id: str
) -> list[YourLibraryAlbum]:
    """Return ``albums`` with the first matching Spotify album id removed.

    Args:
        albums: Original ordered library items.
        album_id: Original Spotify album identifier.

    Returns:
        A copy with only the first matching entry removed.
    """
    remaining = list(albums)
    for index, album in enumerate(remaining):
        if album.spotify_id == album_id:
            del remaining[index]
            break
    return remaining


def load_review_decisions(
    decisions_path: Path = REVIEW_DECISIONS_PATH,
) -> ReviewDecisions:
    """Load persisted review decisions keyed by Spotify album id.

    Args:
        decisions_path: Existing decisions file destination.

    Returns:
        Original dictionary entries, ignoring non-dictionary records.
    """
    if not decisions_path.exists():
        return {}

    with open(decisions_path) as decisions_file:
        data = json.load(decisions_file)

    if not isinstance(data, dict):
        return {}

    return validate_review_decisions(data)


def validate_review_decisions(raw: object) -> ReviewDecisions:
    """Validate album-review decisions independently of storage.

    Args:
        raw: Untrusted stored payload; existing tolerant validation is preserved.

    Returns:
        Original dictionary entries, preserving unknown fields.
    """
    if not isinstance(raw, dict):
        return {}
    decisions = {}
    for album_id, entry in raw.items():
        if isinstance(entry, dict):
            decisions[str(album_id)] = entry
    return decisions


def save_review_decisions(
    decisions: ReviewDecisions,
    decisions_path: Path = REVIEW_DECISIONS_PATH,
) -> None:
    """Persist review decisions atomically enough for CLI interruptions.

    Args:
        decisions: Mutable original decisions keyed by album identifier.
        decisions_path: Existing decisions file destination.
    """
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = decisions_path.with_suffix(f"{decisions_path.suffix}.tmp")
    with open(temporary_path, "w") as decisions_file:
        json.dump(decisions, decisions_file, ensure_ascii=False, indent=2)
        decisions_file.write("\n")
    temporary_path.replace(decisions_path)


def _state_access(
    decisions_path: Path, state_service: StateService | None
) -> BlockingRoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state_from(
        "review_album_limits",
        ReviewAlbumLimitsStateCodec(),
        StateLocation(decisions_path, REVIEW_DECISIONS_PATH, state_service),
    )


def _async_state_access(
    decisions_path: Path, state_service: StateService | None
) -> AsyncRoutineState:
    return AsyncRoutineState(_state_access(decisions_path, state_service))


def record_review_decision(
    decisions: ReviewDecisions,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    decision: str,
    decisions_path: Path = REVIEW_DECISIONS_PATH,
    live_liked_tracks: int | None = None,
    state_access: BlockingRoutineState | None = None,
) -> None:
    """Persist a user review decision for restart-safe reviews.

    Args:
        decisions: Mutable original decisions keyed by album identifier.
        album: Original validated library item.
        evaluation: Original assessment and source metadata.
        decision: Original user decision label.
        decisions_path: Existing decisions file destination.
        live_liked_tracks: Last live membership count, when available.
        state_access: Optional shared-state persistence boundary.
    """
    entry = {
        "decided_at": datetime.now(UTC).isoformat(),
        "decision": decision,
        "spotify_id": album.spotify_id,
        "album": album.album,
        "artist": album.artist,
        "liked_tracks": evaluation.liked_tracks,
        "total_tracks": evaluation.total_tracks,
        "liked_ratio": evaluation.liked_ratio,
        "threshold": evaluation.threshold,
        "from_cache": evaluation.from_cache,
        "source": evaluation.source,
    }
    if live_liked_tracks is not None:
        entry["live_liked_tracks"] = live_liked_tracks
    decisions[album.spotify_id] = entry
    if state_access is None:
        save_review_decisions(decisions, decisions_path)
    else:
        # Widen only the known entry values; retain the caller mapping identity.
        state_access.save(cast(dict[str, object], decisions))


def has_persisted_keep_decision(
    album: YourLibraryAlbum,
    decisions: ReviewDecisions,
) -> bool:
    """Return whether this album was explicitly kept in a previous run.

    Args:
        album: Original validated library item.
        decisions: Mutable original decisions keyed by album identifier.

    Returns:
        Whether the stored decision equals keep.
    """
    return decisions.get(album.spotify_id, {}).get("decision") == "keep"


def append_removed_album_log(
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    action: str = "manual",
    live_liked_tracks: int | None = None,
) -> None:
    """Append one removed-album event as JSON Lines.

    Args:
        album: Original validated library item.
        evaluation: Original assessment and source metadata.
        log_path: Original audit file destination.
        action: Original removal reason retained in the audit.
        live_liked_tracks: Last live membership count, when available.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "removed_at": datetime.now(UTC).isoformat(),
        "action": action,
        "spotify_id": album.spotify_id,
        "album": album.album,
        "artist": album.artist,
        "liked_tracks": evaluation.liked_tracks,
        "total_tracks": evaluation.total_tracks,
        "liked_ratio": evaluation.liked_ratio,
        "threshold": evaluation.threshold,
        "from_cache": evaluation.from_cache,
        "source": evaluation.source,
    }
    if live_liked_tracks is not None:
        entry["live_liked_tracks"] = live_liked_tracks
    with open(log_path, "a") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def track_ids_from_evaluation(evaluation: AlbumEvaluation) -> list[str]:
    """Return Spotify track ids known for an album evaluation.

    Args:
        evaluation: Original assessment and source metadata.

    Returns:
        Truthy identifiers in the original track order.
    """
    return [track.spotify_id for track in evaluation.tracks if track.spotify_id]


async def async_get_live_liked_track_count(sp: Spotify, track_ids: list[str]) -> int:
    """Count album tracks currently saved by the user in Spotify.

    Args:
        sp: Caller-owned synchronous Spotify client.
        track_ids: Ordered original track identifiers, including duplicates.

    Returns:
        Number of truthy observed membership statuses.
    """
    liked_count = 0
    for start in range(0, len(track_ids), TRACK_CONTAINS_BATCH_SIZE):
        batch = track_ids[start : start + TRACK_CONTAINS_BATCH_SIZE]
        try:
            response = await sp.current_user_saved_tracks_contains(batch)
            saved_statuses = cast(list[bool], response)
        except SpotifyException as exc:
            handle_spotify_exception(exc)
        liked_count += sum(1 for is_saved in saved_statuses if is_saved)
    return liked_count


async def async_remove_album_from_library(
    sp: Spotify,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    remaining_albums: list[YourLibraryAlbum],
    log_path: Path,
    action: str = "manual",
    live_liked_tracks: int | None = None,
) -> list[YourLibraryAlbum]:
    """Remove an album from Spotify and persist the local removal immediately.

    Args:
        sp: Caller-owned synchronous Spotify client.
        album: Original validated library item.
        evaluation: Original assessment and source metadata.
        remaining_albums: Current ordered mirror snapshot.
        log_path: Original audit file destination.
        action: Original removal reason retained in the audit.
        live_liked_tracks: Last live membership count, when available.

    Returns:
        Mirror contents after the completed deletion and audit.
    """
    try:
        await sp.current_user_saved_albums_delete([album.spotify_id])
    except SpotifyException as exc:
        handle_spotify_exception(exc)

    updated_albums = remove_first_matching_album(remaining_albums, album.spotify_id)
    async with blocking_capacity():
        albums_write = asyncio.create_task(
            asyncio.to_thread(save_total_albums_new_file, updated_albums)
        )
        await finish_blocking(albums_write)
    async with blocking_capacity():
        file_operation = asyncio.create_task(
            asyncio.to_thread(
                append_removed_album_log,
                album,
                evaluation,
                log_path=log_path,
                action=action,
                live_liked_tracks=live_liked_tracks,
            )
        )
        await finish_blocking(file_operation)
    return updated_albums


async def _is_artist_followed(sp: Spotify, artist: AlbumArtist) -> bool:
    try:
        response = await sp.current_user_following_artists([artist.spotify_id])
        followed_response = cast(list[bool], response)
    except SpotifyException as exc:
        handle_spotify_exception(exc)
    return bool(followed_response[0]) if followed_response else False


async def _follow_artist(sp: Spotify, artist: AlbumArtist) -> None:
    try:
        await sp.user_follow_artists([artist.spotify_id])
    except SpotifyException as exc:
        handle_spotify_exception(exc)


async def async_ensure_artist_followed(
    sp: Spotify,
    album: YourLibraryAlbum,
    known_artist_ids: dict[str, str],
    checked_artist_ids: set[str],
    echo: Echo,
) -> bool:
    """Follow the album artist through the shared application decision.

    Args:
        sp: Caller-owned Spotify client.
        album: Current review item.
        known_artist_ids: Run-scoped artist-name resolution cache.
        checked_artist_ids: Run-scoped completed artist checks.
        echo: Existing output callback.

    Returns:
        Whether a new follow and its persistence completed.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyException: A different Spotify error occurs.
    """
    from spotify_manager.bootstrap.album_limits import follow_review_artist
    from spotify_manager.interfaces.presenters.album_limits import present_artist_follow

    outcome = await follow_review_artist(
        sp, album, known_artist_ids, checked_artist_ids
    )
    present_artist_follow(outcome, album, echo)
    return outcome.action == "followed"


async def async_review_album_limits(
    sp: Spotify,
    action_reader: ActionReader,
    threshold: float = 0.5,
    use_cache: bool = True,
    refresh_cache: bool = False,
    echo: Echo = STANDARD_OUTPUT,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    decisions_path: Path | None = None,
    state_service: StateService | None = None,
    progress_callback: ProgressCallback | None = None,
    sleep: Sleep = asyncio,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
) -> None:
    """Review saved albums through an injected application use case.

    Args:
        sp: Caller-owned Spotify client.
        action_reader: Interface choice callback.
        threshold: Existing retention threshold.
        use_cache: Read cached track lists when available.
        refresh_cache: Refresh track lists before evaluation.
        echo: Existing message sink.
        log_path: Removal audit destination.
        decisions_path: Optional explicit legacy decisions path.
        state_service: Optional shared-state service.
        progress_callback: Optional completion and cancellation callback.
        sleep: Existing retry wait callback.
        transient_retry_delay_seconds: Existing retry delay.
        transient_max_attempts: Existing retry limit.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyTransientServerError: The configured retry policy is exhausted.
    """
    from spotify_manager.interfaces.operations.review_album_limits import (
        review_album_limits as operation,
    )

    return await operation(
        sp,
        action_reader,
        threshold,
        use_cache,
        refresh_cache,
        echo,
        log_path,
        decisions_path,
        state_service,
        progress_callback,
        sleep,
        transient_retry_delay_seconds,
        transient_max_attempts,
    )


def resolve_album_artist(
    sp: LegacySpotify, album: YourLibraryAlbum, known_artist_ids: dict[str, str]
) -> AlbumArtist | None:
    """Resolve the artist using original local-name and primary-credit rules.

    Args:
        sp: Caller-owned client.
        album: Original review item.
        known_artist_ids: Mutable run-scoped name cache.

    Returns:
        Resolved identity, or None for absent metadata/identifier.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyException: Other Spotify failures retain their original type.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_resolve_album_artist(legacy_spotify(sp), album, known_artist_ids)
    )


def update_stats_history_for_followed_artist() -> bool:
    """Record one newly followed artist in stats_history.json.

    Returns:
        Whether a nonempty history was updated.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_update_stats_history_for_followed_artist())


def record_followed_artist(artist: AlbumArtist) -> ArtistPersistenceResult:
    """Persist a newly followed artist to local files.

    Args:
        artist: Resolved Spotify artist identity.

    Returns:
        Original mirror and statistics publication flags.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_record_followed_artist(artist))


def get_live_liked_track_count(sp: LegacySpotify, track_ids: list[str]) -> int:
    """Count album tracks currently saved by the user in Spotify.

    Args:
        sp: Caller-owned synchronous Spotify client.
        track_ids: Ordered original track identifiers, including duplicates.

    Returns:
        Number of truthy observed membership statuses.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_get_live_liked_track_count(legacy_spotify(sp), track_ids))


def remove_album_from_library(
    sp: LegacySpotify,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    remaining_albums: list[YourLibraryAlbum],
    log_path: Path,
    action: str = "manual",
    live_liked_tracks: int | None = None,
) -> list[YourLibraryAlbum]:
    """Remove an album from Spotify and persist the local removal immediately.

    Args:
        sp: Caller-owned synchronous Spotify client.
        album: Original validated library item.
        evaluation: Original assessment and source metadata.
        remaining_albums: Current ordered mirror snapshot.
        log_path: Original audit file destination.
        action: Original removal reason retained in the audit.
        live_liked_tracks: Last live membership count, when available.

    Returns:
        Mirror contents after the completed deletion and audit.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_remove_album_from_library(
            legacy_spotify(sp),
            album,
            evaluation,
            remaining_albums,
            log_path,
            action,
            live_liked_tracks,
        )
    )


def ensure_artist_followed(
    sp: LegacySpotify,
    album: YourLibraryAlbum,
    known_artist_ids: dict[str, str],
    checked_artist_ids: set[str],
    echo: Echo,
) -> bool:
    """Follow the album artist through the shared application decision.

    Args:
        sp: Caller-owned Spotify client.
        album: Current review item.
        known_artist_ids: Run-scoped artist-name resolution cache.
        checked_artist_ids: Run-scoped completed artist checks.
        echo: Existing output callback.

    Returns:
        Whether a new follow and its persistence completed.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyException: A different Spotify error occurs.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_ensure_artist_followed(
            legacy_spotify(sp), album, known_artist_ids, checked_artist_ids, echo
        )
    )


def review_album_limits(
    sp: LegacySpotify,
    action_reader: ActionReader | LegacyAlbumAction,
    threshold: float = 0.5,
    use_cache: bool = True,
    refresh_cache: bool = False,
    echo: Echo = STANDARD_OUTPUT,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    decisions_path: Path | None = None,
    state_service: StateService | None = None,
    progress_callback: ProgressCallback | None = None,
    sleep: Sleep | LegacyWait = asyncio,
    transient_retry_delay_seconds: int = TRANSIENT_RETRY_DELAY_SECONDS,
    transient_max_attempts: int = TRANSIENT_MAX_ATTEMPTS,
) -> None:
    """Review saved albums through an injected application use case.

    Args:
        sp: Caller-owned Spotify client.
        action_reader: Interface choice callback.
        threshold: Existing retention threshold.
        use_cache: Read cached track lists when available.
        refresh_cache: Refresh track lists before evaluation.
        echo: Existing message sink.
        log_path: Removal audit destination.
        decisions_path: Optional explicit legacy decisions path.
        state_service: Optional shared-state service.
        progress_callback: Optional completion and cancellation callback.
        sleep: Existing retry wait callback.
        transient_retry_delay_seconds: Existing retry delay.
        transient_max_attempts: Existing retry limit.

    Raises:
        SpotifyRateLimitError: Spotify reports a rate limit.
        SpotifyTransientServerError: The configured retry policy is exhausted.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.album_limits import (
        PythonAlbumAction,
    )
    from spotify_manager.infrastructure.python_compat.runtime import PythonWait
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_review_album_limits(
            legacy_spotify(sp),
            PythonAlbumAction(action_reader),
            threshold,
            use_cache,
            refresh_cache,
            echo,
            log_path,
            decisions_path,
            state_service,
            progress_callback,
            PythonWait(sleep),
            transient_retry_delay_seconds,
            transient_max_attempts,
        )
    )
