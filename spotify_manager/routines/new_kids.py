"""Advance artists through New Kids on the Block's four-release review."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from spotipy import Spotify

from spotify_manager.application import composer_progression
from spotify_manager.application import composer_routes
from spotify_manager.application import new_kids_state as discovery_state
from spotify_manager.application.new_kids_values import (
    ArtistAssessment as ArtistAssessment,
)
from spotify_manager.application.new_kids_values import FillResult as FillResult
from spotify_manager.application.new_kids_values import FlushResult as FlushResult
from spotify_manager.application.new_kids_values import FlushSummary as FlushSummary
from spotify_manager.application.new_kids_values import (
    NewKidsConfigError as NewKidsConfigError,
)
from spotify_manager.application.new_kids_values import NewKidsError as NewKidsError
from spotify_manager.application.new_kids_values import (
    NewKidsStateError as NewKidsStateError,
)
from spotify_manager.application.new_kids_values import Queue2Summary as Queue2Summary
from spotify_manager.application.release_evaluation import evaluate_catalog_release
from spotify_manager.core.library_data.runtime import publish_managed_path
from spotify_manager.core.state import RoutineState
from spotify_manager.core.state import StateService
from spotify_manager.core.state.compat import routine_state
from spotify_manager.domain import completion

# UFI
from spotify_manager.domain import discovery_history as history_policy
from spotify_manager.domain import discovery_progression as discovery_policy
from spotify_manager.domain import releases as release_policy
from spotify_manager.domain.discovery import CatalogTrack as CatalogTrack
from spotify_manager.domain.discovery import RankedRelease as RankedRelease
from spotify_manager.domain.discovery import ReleaseTier as ReleaseTier
from spotify_manager.domain.discovery_assessment import qualification_reasons
from spotify_manager.domain.discovery_progression import (
    DECORATED_PATTERN as DECORATED_PATTERN,
)
from spotify_manager.domain.discovery_progression import LIVE_PATTERN as LIVE_PATTERN
from spotify_manager.domain.releases import release_identity
from spotify_manager.infrastructure.library_records import REMOVED_ALBUMS_LOG_PATH
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import composer_playlists
from spotify_manager.routines import new_wine
from spotify_manager.routines import scrobble_history
from spotify_manager.routines.recover_removed_albums import sync_stats_history_counts
from spotify_manager.routines.review_album_limits import (
    append_removed_album_log as append_removed_album_log,
)
from spotify_manager.routines.review_artists import add_playlist_item
from spotify_manager.routines.review_artists import remove_library_artists
from spotify_manager.routines.review_artists import remove_playlist_items
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_STATE_PATH = FILES_DIR / "new_kids_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "new_kids_log.jsonl"
DEFAULT_QUEUE_2_LOG_PATH = FILES_DIR / "queue_2_log.jsonl"
DEFAULT_ALBUMS_PATH = FILES_DIR / "albums_total_new.json"
DEFAULT_ARTISTS_PATH = FILES_DIR / "artists_total.json"
DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH

STATE_VERSION = 1
PLAYLIST_CAP = 10
QUEUE_2_DAILY_LIMIT = 10
RELEASES_PER_ARTIST = 4
COMPOSER_TRACKS_PER_ARTIST = 40
MIN_SCROBBLED_TRACKS_PER_RELEASE = 3
ARTIST_RELEASE_PAGE_SIZE = 50
ALBUM_BATCH_SIZE = 20
CONTAINS_BATCH_SIZE = 20
TRACK_BATCH_SIZE = 50
CHOICE_SKIP = "__skip__"
CHOICE_QUIT = "__quit__"


Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = Callable[[Callable[[], object], str], object]


ChoiceCandidate = RankedRelease | composer_playlists.OwnedPlaylist
ReleaseChoiceReader = Callable[[str, tuple[ChoiceCandidate, ...]], str]


AnnualReleaseKey = history_policy.AnnualReleaseKey
AnnualScrobbleIndex = history_policy.AnnualScrobbleIndex


def parse_playlist_id(value: str | None, variable: str) -> str:
    """Parse a required Spotify playlist setting."""
    try:
        return new_wine.parse_playlist_id(value, variable)
    except new_wine.NewWineConfigError as exc:
        raise NewKidsConfigError(str(exc)) from exc


def _positive_int(value: object, fallback: int = 0) -> int:
    return discovery_state.positive_int(value, fallback)


def _annual_release_key(artist: str, release: str) -> AnnualReleaseKey:
    """Return the edition-tolerant Last.fm identity for one artist release."""
    return history_policy.annual_release_key(artist, release)


def _scrobble_track_identity(name: str) -> str:
    """Normalize one Last.fm or Spotify track title across edition suffixes."""
    return history_policy.scrobble_track_identity(name)


def load_annual_scrobble_index(
    path: Path = DEFAULT_SCROBBLES_PATH,
    *,
    year: int,
) -> AnnualScrobbleIndex:
    """Index distinct release tracks scrobbled in one Berlin calendar year.

    Args:
        path: Existing Last.fm export path.
        year: Active local calendar year.

    Returns:
        Nonempty normalized titles grouped by artist/release identity.

    Raises:
        NewKidsStateError: Loading or decoding the source export fails.
    """
    try:
        scrobbles_by_date = blast_from_past.load_scrobbles_by_date(path)
    except blast_from_past.LastFmExportError as exc:
        raise NewKidsStateError(
            f"Could not load the {year} Last.fm scrobble history: {exc}"
        ) from exc

    return history_policy.annual_scrobble_index(scrobbles_by_date, year)


def refresh_scrobbles_for_release_progress(
    lastfm: scrobble_history.LastFmReader,
    username: str,
    *,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    echo: Echo = print,
) -> scrobble_history.ScrobbleHistorySummary:
    """Refresh the shared history before deriving annual release progress."""
    canonical_path = scrobbles_path.resolve() == DEFAULT_SCROBBLES_PATH.resolve()
    summary = scrobble_history.refresh_scrobble_history(
        lastfm,
        expected_username=username,
        export_path=scrobbles_path,
        legacy_delta_path=(
            scrobble_history.DEFAULT_LEGACY_DELTA_PATH if canonical_path else None
        ),
        backup_dir=(
            scrobble_history.DEFAULT_BACKUP_DIR
            if canonical_path
            else scrobbles_path.parent / "lastfm_history_backups"
        ),
        log_path=(
            scrobble_history.DEFAULT_LOG_PATH
            if canonical_path
            else scrobbles_path.parent / "scrobble_history_update_log.jsonl"
        ),
        dry_run=False,
        progress_callback=echo,
    )
    echo(
        "Last.fm release history ready: "
        f"{summary.live_scrobbles_added} new scrobble(s), "
        f"{summary.total_scrobbles} total."
    )
    return summary


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    pairs: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or spotify_id).strip()
        if spotify_id:
            pairs.append((spotify_id, name))
    return tuple(pairs)


def _track_position(value: object, fallback: int) -> int:
    parsed = _positive_int(value)
    return parsed if parsed > 0 else fallback


def _release_type(
    raw_type: object,
    total_tracks: int,
    name: str,
) -> tuple[str, ReleaseTier]:
    return discovery_policy.release_kind(raw_type, total_tracks, name)


def _release_date_key(value: str) -> tuple[int, int, int, str]:
    return release_policy.review_date_key(value)


def _raw_release(
    raw: object,
    artist_id: str,
    saved: bool,
    top_track_rank: int | None,
) -> RankedRelease | None:
    if not isinstance(raw, dict):
        return None
    artists = _artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or spotify_id).strip()
    if not spotify_id or not uri or not name:
        return None
    total_tracks = _positive_int(raw.get("total_tracks"))
    release_type, tier = _release_type(raw.get("album_type"), total_tracks, name)
    raw_popularity = raw.get("popularity")
    popularity = raw_popularity if isinstance(raw_popularity, int) else None
    return RankedRelease(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=release_type,
        release_date=str(raw.get("release_date") or "Unknown"),
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        popularity=popularity,
        top_track_rank=top_track_rank,
        tier=tier,
        identity=release_identity(name),
        saved=saved,
        plain=not DECORATED_PATTERN.search(name),
    )


def _source_release(source: new_wine.PlaylistTrack) -> RankedRelease:
    return discovery_policy.source_release(source)


def _composer_release(
    source: new_wine.PlaylistTrack,
    artist_id: str,
    artist_name: str,
) -> RankedRelease:
    """Represent a works-playlist track's release under the logical composer."""
    return discovery_policy.composer_release(source, artist_id, artist_name)


