"""Rebuild Last.fm-style album recommendations for Sauvignon Terre-Neuve."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import Protocol

from spotipy import Spotify

# UFI
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines.slow_listening import release_identity


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_LOG_PATH = FILES_DIR / "sauvignon_recommendation_log.jsonl"
DEFAULT_CACHE_PATH = found_art.DEFAULT_CACHE_PATH
DEFAULT_SCROBBLES_PATH = found_art.DEFAULT_SCROBBLES_PATH
DEFAULT_RECENT_PATH = found_art.DEFAULT_RECENT_PATH
DEFAULT_MAX_PLAYLIST_LENGTH = 20
DEFAULT_SEED_COUNT = found_art.DEFAULT_SEED_COUNT
SPOTIFY_CANDIDATE_MULTIPLIER = 5
MIN_SPOTIFY_CANDIDATES = 50
CHOICE_SKIP = "__skip__"
CHOICE_QUIT = "__quit__"

AlbumKey = tuple[str, str]
Echo = Callable[[str], None]
ProgressCallback = Callable[[str], None]
RetryCall = Callable[[Callable[[], object], str], object]
AlbumChoiceReader = Callable[
    ["AlbumRecommendation", tuple["SpotifyAlbumOption", ...]], str
]


class SauvignonError(RuntimeError):
    """Base error for the Sauvignon recommendation routine."""


class SauvignonConfigError(SauvignonError):
    """Raised when a required setting or numeric option is invalid."""


class SauvignonStateError(SauvignonError):
    """Raised when durable audit data cannot be read or written safely."""


class SauvignonSpotifyError(SauvignonError):
    """Raised when Spotify returns incomplete recommendation data."""


class LastFmReader(found_art.LastFmReader, Protocol):
    """Last.fm methods required through the shared Found Art machinery."""


@dataclass(frozen=True)
class SpotifyAlbumOption:
    """One eligible Spotify album edition reached through a similar track."""

    spotify_id: str
    uri: str
    artist_id: str
    artist: str
    album: str
    release_type: str
    release_date: str
    total_tracks: int
    source_track: str
    source_track_id: str
    search_rank: int
    track_similarity: float
    track_popularity: int | None


@dataclass(frozen=True)
class AlbumRecommendation:
    """One album-level score aggregated from recommended tracks."""

    artist: str
    album: str
    key: AlbumKey
    score: float
    best_match: float
    supporting_tracks: tuple[str, ...]
    options: tuple[SpotifyAlbumOption, ...]
    base_rank: int = 0
    weekly_rank: float = 1.0


@dataclass(frozen=True)
class FirstTrack:
    """The first playable track in Spotify's stored album order."""

    spotify_id: str
    uri: str
    name: str


SauvignonAction = Literal[
    "added",
    "would add",
    "already represented",
    "artist already selected",
    "skipped",
    "quit",
]


@dataclass(frozen=True)
class SauvignonResult:
    """One ranked recommendation and its final playlist action."""

    recommendation: AlbumRecommendation
    album: SpotifyAlbumOption | None
    first_track: FirstTrack | None
    action: SauvignonAction


@dataclass(frozen=True)
class SauvignonSummary:
    """Outcome of one Last.fm-driven Sauvignon fill."""

    generated_at: datetime
    week_start: date
    playlist_id: str
    requested_count: int
    history_albums: int
    history_scrobbles: int
    live_scrobbles_added: int
    seed_count: int
    track_candidate_count: int
    album_candidate_count: int
    playlist_length_before: int
    playlist_length_after: int
    paused: bool
    dry_run: bool
    results: tuple[SauvignonResult, ...]

    @property
    def selected(self) -> int:
        """Return proposed or completed additions."""
        return sum(result.action in {"added", "would add"} for result in self.results)


@dataclass
class _AlbumAccumulator:
    """Mutable album score while recommended tracks are grouped."""

    artist: str
    album: str
    key: AlbumKey
    score: float = 0.0
    best_match: float = 0.0
    supporting_tracks: set[str] | None = None
    options: dict[str, SpotifyAlbumOption] | None = None

    def __post_init__(self) -> None:
        if self.supporting_tracks is None:
            self.supporting_tracks = set()
        if self.options is None:
            self.options = {}


def parse_playlist_id(reference: str | None) -> str:
    """Parse the configured Sauvignon destination playlist."""
    try:
        return new_wine.parse_playlist_id(
            reference,
            "SAUVIGNON_TERRE_NEUVE_PLAYLIST",
        )
    except new_wine.NewWineConfigError as exc:
        raise SauvignonConfigError(str(exc)) from exc


def canonical_album_key(artist: str, album: str) -> AlbumKey:
    """Return an edition-tolerant artist and album identity."""
    return (
        blast_from_past.normalize_name(artist),
        release_identity(album),
    )


def heard_album_keys(
    scrobbles: list[blast_from_past.Scrobble],
) -> set[AlbumKey]:
    """Return every non-empty album identity present in Last.fm history."""
    return {
        key
        for scrobble in scrobbles
        if scrobble.album
        and all(key := canonical_album_key(scrobble.artist, scrobble.album))
    }


def previously_added_album_keys(path: Path = DEFAULT_LOG_PATH) -> set[AlbumKey]:
    """Return albums actually added by earlier Sauvignon recommendation runs."""
    if not path.exists():
        return set()
    keys: set[AlbumKey] = set()
    current_line = 0
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                current_line = line_number
                if not line.strip():
                    continue
                record = json.loads(line)
                raw_results = (
                    record.get("results") if isinstance(record, dict) else None
                )
                if not isinstance(raw_results, list):
                    raise ValueError("results must be a list")
                for result in raw_results:
                    if not isinstance(result, dict) or result.get("action") != "added":
                        continue
                    raw_album = result.get("album")
                    if not isinstance(raw_album, dict):
                        raise ValueError("album must be an object")
                    keys.add(
                        canonical_album_key(
                            str(raw_album["artist"]),
                            str(raw_album["album"]),
                        )
                    )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        detail = f" at line {current_line}" if current_line else ""
        raise SauvignonStateError(
            f"Sauvignon audit log is invalid{detail}: {path}"
        ) from exc
    return keys


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    pairs: list[tuple[str, str]] = []
    for value in raw:
        if not isinstance(value, dict):
            continue
        spotify_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or spotify_id).strip()
        if spotify_id and name:
            pairs.append((spotify_id, name))
    return tuple(pairs)


def _positive_int(raw: object) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0


def _album_option(
    raw_track: object,
    candidate: found_art.FoundArtCandidate,
    search_rank: int,
) -> SpotifyAlbumOption | None:
    """Parse one exact-primary-artist studio album or EP search result."""
    match = blast_from_past.matching_spotify_track(
        blast_from_past.Scrobble(
            artist=candidate.artist,
            track=candidate.track,
            album="",
            timestamp_ms=0,
        ),
        raw_track,
        search_rank,
    )
    if match is None or not isinstance(raw_track, dict):
        return None
    expected_artist = blast_from_past.normalize_name(candidate.artist)
    track_artists = _artist_pairs(raw_track.get("artists"))
    raw_album = raw_track.get("album")
    if not track_artists or not isinstance(raw_album, dict):
        return None
    album_artists = _artist_pairs(raw_album.get("artists"))
    if (
        blast_from_past.normalize_name(track_artists[0][1]) != expected_artist
        or not album_artists
        or blast_from_past.normalize_name(album_artists[0][1]) != expected_artist
    ):
        return None

    spotify_id = str(raw_album.get("id") or "").strip()
    uri = str(raw_album.get("uri") or "").strip()
    album_name = str(raw_album.get("name") or "").strip()
    total_tracks = _positive_int(raw_album.get("total_tracks"))
    if not spotify_id or not uri or not album_name:
        return None
    release_type, tier = new_kids._release_type(
        raw_album.get("album_type"),
        total_tracks,
        album_name,
    )
    if tier != 0 or new_kids.DECORATED_PATTERN.search(album_name):
        return None
    return SpotifyAlbumOption(
        spotify_id=spotify_id,
        uri=uri,
        artist_id=album_artists[0][0],
        artist=album_artists[0][1],
        album=album_name,
        release_type=release_type,
        release_date=str(raw_album.get("release_date") or "Unknown"),
        total_tracks=total_tracks,
        source_track=match.track,
        source_track_id=match.spotify_id,
        search_rank=search_rank,
        track_similarity=match.track_similarity,
        track_popularity=match.popularity,
    )