def _composer_track(
    source: new_wine.PlaylistTrack,
    artist_id: str,
    artist_name: str,
) -> CatalogTrack:
    """Adapt one works-playlist marker to the normal durable track model."""
    return discovery_policy.composer_track(source, artist_id, artist_name)


def _composer_source_index(
    source: new_wine.PlaylistTrack,
    tracks: tuple[new_wine.PlaylistTrack, ...],
) -> int | None:
    """Locate the current marker by id, then by one unique normalized title."""
    return discovery_policy.composer_source_index(source, tracks)


def _composer_step(
    source: new_wine.PlaylistTrack,
    tracks: tuple[new_wine.PlaylistTrack, ...],
) -> tuple[int, new_wine.PlaylistTrack | None]:
    """Return completed works and the next marker in stored playlist order."""
    return composer_progression.composer_step(
        source, tracks, COMPOSER_TRACKS_PER_ARTIST
    )


def _resolve_composer_playlist(
    state: dict[str, object],
    artist_id: str,
    artist_name: str,
    source_track_id: str,
    owned_playlists: tuple[composer_playlists.OwnedPlaylist, ...],
    excluded_playlist_ids: frozenset[str],
    choice_reader: ReleaseChoiceReader,
) -> tuple[composer_playlists.OwnedPlaylist | None, str | None]:
    """Resolve and remember one owned works playlist for a logical artist."""
    return composer_routes.resolve_composer_route(
        state,
        artist_id,
        artist_name,
        source_track_id,
        owned_playlists,
        excluded_playlist_ids,
        choice_reader,
        _utc_now,
    )


def _composer_plan(
    source: new_wine.PlaylistTrack,
    artist_id: str,
    artist_name: str,
    playlist: composer_playlists.OwnedPlaylist,
    tracks: tuple[new_wine.PlaylistTrack, ...],
    *,
    current_liked: bool,
    assessment: ArtistAssessment | None,
) -> dict[str, object]:
    """Plan one of the first forty works in stored Spotify playlist order."""
    return composer_progression.composer_plan(
        source,
        artist_id,
        artist_name,
        playlist,
        tracks,
        current_liked=current_liked,
        assessment=assessment,
        limit=COMPOSER_TRACKS_PER_ARTIST,
    )


def _batched_contains(
    ids: list[str],
    operation: Callable[[list[str]], object],
    resource: str,
    retry_call: RetryCall,
) -> dict[str, bool]:
    statuses: dict[str, bool] = {}
    for start in range(0, len(ids), CONTAINS_BATCH_SIZE):
        batch = ids[start : start + CONTAINS_BATCH_SIZE]
        response = retry_call(
            partial(operation, batch),
            f"checking {len(batch)} {resource}",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise NewKidsError(f"Spotify returned invalid {resource} statuses.")
        statuses.update(
            {
                spotify_id: bool(status)
                for spotify_id, status in zip(batch, response, strict=True)
            }
        )
    return statuses


def load_top_track_data(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[dict[str, int], tuple[CatalogTrack, ...]]:
    """Load primary-artist Spotify top tracks and their release ranks."""
    response = retry_call(
        partial(sp.artist_top_tracks, artist_id),
        f"loading top tracks for artist {artist_id}",
    )
    raw_tracks = response.get("tracks") if isinstance(response, dict) else None
    if not isinstance(raw_tracks, list):
        raise NewKidsError("Spotify returned invalid artist top tracks.")
    album_ranks: dict[str, int] = {}
    tracks: list[CatalogTrack] = []
    for rank, raw_track in enumerate(raw_tracks, start=1):
        if not isinstance(raw_track, dict):
            continue
        artists = _artist_pairs(raw_track.get("artists"))
        raw_album = raw_track.get("album")
        if not isinstance(raw_album, dict):
            continue
        album_artists = _artist_pairs(raw_album.get("artists"))
        if (
            not artists
            or artists[0][0] != artist_id
            or not album_artists
            or album_artists[0][0] != artist_id
        ):
            continue
        track_id = str(raw_track.get("id") or "").strip()
        uri = str(raw_track.get("uri") or "").strip()
        album_id = str(raw_album.get("id") or "").strip()
        if not track_id or not uri:
            continue
        if album_id:
            album_ranks.setdefault(album_id, rank)
        raw_popularity = raw_track.get("popularity")
        tracks.append(
            CatalogTrack(
                spotify_id=track_id,
                uri=uri,
                name=str(raw_track.get("name") or track_id),
                disc_number=_track_position(raw_track.get("disc_number"), 1),
                track_number=_track_position(raw_track.get("track_number"), rank),
                primary_artist_id=artists[0][0],
                primary_artist_name=artists[0][1],
                popularity=(
                    raw_popularity if isinstance(raw_popularity, int) else None
                ),
            )
        )
    return album_ranks, tuple(tracks)


def load_ranked_catalog(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[RankedRelease, ...]:
    """Load canonical releases using album popularity and top-track fallback."""
    simplified: dict[str, dict[str, object]] = {}
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.artist_albums,
                artist_id,
                include_groups="album,single,compilation",
                limit=ARTIST_RELEASE_PAGE_SIZE,
                offset=offset,
            ),
            f"loading releases for artist {artist_id} at offset {offset}",
        )
        if not isinstance(response, dict):
            raise NewKidsError("Spotify returned invalid artist releases.")
        raw_items = response.get("items")
        if not isinstance(raw_items, list):
            raise NewKidsError("Spotify returned invalid artist releases.")
        for raw_release in raw_items:
            if not isinstance(raw_release, dict):
                continue
            artists = _artist_pairs(raw_release.get("artists"))
            release_id = str(raw_release.get("id") or "").strip()
            if artists and artists[0][0] == artist_id and release_id:
                simplified[release_id] = raw_release
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewKidsError("Spotify returned an empty release page.")

    release_ids = list(simplified)
    if not release_ids:
        return ()
    saved = _batched_contains(
        release_ids,
        sp.current_user_saved_albums_contains,
        "Saved Albums",
        retry_call,
    )
    top_ranks, _top_tracks = load_top_track_data(sp, artist_id, retry_call)

    full_by_id: dict[str, dict[str, object]] = {}
    for start in range(0, len(release_ids), ALBUM_BATCH_SIZE):
        batch = release_ids[start : start + ALBUM_BATCH_SIZE]
        response = retry_call(
            partial(sp.albums, batch),
            f"loading popularity for {len(batch)} releases",
        )
        raw_albums = response.get("albums") if isinstance(response, dict) else None
        if not isinstance(raw_albums, list):
            raise NewKidsError("Spotify returned invalid album details.")
        for raw_album in raw_albums:
            if not isinstance(raw_album, dict):
                continue
            album_id = str(raw_album.get("id") or "").strip()
            if album_id:
                full_by_id[album_id] = raw_album

    candidates: list[RankedRelease] = []
    for release_id in release_ids:
        raw = full_by_id.get(release_id, simplified[release_id])
        candidate = _raw_release(
            raw,
            artist_id,
            saved.get(release_id, False),
            top_ranks.get(release_id),
        )
        if candidate is not None:
            candidates.append(candidate)

    editions: dict[tuple[str, ReleaseTier], list[RankedRelease]] = defaultdict(list)
    for candidate in candidates:
        editions[(candidate.identity, candidate.tier)].append(candidate)

    canonical: list[RankedRelease] = []
    for group in editions.values():
        canonical.append(
            min(
                group,
                key=lambda release: (
                    not release.saved,
                    not release.plain,
                    release.tier,
                    -(release.popularity if release.popularity is not None else -1),
                    release.top_track_rank or 9999,
                    release.total_tracks,
                    _release_date_key(release.release_date),
                    release.name.casefold(),
                ),
            )
        )
    return tuple(
        sorted(
            canonical,
            key=lambda release: (
                release.tier,
                release.popularity is None,
                -(release.popularity or 0),
                release.top_track_rank or 9999,
                _release_date_key(release.release_date),
                release.name.casefold(),
                release.spotify_id,
            ),
        )
    )


def load_release_tracks(
    sp: Spotify,
    release: RankedRelease,
    retry_call: RetryCall,
) -> tuple[CatalogTrack, ...]:
    """Load an ordered release track list with primary artist credits."""
    tracks: list[CatalogTrack] = []
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.album_tracks,
                release.spotify_id,
                limit=50,
                offset=offset,
            ),
            f"loading {release.name} at offset {offset}",
        )
        if not isinstance(response, dict):
            raise NewKidsError(f"Spotify returned invalid tracks for {release.name}.")
        raw_items = response.get("items")
        if not isinstance(raw_items, list):
            raise NewKidsError(f"Spotify returned invalid tracks for {release.name}.")
        for raw_track in raw_items:
            if not isinstance(raw_track, dict):
                continue
            artists = _artist_pairs(raw_track.get("artists"))
            track_id = str(raw_track.get("id") or "").strip()
            uri = str(raw_track.get("uri") or "").strip()
            if not artists or not track_id or not uri:
                continue
            tracks.append(
                CatalogTrack(
                    spotify_id=track_id,
                    uri=uri,
                    name=str(raw_track.get("name") or track_id),
                    disc_number=_track_position(raw_track.get("disc_number"), 1),
                    track_number=_track_position(
                        raw_track.get("track_number"),
                        len(tracks) + 1,
                    ),
                    primary_artist_id=artists[0][0],
                    primary_artist_name=artists[0][1],
                )
            )
        offset += len(raw_items)
        if not response.get("next"):
            break
        if not raw_items:
            raise NewKidsError(f"Spotify returned an empty page for {release.name}.")
    return tuple(
        sorted(tracks, key=lambda track: (track.disc_number, track.track_number))
    )