def search_candidate_albums(
    spotify: Spotify,
    candidate: found_art.FoundArtCandidate,
    retry_call: RetryCall,
) -> tuple[SpotifyAlbumOption, ...]:
    """Resolve one Last.fm track candidate to eligible Spotify releases."""
    scrobble = blast_from_past.Scrobble(
        artist=candidate.artist,
        track=candidate.track,
        album="",
        timestamp_ms=0,
    )
    response = retry_call(
        partial(
            spotify.search,
            q=blast_from_past.spotify_search_query(scrobble),
            type="track",
            limit=blast_from_past.SPOTIFY_SEARCH_LIMIT,
            offset=0,
        ),
        f"searching Spotify for {candidate.artist} - {candidate.track}",
    )
    page = response.get("tracks") if isinstance(response, dict) else None
    raw_items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(raw_items, list):
        raise SauvignonSpotifyError(
            f"Spotify returned invalid search data for {candidate.artist} - "
            f"{candidate.track}."
        )
    options: dict[str, SpotifyAlbumOption] = {}
    for rank, raw_track in enumerate(raw_items, start=1):
        option = _album_option(raw_track, candidate, rank)
        if option is None:
            continue
        previous = options.get(option.spotify_id)
        if previous is None or _option_rank(option) > _option_rank(previous):
            options[option.spotify_id] = option
    return tuple(sorted(options.values(), key=_option_sort_key))


def _option_rank(option: SpotifyAlbumOption) -> tuple[float, int, int]:
    return (
        option.track_similarity,
        option.track_popularity if option.track_popularity is not None else -1,
        -option.search_rank,
    )


def _option_sort_key(option: SpotifyAlbumOption) -> tuple[float, int, int, str]:
    rank = _option_rank(option)
    return (-rank[0], -rank[1], -rank[2], option.spotify_id)