def release_was_played_this_year(
    release: RankedRelease,
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
    annual_scrobbles: AnnualScrobbleIndex,
) -> bool:
    """Evaluate completion after applying the existing title and credit codecs.

    Args:
        release: Release being reviewed.
        tracks: Its parsed catalog tracks.
        liked: Observed liked statuses, with missing entries treated as false.
        annual_scrobbles: Current-year normalized titles grouped by artist/release.

    Returns:
        Whether enough distinct titles and every liked title were played.
    """
    return history_policy.release_was_played(
        release, tracks, liked, annual_scrobbles, MIN_SCROBBLED_TRACKS_PER_RELEASE
    )


def release_scrobble_threshold(release: RankedRelease) -> int:
    """Return the pure completion threshold for this release tier.

    Args:
        release: Parsed review-catalog release.

    Returns:
        Studio minimum or the single-track fallback minimum.
    """
    return completion.scrobble_threshold(release.tier, MIN_SCROBBLED_TRACKS_PER_RELEASE)


def release_review_catalog(
    catalog: tuple[RankedRelease, ...],
) -> tuple[RankedRelease, ...]:
    """Use fallback releases only when fewer than four studio releases exist.

    Args:
        catalog: Original ordered catalog, retaining duplicate entries.

    Returns:
        Preferred studios when sufficient, otherwise the complete catalog.
    """
    return history_policy.review_catalog(catalog, RELEASES_PER_ARTIST)


def played_releases_from_history(
    sp: Spotify,
    catalog: tuple[RankedRelease, ...],
    annual_scrobbles: AnnualScrobbleIndex,
    retry_call: RetryCall,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
    liked_cache: dict[str, bool],
) -> tuple[RankedRelease, ...]:
    """Return catalog releases completed according to current-year Last.fm data.

    Args:
        sp: Caller-owned synchronous Spotify client.
        catalog: Original ranked catalog observations.
        annual_scrobbles: Current-year normalized listening evidence.
        retry_call: Existing retry/cancellation callback.
        track_cache: Shared run-owned catalog observations, updated in place.
        liked_cache: Shared run-owned memberships, updated in place.

    Returns:
        Completed entries in catalog order, retaining duplicates.

    Raises:
        NewKidsError: Spotify returns malformed release observations.
        new_wine.NewWineError: Spotify returns malformed liked statuses.
    """
    from spotify_manager.bootstrap.release_history import observe_played_releases

    return observe_played_releases(
        sp,
        catalog,
        annual_scrobbles,
        retry_call,
        track_cache,
        liked_cache,
        release_limit=RELEASES_PER_ARTIST,
        studio_minimum=MIN_SCROBBLED_TRACKS_PER_RELEASE,
    )


def _default_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "artists": {},
        "composer_routes": {},
        "great_discoveries_playlists": {},
        "active_run": None,
        "queue_2_active_run": None,
    }


def validate_state(raw: object) -> dict[str, Any]:
    """Validate the New Kids namespace independently of its storage."""
    if isinstance(raw, dict) and raw.get("version") == STATE_VERSION:
        raw.setdefault("composer_routes", {})
    if (
        not isinstance(raw, dict)
        or raw.get("version") != STATE_VERSION
        or not isinstance(raw.get("artists"), dict)
        or not isinstance(raw.get("composer_routes"), dict)
        or not isinstance(raw.get("great_discoveries_playlists"), dict)
    ):
        raise NewKidsStateError("New Kids state is invalid.")
    return raw


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    """Load durable artist and active-run progress."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewKidsStateError(f"Could not read New Kids state: {path}") from exc
    try:
        return validate_state(raw)
    except NewKidsStateError as exc:
        raise NewKidsStateError(f"New Kids state is invalid: {path}") from exc


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically save durable artist and active-run progress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewKidsStateError(f"Could not save New Kids state: {path}") from exc


def _state_access(
    state_path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="new_kids",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=state_path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=load_state,
        legacy_saver=save_state,
        service=state_service,
    )


def append_event(path: Path, event: str, **details: object) -> None:
    """Append one mutation or decision to the audit log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "event": event,
        **details,
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise NewKidsStateError(f"Could not append New Kids log: {path}") from exc


def _source_from_record(raw: object) -> new_wine.PlaylistTrack:
    return discovery_state.source_from_record(raw)


def _release_from_record(raw: object) -> RankedRelease:
    return discovery_state.release_from_record(raw)


def _track_from_record(raw: object) -> CatalogTrack | None:
    return discovery_state.track_from_record(raw)


def _artist_progress(
    state: dict[str, object],
    source: new_wine.PlaylistTrack,
    artist_id: str,
    artist_name: str,
) -> dict[str, object]:
    return discovery_state.artist_progress(
        state, source, artist_id, artist_name, _utc_now
    )


def _track_index(
    tracks: tuple[CatalogTrack, ...],
    source: new_wine.PlaylistTrack,
) -> int | None:
    return discovery_policy.catalog_track_index(tracks, source)


def _live_evaluation(
    release: RankedRelease,
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
) -> AlbumEvaluation:
    return evaluate_catalog_release(release, tracks, liked)


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NewKidsStateError(f"Could not read local mirror: {path}") from exc
    if not isinstance(raw, list):
        raise NewKidsStateError(f"Local mirror is invalid: {path}")
    return raw