def gather_album_recommendations(
    spotify: Spotify,
    candidates: tuple[found_art.FoundArtCandidate, ...],
    excluded_keys: set[AlbumKey],
    existing_album_ids: set[str],
    *,
    maximum_candidates: int,
    week_start: date,
    retry_call: RetryCall,
    progress_callback: ProgressCallback | None = None,
) -> tuple[AlbumRecommendation, ...]:
    """Resolve recommended tracks and aggregate their eligible Spotify albums."""
    accumulators: dict[AlbumKey, _AlbumAccumulator] = {}
    considered = candidates[:maximum_candidates]
    for index, candidate in enumerate(considered, start=1):
        if progress_callback is not None:
            progress_callback(
                f"Resolving album evidence {index}/{len(considered)}: "
                f"{candidate.artist} - {candidate.track}"
            )
        options = search_candidate_albums(spotify, candidate, retry_call)
        grouped: dict[AlbumKey, list[SpotifyAlbumOption]] = {}
        for option in options:
            key = canonical_album_key(option.artist, option.album)
            if key in excluded_keys or option.spotify_id in existing_album_ids:
                continue
            grouped.setdefault(key, []).append(option)
        for key, group in grouped.items():
            best = max(group, key=_option_rank)
            accumulator = accumulators.setdefault(
                key,
                _AlbumAccumulator(
                    artist=best.artist,
                    album=best.album,
                    key=key,
                ),
            )
            accumulator.score += candidate.score * best.track_similarity
            accumulator.best_match = max(
                accumulator.best_match,
                candidate.best_match,
            )
            assert accumulator.supporting_tracks is not None
            assert accumulator.options is not None
            accumulator.supporting_tracks.add(f"{candidate.artist} - {candidate.track}")
            for option in group:
                previous = accumulator.options.get(option.spotify_id)
                if previous is None or _option_rank(option) > _option_rank(previous):
                    accumulator.options[option.spotify_id] = option

    base_ranked = sorted(
        (
            AlbumRecommendation(
                artist=value.artist,
                album=value.album,
                key=value.key,
                score=value.score
                * (1 + 0.15 * (len(value.supporting_tracks or ()) - 1)),
                best_match=value.best_match,
                supporting_tracks=tuple(sorted(value.supporting_tracks or ())),
                options=tuple(
                    sorted((value.options or {}).values(), key=_option_sort_key)
                ),
            )
            for value in accumulators.values()
        ),
        key=lambda item: (
            -item.score,
            -len(item.supporting_tracks),
            -item.best_match,
            item.key,
        ),
    )
    rotated = tuple(
        replace(
            recommendation,
            base_rank=rank,
            weekly_rank=found_art.weekly_weighted_rank(
                week_start,
                "sauvignon-album",
                recommendation.key,
                recommendation.score**2,
            ),
        )
        for rank, recommendation in enumerate(base_ranked, start=1)
    )
    return tuple(
        sorted(
            rotated,
            key=lambda item: (-item.weekly_rank, item.base_rank, item.key),
        )
    )


def _genuinely_ambiguous(options: tuple[SpotifyAlbumOption, ...]) -> bool:
    """Return whether editions differ in visible release metadata."""
    signatures = {
        (
            blast_from_past.normalize_name(option.album),
            option.release_date,
            option.total_tracks,
            option.release_type,
        )
        for option in options
    }
    return len(signatures) > 1


def choose_album_option(
    recommendation: AlbumRecommendation,
    choice_reader: AlbumChoiceReader | None,
) -> SpotifyAlbumOption | Literal["skip", "quit"]:
    """Choose automatically unless multiple materially different editions exist."""
    if not recommendation.options:
        return "skip"
    if not _genuinely_ambiguous(recommendation.options):
        return recommendation.options[0]
    if choice_reader is None:
        return "skip"
    choice = choice_reader(recommendation, recommendation.options)
    if choice == CHOICE_SKIP:
        return "skip"
    if choice == CHOICE_QUIT:
        return "quit"
    return next(
        (option for option in recommendation.options if option.spotify_id == choice),
        "skip",
    )


def load_first_track(
    spotify: Spotify,
    album: SpotifyAlbumOption,
    retry_call: RetryCall,
) -> FirstTrack:
    """Load the first playable track without reordering Spotify's response."""
    response = retry_call(
        partial(spotify.album_tracks, album.spotify_id, limit=50, offset=0),
        f"loading the first track of {album.artist} - {album.album}",
    )
    raw_items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(raw_items, list):
        raise SauvignonSpotifyError(
            f"Spotify returned invalid tracks for {album.artist} - {album.album}."
        )
    for raw_track in raw_items:
        if not isinstance(raw_track, dict):
            continue
        spotify_id = str(raw_track.get("id") or "").strip()
        uri = str(raw_track.get("uri") or "").strip()
        name = str(raw_track.get("name") or "").strip()
        if spotify_id and uri and name:
            return FirstTrack(spotify_id=spotify_id, uri=uri, name=name)
    raise SauvignonSpotifyError(
        f"No playable first track found for {album.artist} - {album.album}."
    )


def _result_record(result: SauvignonResult) -> dict[str, object]:
    recommendation = result.recommendation
    return {
        "recommendation": {
            "artist": recommendation.artist,
            "album": recommendation.album,
            "score": recommendation.score,
            "best_match": recommendation.best_match,
            "supporting_tracks": list(recommendation.supporting_tracks),
            "base_rank": recommendation.base_rank,
            "weekly_rank": recommendation.weekly_rank,
        },
        "album": asdict(result.album) if result.album is not None else None,
        "first_track": (
            asdict(result.first_track) if result.first_track is not None else None
        ),
        "action": result.action,
    }