def _write_json_list(path: Path, values: list[object]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(values, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise NewKidsStateError(f"Could not update local mirror: {path}") from exc
    publish_managed_path(path, source="New Kids library reconciliation")


def _sync_local_album(
    release: RankedRelease,
    should_save: bool,
    path: Path,
) -> bool:
    raw = _read_json_list(path)
    albums = [YourLibraryAlbum.model_validate(item) for item in raw]
    present = any(album.spotify_id == release.spotify_id for album in albums)
    if present == should_save:
        return False
    if should_save:
        albums.append(
            YourLibraryAlbum(
                artist=release.primary_artist_name,
                album=release.name,
                uri=release.uri,
            )
        )
        albums.sort(key=album_sort_key)
    else:
        albums = [album for album in albums if album.spotify_id != release.spotify_id]
    _write_json_list(path, [album.model_dump(mode="json") for album in albums])
    if path == DEFAULT_ALBUMS_PATH:
        sync_stats_history_counts(total_albums=len(albums))
    return True


def remove_local_artist(artist_id: str, path: Path = DEFAULT_ARTISTS_PATH) -> bool:
    """Remove one unfollowed artist from the local mirror and update stats."""
    raw = _read_json_list(path)
    artists = [YourLibraryArtist.model_validate(item) for item in raw]
    updated = [artist for artist in artists if artist.spotify_id != artist_id]
    if len(updated) == len(artists):
        return False
    updated.sort(key=artist_sort_key)
    _write_json_list(path, [artist.model_dump(mode="json") for artist in updated])
    if path == DEFAULT_ARTISTS_PATH:
        sync_stats_history_counts(total_artists=len(updated))
    return True


def _reconcile_release_library(
    sp: Spotify,
    release: RankedRelease,
    evaluation: AlbumEvaluation,
    *,
    dry_run: bool,
    retry_call: RetryCall,
    albums_path: Path,
    removed_albums_log_path: Path,
    log_path: Path,
    echo: Echo,
) -> str:
    from spotify_manager.bootstrap.new_kids import library_reconciliation

    service = library_reconciliation(
        sp, retry_call, albums_path, removed_albums_log_path, log_path, echo, dry_run
    )
    return service.reconcile(release, evaluation)


def _release_saved(sp: Spotify, release: RankedRelease, retry_call: RetryCall) -> bool:
    response = retry_call(
        partial(sp.current_user_saved_albums_contains, [release.spotify_id]),
        f"checking whether {release.name} is saved",
    )
    return bool(response[0]) if isinstance(response, list) and response else False


def _save_release(sp: Spotify, release: RankedRelease, retry_call: RetryCall) -> None:
    retry_call(
        partial(sp.current_user_saved_albums_add, [release.spotify_id]),
        f"saving {release.name}",
    )


def _remove_release(sp: Spotify, release: RankedRelease, retry_call: RetryCall) -> None:
    retry_call(
        partial(sp.current_user_saved_albums_delete, [release.spotify_id]),
        f"unsaving {release.name}",
    )


def _catalog_track_popularities(
    sp: Spotify,
    track_ids: list[str],
    retry_call: RetryCall,
) -> dict[str, int]:
    popularities: dict[str, int] = {}
    for start in range(0, len(track_ids), TRACK_BATCH_SIZE):
        batch = track_ids[start : start + TRACK_BATCH_SIZE]
        response = retry_call(
            partial(sp.tracks, batch),
            f"loading popularity for {len(batch)} tracks",
        )
        raw_tracks = response.get("tracks") if isinstance(response, dict) else None
        if not isinstance(raw_tracks, list):
            raise NewKidsError("Spotify returned invalid track details.")
        for raw_track in raw_tracks:
            if not isinstance(raw_track, dict):
                continue
            track_id = str(raw_track.get("id") or "").strip()
            popularity = raw_track.get("popularity")
            if track_id and isinstance(popularity, int):
                popularities[track_id] = popularity
    return popularities


def _promotion_reasons(
    catalog: tuple[RankedRelease, ...],
    saved: dict[str, bool],
    *,
    liked_tracks: int,
    total_tracks: int,
) -> tuple[str, ...]:
    """Translate parsed catalog facts into stable legacy promotion messages.

    Args:
        catalog: Parsed releases, retaining duplicate album entries.
        saved: Live saved statuses, including entries outside the catalog.
        liked_tracks: Liked primary-artist track count.
        total_tracks: Total primary-artist track count.

    Returns:
        User-visible promotion reasons in the existing order.
    """
    return qualification_reasons(
        catalog, saved, liked_tracks=liked_tracks, total_tracks=total_tracks
    )


def assess_artist(
    sp: Spotify,
    artist_id: str,
    catalog: tuple[RankedRelease, ...],
    retry_call: RetryCall,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
) -> ArtistAssessment:
    """Evaluate all four promotion criteria against live Spotify state.

    Args:
        sp: Caller-owned synchronous Spotify client.
        artist_id: Primary artist being assessed.
        catalog: Original ranked release observations.
        retry_call: Existing retry and cancellation callback.
        track_cache: Shared run-scoped track observations, updated in place.

    Returns:
        Original live assessment, promotion reasons and marker choices.

    Raises:
        NewKidsError: A catalog or membership response is malformed.
    """
    from spotify_manager.bootstrap.artist_assessment import observe_artist_assessment

    return observe_artist_assessment(sp, artist_id, catalog, retry_call, track_cache)


def _assessment_saved(
    sp: Spotify, release_ids: list[str], retry_call: RetryCall
) -> dict[str, bool]:
    return _batched_contains(
        release_ids, sp.current_user_saved_albums_contains, "Saved Albums", retry_call
    )


def _assessment_liked(
    sp: Spotify, track_ids: list[str], retry_call: RetryCall
) -> dict[str, bool]:
    return _batched_contains(
        track_ids, sp.current_user_saved_tracks_contains, "Liked Songs", retry_call
    )


def _assessment_top_liked(
    sp: Spotify, track_ids: list[str], retry_call: RetryCall
) -> dict[str, bool]:
    return _batched_contains(
        track_ids, sp.current_user_saved_tracks_contains, "top Liked Songs", retry_call
    )


def _playlist_artist_ids(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
) -> tuple[set[str], set[str]]:
    tracks = new_wine.load_playlist_tracks(sp, playlist_id, retry_call)
    return (
        {track.primary_artist_id for track in tracks},
        {track.spotify_id for track in tracks},
    )


def _great_discoveries_playlist(
    sp: Spotify,
    state: dict[str, Any],
    year: int,
    seed_2026_playlist_id: str,
    *,
    dry_run: bool,
    retry_call: RetryCall,
    state_access: RoutineState,
    echo: Echo,
) -> str | None:
    from spotify_manager.bootstrap.new_kids import great_discoveries

    service = great_discoveries(sp, retry_call, state_access, echo)
    return service.resolve(state, year, seed_2026_playlist_id, dry_run)


def _current_user_id(sp: Spotify, retry_call: RetryCall) -> str:
    profile = retry_call(sp.current_user, "loading the current Spotify profile")
    return str(profile.get("id") or "") if isinstance(profile, dict) else ""


def _create_great_playlist(
    sp: Spotify, user_id: str, year: int, retry_call: RetryCall
) -> str:
    created = retry_call(
        partial(
            sp.user_playlist_create,
            user_id,
            f"Great Discoveries {year}",
            public=False,
            description=(
                f"Artists completed through New Kids on the Block during {year}."
            ),
        ),
        f"creating Great Discoveries {year}",
    )
    return str(created.get("id") or "") if isinstance(created, dict) else ""


def _move_queue_entries(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    current: list[new_wine.PlaylistTrack],
    state: dict[str, object],
    *,
    dry_run: bool,
    retry_call: RetryCall,
    log_path: Path,
    echo: Echo,
    queue: list[new_wine.PlaylistTrack] | None = None,
) -> tuple[
    list[new_wine.PlaylistTrack],
    tuple[FillResult, ...],
    list[new_wine.PlaylistTrack],
]:
    from spotify_manager.bootstrap.new_kids import queue_transfer

    service = queue_transfer(
        sp,
        retry_call,
        new_kids_playlist_id,
        queue_2_playlist_id,
        PLAYLIST_CAP,
        dry_run,
        log_path,
        echo,
    )
    return service.move(current, state, queue)


def _append_queue_track(
    sp: Spotify,
    playlist_id: str,
    source: new_wine.PlaylistTrack,
    description: str,
    retry_call: RetryCall,
) -> None:
    retry_call(partial(add_playlist_item, sp, playlist_id, source.uri), description)


def _remove_queue_track(
    sp: Spotify,
    playlist_id: str,
    source: new_wine.PlaylistTrack,
    description: str,
    retry_call: RetryCall,
) -> None:
    retry_call(
        partial(remove_playlist_items, sp, playlist_id, [source.uri]), description
    )


def _logical_artist(
    state: dict[str, object],
    track: new_wine.PlaylistTrack,
) -> tuple[str, str]:
    """Recover a composer's identity from the current works-playlist marker."""
    return discovery_state.logical_artist(state, track)


def _new_run(
    playlist_id: str,
    tracks: list[new_wine.PlaylistTrack],
    state: dict[str, object],
) -> dict[str, object]:
    return discovery_state.new_run(playlist_id, tracks, state, _utc_now)


def next_release_options(
    releases: tuple[RankedRelease, ...],
) -> tuple[RankedRelease, ...]:
    """Return only the highest-priority release tier still available."""
    return discovery_policy.next_release_options(releases)


def _plan_result(
    source: new_wine.PlaylistTrack,
    plan: dict[str, object],
    dry_run: bool,
    *,
    artist_name: str | None = None,
) -> FlushResult:
    return discovery_state.result_from_plan(
        source, plan, dry_run, artist_name=artist_name
    )


def _flush_review_playlist(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    lastfm: scrobble_history.LastFmReader | None = None,
    lastfm_username: str | None = None,
    _playlist_label: str = "New Kids",
    _active_run_key: str = "active_run",
    _blocking_active_run_key: str = "queue_2_active_run",
    _fill_from_queue: bool = True,
    _initial_tracks: list[new_wine.PlaylistTrack] | None = None,
    _live_tracks: list[new_wine.PlaylistTrack] | None = None,
) -> FlushSummary:
    """Advance one playlist snapshot using the shared four-release rules."""
    retry = retry_call or (lambda operation, _description: operation())
    active_year = year or datetime.now().year
    if lastfm is not None:
        if not lastfm_username:
            raise NewKidsConfigError(
                "LASTFM_USERNAME is required to refresh New Kids release progress."
            )
        if progress_callback:
            progress_callback(0, 0, "Refreshing Last.fm release history")
        refresh_scrobbles_for_release_progress(
            lastfm,
            lastfm_username,
            scrobbles_path=scrobbles_path,
            echo=echo,
        )
    if progress_callback:
        progress_callback(0, 0, f"Loading {active_year} Last.fm release history")
    annual_scrobbles = load_annual_scrobble_index(
        scrobbles_path,
        year=active_year,
    )
    state_access = _state_access(state_path, state_service)
    persisted_state = state_access.load()
    state = json.loads(json.dumps(persisted_state)) if dry_run else persisted_state
    try:
        owned_playlists = composer_playlists.load_owned_playlists(
            sp,
            retry,
            frozenset({new_kids_playlist_id, queue_2_playlist_id}),
        )
    except composer_playlists.ComposerPlaylistError as exc:
        raise NewKidsError(str(exc)) from exc
    from spotify_manager.bootstrap.new_kids import review_run

    lifecycle = review_run(
        sp,
        retry,
        state_access,
        state,
        new_kids_playlist_id,
        queue_2_playlist_id,
        _active_run_key,
        _blocking_active_run_key,
        _fill_from_queue,
        dry_run,
        PLAYLIST_CAP,
        log_path,
        echo,
        _utc_now,
    )
    snapshot = lifecycle.prepare(_initial_tracks, _live_tracks)
    catalog_cache: dict[str, tuple[RankedRelease, ...]] = {}
    track_cache: dict[str, tuple[CatalogTrack, ...]] = {}
    composer_track_cache: dict[str, tuple[new_wine.PlaylistTrack, ...]] = {}
    liked_cache: dict[str, bool] = {}

    from spotify_manager.bootstrap.new_kids import review_planner

    planner = review_planner(
        sp,
        retry,
        choice_reader,
        year=active_year,
        dry_run=dry_run,
        history=annual_scrobbles,
        release_limit=RELEASES_PER_ARTIST,
        studio_minimum=MIN_SCROBBLED_TRACKS_PER_RELEASE,
        log_path=log_path,
        echo=echo,
        catalogs=catalog_cache,
        tracks=track_cache,
        liked=liked_cache,
        works=composer_track_cache,
    )

    from spotify_manager.bootstrap.new_kids import review_execution

    execution = review_execution(
        sp,
        retry,
        state_access=state_access,
        state=state,
        live_ids=snapshot.live_ids,
        playlist_id=new_kids_playlist_id,
        label=_playlist_label,
        newfoundland=newfoundland_playlist_id,
        unlucky=unlucky_ones_playlist_id,
        great_seed=great_discoveries_2026_playlist_id,
        year=active_year,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_path=removed_albums_log_path,
        log_path=log_path,
        echo=echo,
        dry_run=dry_run,
        clock=_utc_now,
    )

    from spotify_manager.bootstrap.new_kids import entry_review

    reviewer = entry_review(
        planner,
        execution,
        owned_playlists,
        frozenset({new_kids_playlist_id, queue_2_playlist_id}),
        _utc_now,
        COMPOSER_TRACKS_PER_ARTIST,
        progress_callback,
        echo,
    )
    reviewed, paused = reviewer.review(snapshot.entries, snapshot.run.get("run_id"))
    return lifecycle.finish(snapshot, reviewed, paused)


def flush_new_kids(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    lastfm: scrobble_history.LastFmReader | None = None,
    lastfm_username: str | None = None,
) -> FlushSummary:
    """Advance every snapshotted artist once, then refill New Kids to ten."""
    return _flush_review_playlist(
        sp,
        new_kids_playlist_id,
        queue_2_playlist_id,
        great_discoveries_2026_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
        choice_reader,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_albums_log_path=removed_albums_log_path,
        scrobbles_path=scrobbles_path,
        lastfm=lastfm,
        lastfm_username=lastfm_username,
    )


def flush_queue_2(
    sp: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_2026_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    choice_reader: ReleaseChoiceReader,
    *,
    dry_run: bool = False,
    year: int | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    state_service: StateService | None = None,
    log_path: Path = DEFAULT_QUEUE_2_LOG_PATH,
    albums_path: Path = DEFAULT_ALBUMS_PATH,
    artists_path: Path = DEFAULT_ARTISTS_PATH,
    removed_albums_log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    lastfm: scrobble_history.LastFmReader | None = None,
    lastfm_username: str | None = None,
) -> Queue2Summary:
    """Fill New Kids, then advance the first ten remaining Queue 2 artists."""
    if lastfm is not None:
        if not lastfm_username:
            raise NewKidsConfigError(
                "LASTFM_USERNAME is required to refresh Queue 2 release progress."
            )
        if progress_callback:
            progress_callback(0, 0, "Refreshing Last.fm release history")
        refresh_scrobbles_for_release_progress(
            lastfm,
            lastfm_username,
            scrobbles_path=scrobbles_path,
            echo=echo,
        )
    retry = retry_call or (lambda operation, _description: operation())
    state_access = _state_access(state_path, state_service)
    persisted_state = state_access.load()
    state = json.loads(json.dumps(persisted_state)) if dry_run else persisted_state
    queue_run = state.get("queue_2_active_run")
    resumed = bool(
        not dry_run
        and isinstance(queue_run, dict)
        and queue_run.get("status") in {"active", "refilling"}
        and queue_run.get("playlist_id") == queue_2_playlist_id
    )

    new_kids_tracks = list(
        new_wine.load_playlist_tracks(sp, new_kids_playlist_id, retry)
    )
    new_kids_length_before = len(new_kids_tracks)
    queue_tracks = list(new_wine.load_playlist_tracks(sp, queue_2_playlist_id, retry))
    queue_length_before = len(queue_tracks)
    prefill: tuple[FillResult, ...] = ()

    if resumed:
        remaining = queue_tracks
    else:
        active_new_kids_run = state.get("active_run")
        if (
            not dry_run
            and isinstance(active_new_kids_run, dict)
            and active_new_kids_run.get("status") in {"active", "refilling"}
        ):
            raise NewKidsStateError(
                "The saved New Kids run must be resumed before Queue 2 can start."
            )
        new_kids_tracks, prefill, remaining = _move_queue_entries(
            sp,
            new_kids_playlist_id,
            queue_2_playlist_id,
            new_kids_tracks,
            state,
            dry_run=dry_run,
            retry_call=retry,
            log_path=log_path,
            echo=echo,
            queue=queue_tracks,
        )

    review_entries: list[new_wine.PlaylistTrack] = []
    seen_artist_ids: set[str] = set()
    for source in remaining:
        artist_id, _artist_name = _logical_artist(state, source)
        if artist_id in seen_artist_ids:
            continue
        seen_artist_ids.add(artist_id)
        review_entries.append(source)
        if len(review_entries) >= QUEUE_2_DAILY_LIMIT:
            break

    review = _flush_review_playlist(
        sp,
        queue_2_playlist_id,
        queue_2_playlist_id,
        great_discoveries_2026_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
        choice_reader,
        dry_run=dry_run,
        year=year,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry,
        state_path=state_path,
        state_service=state_service,
        log_path=log_path,
        albums_path=albums_path,
        artists_path=artists_path,
        removed_albums_log_path=removed_albums_log_path,
        scrobbles_path=scrobbles_path,
        _playlist_label="Queue 2",
        _active_run_key="queue_2_active_run",
        _blocking_active_run_key="active_run",
        _fill_from_queue=False,
        _initial_tracks=review_entries,
        _live_tracks=remaining,
    )

    return Queue2Summary(
        results=review.results,
        prefill=prefill,
        queue_length_before=queue_length_before,
        queue_length_after=review.playlist_length_after,
        new_kids_length_before=new_kids_length_before,
        new_kids_length_after=len(new_kids_tracks),
        paused=review.paused,
        resumed=review.resumed,
        dry_run=dry_run,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _checkpoint_review(
    access: RoutineState, state: dict[str, object], dry_run: bool
) -> None:
    if not dry_run:
        access.save(state)


def _append_review_track(
    sp: Spotify,
    playlist_id: str,
    track: CatalogTrack,
    description: str,
    retry_call: RetryCall,
) -> None:
    retry_call(partial(add_playlist_item, sp, playlist_id, track.uri), description)


def _remove_review_track(
    sp: Spotify,
    playlist_id: str,
    source: new_wine.PlaylistTrack,
    label: str,
    retry_call: RetryCall,
) -> None:
    retry_call(
        partial(remove_playlist_items, sp, playlist_id, [source.uri]),
        f"removing previous {label} track {source.name}",
    )


def _artist_followed(
    sp: Spotify, artist_id: str, artist_name: str, retry_call: RetryCall
) -> bool:
    followed = retry_call(
        partial(sp.current_user_following_artists, [artist_id]),
        f"checking follow status for {artist_name}",
    )
    return bool(followed[0]) if isinstance(followed, list) and followed else False


def _unfollow_artist(
    sp: Spotify, artist_id: str, artist_name: str, retry_call: RetryCall
) -> None:
    retry_call(
        partial(remove_library_artists, sp, [f"spotify:artist:{artist_id}"]),
        f"unfollowing {artist_name}",
    )