def append_log(summary: SauvignonSummary, path: Path = DEFAULT_LOG_PATH) -> None:
    """Append one complete recommendation run to the audit log."""
    record = {
        "generated_at": summary.generated_at.isoformat(),
        "week_start": summary.week_start.isoformat(),
        "playlist_id": summary.playlist_id,
        "requested_count": summary.requested_count,
        "history_albums": summary.history_albums,
        "history_scrobbles": summary.history_scrobbles,
        "live_scrobbles_added": summary.live_scrobbles_added,
        "seed_count": summary.seed_count,
        "track_candidate_count": summary.track_candidate_count,
        "album_candidate_count": summary.album_candidate_count,
        "playlist_length_before": summary.playlist_length_before,
        "playlist_length_after": summary.playlist_length_after,
        "paused": summary.paused,
        "dry_run": summary.dry_run,
        "results": [_result_record(result) for result in summary.results],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise SauvignonStateError(f"Could not write Sauvignon log: {path}") from exc


def fill_sauvignon_from_lastfm(
    spotify: Spotify,
    lastfm: LastFmReader,
    playlist_id: str,
    choice_reader: AlbumChoiceReader | None,
    *,
    count: int | None = None,
    max_playlist_length: int | None = DEFAULT_MAX_PLAYLIST_LENGTH,
    seed_count: int = DEFAULT_SEED_COUNT,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    recent_path: Path = DEFAULT_RECENT_PATH,
    cache_path: Path = DEFAULT_CACHE_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> SauvignonSummary:
    """Fill Sauvignon with album-level recommendations inferred from Last.fm."""
    if count is not None and max_playlist_length is not None:
        raise SauvignonConfigError(
            "Use either count or maximum playlist length, not both."
        )
    if count is not None and count < 1:
        raise SauvignonConfigError("Count must be at least 1.")
    if max_playlist_length is not None and max_playlist_length < 1:
        raise SauvignonConfigError("Maximum playlist length must be at least 1.")
    if seed_count < 1:
        raise SauvignonConfigError("Seed count must be at least 1.")

    retry = retry_call or (lambda operation, _description: operation())
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    week_start = found_art.listening_week_start(generated_at)
    history, live_added = found_art.refresh_scrobble_history(
        lastfm,
        export_path=export_path,
        recent_path=recent_path,
        dry_run=dry_run,
        now=generated_at,
        progress_callback=progress_callback,
    )
    if progress_callback is not None:
        progress_callback("Loading Sauvignon Terre-Neuve")
    try:
        playlist = new_wine.load_playlist_tracks(spotify, playlist_id, retry)
    except new_wine.NewWineError as exc:
        raise SauvignonSpotifyError(str(exc)) from exc
    before = len(playlist)
    requested = (
        count
        if count is not None
        else max(
            0,
            (max_playlist_length or DEFAULT_MAX_PLAYLIST_LENGTH) - before,
        )
    )

    seeds: tuple[found_art.FoundArtSeed, ...] = ()
    track_candidates: tuple[found_art.FoundArtCandidate, ...] = ()
    album_candidates: tuple[AlbumRecommendation, ...] = ()
    results: list[SauvignonResult] = []
    pending: list[tuple[SpotifyAlbumOption, FirstTrack]] = []
    paused = False
    history_keys = heard_album_keys(history)
    if requested:
        track_history = found_art.aggregate_track_history(history)
        seeds = found_art.select_seed_tracks(
            track_history,
            seed_count=seed_count,
            week_start=week_start,
        )
        track_candidates = found_art.gather_candidates(
            lastfm,
            seeds,
            {track.key for track in track_history},
            cache_path=cache_path,
            log_path=None,
            week_start=week_start,
            candidate_pool_size=max(
                found_art.MIN_WEEKLY_CANDIDATE_POOL,
                requested * found_art.WEEKLY_CANDIDATE_POOL_MULTIPLIER,
            ),
            now=generated_at,
            progress_callback=progress_callback,
        )
        existing_ids = {track.release.spotify_id for track in playlist}
        existing_keys = {
            canonical_album_key(track.primary_artist_name, track.release.name)
            for track in playlist
        }
        excluded = history_keys | existing_keys | previously_added_album_keys(log_path)
        album_candidates = gather_album_recommendations(
            spotify,
            track_candidates,
            excluded,
            existing_ids,
            maximum_candidates=min(
                len(track_candidates),
                max(MIN_SPOTIFY_CANDIDATES, requested * SPOTIFY_CANDIDATE_MULTIPLIER),
            ),
            week_start=week_start,
            retry_call=retry,
            progress_callback=progress_callback,
        )

        selected_artists: set[str] = set()
        selected_album_ids: set[str] = set()
        for recommendation in album_candidates:
            if len(pending) >= requested:
                break
            artist_key = recommendation.key[0]
            if artist_key in selected_artists:
                results.append(
                    SauvignonResult(
                        recommendation,
                        None,
                        None,
                        "artist already selected",
                    )
                )
                continue
            choice = choose_album_option(recommendation, choice_reader)
            if choice == "quit":
                results.append(SauvignonResult(recommendation, None, None, "quit"))
                paused = True
                break
            if choice == "skip":
                results.append(SauvignonResult(recommendation, None, None, "skipped"))
                continue
            if choice.spotify_id in selected_album_ids:
                results.append(
                    SauvignonResult(
                        recommendation,
                        choice,
                        None,
                        "already represented",
                    )
                )
                continue
            first_track = load_first_track(spotify, choice, retry)
            action: SauvignonAction = "would add" if dry_run else "added"
            results.append(SauvignonResult(recommendation, choice, first_track, action))
            pending.append((choice, first_track))
            selected_artists.add(artist_key)
            selected_album_ids.add(choice.spotify_id)

    actual_additions = 0
    if pending and not dry_run:
        if progress_callback is not None:
            progress_callback("Rechecking Sauvignon before adding albums")
        try:
            current = new_wine.load_playlist_tracks(spotify, playlist_id, retry)
        except new_wine.NewWineError as exc:
            raise SauvignonSpotifyError(str(exc)) from exc
        current_album_ids = {track.release.spotify_id for track in current}
        current_track_ids = {track.spotify_id for track in current}
        additions = [
            (album, track)
            for album, track in pending
            if album.spotify_id not in current_album_ids
            and track.spotify_id not in current_track_ids
        ]
        if additions:
            retry(
                lambda: spotify._post(
                    f"playlists/{playlist_id}/items",
                    payload={"uris": [track.uri for _album, track in additions]},
                ),
                f"adding {len(additions)} albums to Sauvignon Terre-Neuve",
            )
            actual_additions = len(additions)
            echo(f"Added {actual_additions} albums to Sauvignon Terre-Neuve.")
        added_ids = {album.spotify_id for album, _track in additions}
        results = [
            (
                replace(result, action="already represented")
                if result.action == "added"
                and result.album is not None
                and result.album.spotify_id not in added_ids
                else result
            )
            for result in results
        ]

    summary = SauvignonSummary(
        generated_at=generated_at,
        week_start=week_start,
        playlist_id=playlist_id,
        requested_count=requested,
        history_albums=len(history_keys),
        history_scrobbles=len(history),
        live_scrobbles_added=live_added,
        seed_count=len(seeds),
        track_candidate_count=len(track_candidates),
        album_candidate_count=len(album_candidates),
        playlist_length_before=before,
        playlist_length_after=before + actual_additions,
        paused=paused,
        dry_run=dry_run,
        results=tuple(results),
    )
    append_log(summary, log_path)
    return summary
