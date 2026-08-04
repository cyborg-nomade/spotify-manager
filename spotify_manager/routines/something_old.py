"""Fill the Something Old slot from Last.fm Golden Oldies statistics."""

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import Protocol
from typing import cast

from spotipy import Spotify

# UFI
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_LOG_PATH = FILES_DIR / "something_old_log.jsonl"
MIN_ARTIST_SCROBBLES = 50
TOP_TRACK_LIMIT = 10
ARTIST_SEARCH_LIMIT = 10
SelectionMode = Literal["lastfm_top_tracks", "spotify_top_tracks", "album"]
SummaryAction = Literal["playlist not empty", "cancelled", "would add", "added"]
ProgressCallback = Callable[[str], None]
RetryCall = slow_listening.RetryCall


class SomethingOldError(RuntimeError):
    """Base error for the Something Old routine."""


class SomethingOldConfigError(SomethingOldError):
    """Raised when the destination playlist is not configured."""


class SomethingOldSpotifyError(SomethingOldError):
    """Raised when Spotify data is incomplete or ambiguous."""


class LastFmReader(scrobble_history.LastFmReader, Protocol):
    """Last.fm methods used by the shared history refresh."""


@dataclass(frozen=True)
class LastFmTrackStat:
    """All-time play count for one exact Last.fm track title."""

    track: str
    scrobbles: int
    last_scrobbled_ms: int


@dataclass(frozen=True)
class GoldenOldieArtist:
    """One artist eligible for Last.fm's Golden Oldies ranking."""

    artist: str
    scrobbles: int
    average_scrobble_ms: int
    first_scrobble_ms: int
    last_scrobble_ms: int
    top_tracks: tuple[LastFmTrackStat, ...]


@dataclass(frozen=True)
class SpotifyArtistCandidate:
    """One exact-name Spotify artist search result."""

    spotify_id: str
    name: str
    uri: str
    popularity: int | None
    followers: int | None
    search_rank: int


@dataclass(frozen=True)
class SelectedTrack:
    """One Spotify track selected for the destination playlist."""

    spotify_id: str
    uri: str
    track: str
    album: str
    artists: tuple[str, ...]
    source: str
    lastfm_scrobbles: int | None = None


@dataclass(frozen=True)
class SomethingOldSummary:
    """Completed Something Old decision and optional Spotify mutation."""

    generated_at: datetime
    playlist_id: str
    playlist_length_before: int
    playlist_length_after: int
    dry_run: bool
    action: SummaryAction
    history_refresh: scrobble_history.ScrobbleHistorySummary | None
    ranking_preview: tuple[GoldenOldieArtist, ...]
    artist: GoldenOldieArtist | None
    spotify_artist: SpotifyArtistCandidate | None
    mode: SelectionMode | None
    release: slow_listening.DiscographyRelease | None
    tracks: tuple[SelectedTrack, ...]


ArtistSearchChoiceReader = Callable[
    [str, tuple[SpotifyArtistCandidate, ...]],
    str,
]
ArtistChoiceReader = Callable[
    [GoldenOldieArtist, tuple[SpotifyArtistCandidate, ...]],
    str,
]
ModeReader = Callable[[GoldenOldieArtist, SpotifyArtistCandidate], str]
AlbumChoiceReader = Callable[
    [GoldenOldieArtist, tuple[slow_listening.DiscographyRelease, ...]],
    str,
]


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Something Old, Something New playlist id."""
    try:
        return blast_from_past.parse_playlist_id(
            reference,
            setting_name="SOMETHING_OLD_NEW_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise SomethingOldConfigError(str(exc)) from exc


def rank_golden_oldies(
    history: tuple[blast_from_past.Scrobble, ...],
) -> tuple[GoldenOldieArtist, ...]:
    """Reproduce Last.fm Stats' oldest average artist ranking."""
    timestamps: dict[str, list[int]] = defaultdict(list)
    track_counts: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for scrobble in history:
        artist = scrobble.artist.strip()
        track = scrobble.track.strip()
        if not artist or not track:
            continue
        timestamps[artist].append(scrobble.timestamp_ms)
        track_counts[artist][track].append(scrobble.timestamp_ms)

    ranking: list[GoldenOldieArtist] = []
    for artist, played_at in timestamps.items():
        if len(played_at) < MIN_ARTIST_SCROBBLES:
            continue
        top_tracks = tuple(
            LastFmTrackStat(
                track=track,
                scrobbles=len(track_dates),
                last_scrobbled_ms=max(track_dates),
            )
            for track, track_dates in sorted(
                track_counts[artist].items(),
                key=lambda item: (
                    -len(item[1]),
                    item[0].casefold(),
                ),
            )[:TOP_TRACK_LIMIT]
        )
        ranking.append(
            GoldenOldieArtist(
                artist=artist,
                scrobbles=len(played_at),
                average_scrobble_ms=sum(played_at) // len(played_at),
                first_scrobble_ms=min(played_at),
                last_scrobble_ms=max(played_at),
                top_tracks=top_tracks,
            )
        )
    return tuple(
        sorted(
            ranking,
            key=lambda item: (
                item.average_scrobble_ms,
                item.artist.casefold(),
            ),
        )
    )


def _positive_int(raw: object) -> int | None:
    """Return a non-negative Spotify integer when one is available."""
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return None


def _spotify_artist(raw: object, rank: int) -> SpotifyArtistCandidate | None:
    """Parse one complete Spotify artist search result."""
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not spotify_id or not name or not uri:
        return None
    raw_followers = raw.get("followers")
    followers = (
        _positive_int(raw_followers.get("total"))
        if isinstance(raw_followers, dict)
        else None
    )
    return SpotifyArtistCandidate(
        spotify_id=spotify_id,
        name=name,
        uri=uri,
        popularity=_positive_int(raw.get("popularity")),
        followers=followers,
        search_rank=rank,
    )


def resolve_spotify_artist(
    sp: Spotify,
    artist_name: str,
    artist_choice_reader: ArtistSearchChoiceReader | None,
    retry_call: RetryCall,
) -> SpotifyArtistCandidate | None:
    """Resolve one exact normalized artist, prompting only on ambiguity."""
    response = retry_call(
        partial(
            sp.search,
            q=f'artist:"{artist_name.replace(chr(34), " ")}"',
            type="artist",
            limit=ARTIST_SEARCH_LIMIT,
            offset=0,
        ),
        f"searching Spotify for {artist_name}",
    )
    if not isinstance(response, dict):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid artist search data for {artist_name}."
        )
    page = response.get("artists")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid artist search data for {artist_name}."
        )
    expected = blast_from_past.normalize_name(artist_name)
    candidates = tuple(
        candidate
        for rank, raw in enumerate(page["items"], start=1)
        if (candidate := _spotify_artist(raw, rank)) is not None
        and blast_from_past.normalize_name(candidate.name) == expected
    )
    if not candidates:
        raise SomethingOldSpotifyError(
            f"No exact Spotify artist match was found for {artist_name}."
        )
    if len(candidates) == 1:
        return candidates[0]
    if artist_choice_reader is None:
        raise SomethingOldSpotifyError(
            f"Spotify returned {len(candidates)} exact artists named {artist_name}."
        )
    choice = artist_choice_reader(artist_name, candidates)
    if choice == "quit":
        return None
    selected = next(
        (candidate for candidate in candidates if candidate.spotify_id == choice),
        None,
    )
    if selected is None:
        raise SomethingOldSpotifyError("The selected Spotify artist is invalid.")
    return selected


def _selected_from_match(
    match: blast_from_past.SpotifyTrackMatch,
    *,
    source: str,
    lastfm_scrobbles: int | None = None,
) -> SelectedTrack:
    """Convert a strict Spotify match into one playlist selection."""
    return SelectedTrack(
        spotify_id=match.spotify_id,
        uri=match.uri,
        track=match.track,
        album=match.album,
        artists=match.artists,
        source=source,
        lastfm_scrobbles=lastfm_scrobbles,
    )


def select_lastfm_top_tracks(
    sp: Spotify,
    artist: GoldenOldieArtist,
    retry_call: RetryCall,
) -> tuple[SelectedTrack, ...]:
    """Resolve the artist's ten most-scrobbled titles with strict matching."""
    match_groups: list[tuple[blast_from_past.SpotifyTrackMatch, ...]] = []
    for track in artist.top_tracks:
        matches = retry_call(
            partial(
                blast_from_past.search_spotify_matches,
                sp,
                blast_from_past.Scrobble(
                    track=track.track,
                    artist=artist.artist,
                    album="",
                    timestamp_ms=track.last_scrobbled_ms,
                ),
            ),
            f"matching {artist.artist} - {track.track}",
        )
        if not isinstance(matches, tuple):
            raise SomethingOldSpotifyError(
                f"Spotify returned invalid matches for {artist.artist} - {track.track}."
            )
        match_groups.append(matches)

    raw_liked_ids = retry_call(
        partial(blast_from_past.liked_spotify_track_ids, sp, match_groups),
        f"checking liked Spotify tracks for {artist.artist}",
    )
    if not isinstance(raw_liked_ids, set):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid liked-track data for {artist.artist}."
        )
    liked_ids = cast(set[str], raw_liked_ids)
    selected: list[SelectedTrack] = []
    seen_ids: set[str] = set()
    for track, matches in zip(artist.top_tracks, match_groups, strict=True):
        match = blast_from_past.preferred_spotify_match(matches, liked_ids)
        if match is None or match.spotify_id in seen_ids:
            continue
        seen_ids.add(match.spotify_id)
        selected.append(
            _selected_from_match(
                match,
                source="Last.fm top tracks",
                lastfm_scrobbles=track.scrobbles,
            )
        )
    if not selected:
        raise SomethingOldSpotifyError(
            f"None of {artist.artist}'s top Last.fm tracks matched Spotify safely."
        )
    return tuple(selected)


def _track_artist_data(raw: object) -> tuple[tuple[str, str], ...]:
    """Return ordered Spotify artist ids and names for one track."""
    if not isinstance(raw, list):
        return ()
    return tuple(
        (str(item.get("id") or ""), str(item.get("name") or ""))
        for item in raw
        if isinstance(item, dict) and item.get("id") and item.get("name")
    )


def _spotify_top_track(
    raw: object,
    artist: SpotifyArtistCandidate,
) -> SelectedTrack | None:
    """Parse one Spotify top-track response associated with the artist."""
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    artists = _track_artist_data(raw.get("artists"))
    if (
        not spotify_id
        or not uri
        or not name
        or artist.spotify_id not in {spotify_id for spotify_id, _name in artists}
    ):
        return None
    raw_album = raw.get("album")
    album = (
        str(raw_album.get("name") or "").strip() if isinstance(raw_album, dict) else ""
    )
    return SelectedTrack(
        spotify_id=spotify_id,
        uri=uri,
        track=name,
        album=album,
        artists=tuple(name for _spotify_id, name in artists),
        source="Spotify popular tracks",
    )


def select_spotify_top_tracks(
    sp: Spotify,
    artist: SpotifyArtistCandidate,
    retry_call: RetryCall,
) -> tuple[SelectedTrack, ...]:
    """Return up to ten of Spotify's current top tracks for the artist."""
    response = retry_call(
        partial(sp.artist_top_tracks, artist.spotify_id),
        f"loading Spotify top tracks for {artist.name}",
    )
    raw_tracks = response.get("tracks") if isinstance(response, dict) else None
    if not isinstance(raw_tracks, list):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid top tracks for {artist.name}."
        )
    selected: list[SelectedTrack] = []
    seen_ids: set[str] = set()
    for raw in raw_tracks:
        track = _spotify_top_track(raw, artist)
        if track is None or track.spotify_id in seen_ids:
            continue
        seen_ids.add(track.spotify_id)
        selected.append(track)
        if len(selected) == TOP_TRACK_LIMIT:
            break
    if not selected:
        raise SomethingOldSpotifyError(
            f"Spotify returned no usable top tracks for {artist.name}."
        )
    return tuple(selected)


def select_album_tracks(
    sp: Spotify,
    artist: GoldenOldieArtist,
    spotify_artist: SpotifyArtistCandidate,
    album_choice_reader: AlbumChoiceReader,
    retry_call: RetryCall,
) -> tuple[
    slow_listening.DiscographyRelease | None,
    tuple[SelectedTrack, ...],
]:
    """Prompt for one filtered album/EP and return its complete tracklist."""
    try:
        releases = slow_listening.load_discography(
            sp,
            spotify_artist.spotify_id,
            retry_call,
        )
    except slow_listening.SlowListeningError as exc:
        raise SomethingOldSpotifyError(str(exc)) from exc
    if not releases:
        raise SomethingOldSpotifyError(
            f"No studio albums or EPs were found for {spotify_artist.name}."
        )
    choice = album_choice_reader(artist, releases)
    if choice == "quit":
        return None, ()
    release = next(
        (candidate for candidate in releases if candidate.spotify_id == choice),
        None,
    )
    if release is None:
        raise SomethingOldSpotifyError("The selected album or EP is invalid.")
    try:
        release_tracks = slow_listening.load_release_tracks(sp, release, retry_call)
    except slow_listening.SlowListeningError as exc:
        raise SomethingOldSpotifyError(str(exc)) from exc
    tracks = tuple(
        SelectedTrack(
            spotify_id=track.spotify_id,
            uri=track.uri,
            track=track.name,
            album=release.name,
            artists=(spotify_artist.name,),
            source=f"{release.release_type}: {release.name}",
        )
        for track in release_tracks
    )
    if not tracks:
        raise SomethingOldSpotifyError(f"{release.name} has no playable tracks.")
    return release, tracks


def _direct_retry(operation: Callable[[], object], _description: str) -> object:
    """Call an operation directly when no routine-level retry is supplied."""
    return operation()


def _load_playlist_state(
    sp: Spotify,
    playlist_id: str,
    retry_call: RetryCall,
    description: str,
) -> blast_from_past.PlaylistState:
    """Load the destination through the routine's read-only retry policy."""
    playlist = retry_call(
        partial(blast_from_past.load_playlist_state, sp, playlist_id),
        description,
    )
    if not isinstance(playlist, blast_from_past.PlaylistState):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid playlist data for {playlist_id}."
        )
    return playlist


def _add_tracks(
    sp: Spotify, playlist_id: str, tracks: tuple[SelectedTrack, ...]
) -> None:
    """Append one complete Something Old selection in Spotify-sized batches."""
    uris = [track.uri for track in tracks]
    for start in range(0, len(uris), blast_from_past.SPOTIFY_PLAYLIST_ADD_BATCH_SIZE):
        sp._post(
            f"playlists/{playlist_id}/items",
            payload={
                "uris": uris[
                    start : start + blast_from_past.SPOTIFY_PLAYLIST_ADD_BATCH_SIZE
                ]
            },
        )


def _append_log(summary: SomethingOldSummary, path: Path) -> None:
    """Append the exact successful playlist mutation for later review."""
    record = {
        "generated_at": summary.generated_at.isoformat(),
        "playlist_id": summary.playlist_id,
        "playlist_length_before": summary.playlist_length_before,
        "playlist_length_after": summary.playlist_length_after,
        "action": summary.action,
        "artist": asdict(summary.artist) if summary.artist else None,
        "spotify_artist": (
            asdict(summary.spotify_artist) if summary.spotify_artist else None
        ),
        "mode": summary.mode,
        "release": asdict(summary.release) if summary.release else None,
        "tracks": [asdict(track) for track in summary.tracks],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise SomethingOldError(f"Could not write Something Old log: {path}") from exc


def run_something_old(
    sp: Spotify,
    lastfm: LastFmReader,
    playlist_id: str,
    *,
    expected_username: str | None,
    mode_reader: ModeReader,
    album_choice_reader: AlbumChoiceReader,
    artist_choice_reader: ArtistChoiceReader | None = None,
    dry_run: bool = False,
    export_path: Path = scrobble_history.DEFAULT_SCROBBLES_PATH,
    legacy_delta_path: Path | None = scrobble_history.DEFAULT_LEGACY_DELTA_PATH,
    backup_dir: Path = scrobble_history.DEFAULT_BACKUP_DIR,
    history_log_path: Path = scrobble_history.DEFAULT_LOG_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
) -> SomethingOldSummary:
    """Refresh history and fill an empty Something Old playlist cautiously."""
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    if progress_callback is not None:
        progress_callback("Checking whether Something Old is empty")
    playlist = _load_playlist_state(
        sp,
        playlist_id,
        retry_call,
        "checking whether Something Old is empty",
    )
    if playlist.total_items:
        return SomethingOldSummary(
            generated_at=generated_at,
            playlist_id=playlist_id,
            playlist_length_before=playlist.total_items,
            playlist_length_after=playlist.total_items,
            dry_run=dry_run,
            action="playlist not empty",
            history_refresh=None,
            ranking_preview=(),
            artist=None,
            spotify_artist=None,
            mode=None,
            release=None,
            tracks=(),
        )

    history_refresh = scrobble_history.refresh_scrobble_history(
        lastfm,
        expected_username=expected_username,
        export_path=export_path,
        legacy_delta_path=legacy_delta_path,
        backup_dir=backup_dir,
        log_path=history_log_path,
        dry_run=dry_run,
        now=generated_at,
        progress_callback=progress_callback,
    )
    if progress_callback is not None:
        progress_callback("Calculating Golden Oldies average scrobble dates")
    ranking = rank_golden_oldies(history_refresh.history)
    if not ranking:
        raise SomethingOldError(
            f"No artists have at least {MIN_ARTIST_SCROBBLES} scrobbles."
        )
    artist = ranking[0]

    def select_spotify_artist_candidate(
        _artist_name: str,
        candidates: tuple[SpotifyArtistCandidate, ...],
    ) -> str:
        if artist_choice_reader is None:
            raise SomethingOldError("No Spotify artist choice reader is available.")
        return artist_choice_reader(artist, candidates)

    search_choice_reader = (
        select_spotify_artist_candidate if artist_choice_reader is not None else None
    )
    spotify_artist = resolve_spotify_artist(
        sp,
        artist.artist,
        search_choice_reader,
        retry_call,
    )
    if spotify_artist is None:
        return SomethingOldSummary(
            generated_at=generated_at,
            playlist_id=playlist_id,
            playlist_length_before=0,
            playlist_length_after=0,
            dry_run=dry_run,
            action="cancelled",
            history_refresh=history_refresh,
            ranking_preview=ranking[:10],
            artist=artist,
            spotify_artist=None,
            mode=None,
            release=None,
            tracks=(),
        )

    raw_mode = mode_reader(artist, spotify_artist)
    if raw_mode == "quit":
        return SomethingOldSummary(
            generated_at=generated_at,
            playlist_id=playlist_id,
            playlist_length_before=0,
            playlist_length_after=0,
            dry_run=dry_run,
            action="cancelled",
            history_refresh=history_refresh,
            ranking_preview=ranking[:10],
            artist=artist,
            spotify_artist=spotify_artist,
            mode=None,
            release=None,
            tracks=(),
        )
    if raw_mode not in {"lastfm_top_tracks", "spotify_top_tracks", "album"}:
        raise SomethingOldError("The Something Old selection mode is invalid.")
    mode = cast(SelectionMode, raw_mode)

    release: slow_listening.DiscographyRelease | None = None
    if progress_callback is not None:
        progress_callback(f"Preparing {artist.artist}'s {mode.replace('_', ' ')}")
    if mode == "lastfm_top_tracks":
        tracks = select_lastfm_top_tracks(sp, artist, retry_call)
    elif mode == "spotify_top_tracks":
        tracks = select_spotify_top_tracks(sp, spotify_artist, retry_call)
    else:
        release, tracks = select_album_tracks(
            sp,
            artist,
            spotify_artist,
            album_choice_reader,
            retry_call,
        )
        if release is None:
            return SomethingOldSummary(
                generated_at=generated_at,
                playlist_id=playlist_id,
                playlist_length_before=0,
                playlist_length_after=0,
                dry_run=dry_run,
                action="cancelled",
                history_refresh=history_refresh,
                ranking_preview=ranking[:10],
                artist=artist,
                spotify_artist=spotify_artist,
                mode=mode,
                release=None,
                tracks=(),
            )

    action: SummaryAction = "would add" if dry_run else "added"
    if not dry_run:
        if progress_callback is not None:
            progress_callback("Rechecking the empty playlist before adding")
        current_playlist = _load_playlist_state(
            sp,
            playlist_id,
            retry_call,
            "rechecking Something Old before adding",
        )
        if current_playlist.total_items:
            raise SomethingOldError(
                "Something Old changed while the selection was being prepared; "
                "nothing was added."
            )
        _add_tracks(sp, playlist_id, tracks)

    summary = SomethingOldSummary(
        generated_at=generated_at,
        playlist_id=playlist_id,
        playlist_length_before=0,
        playlist_length_after=0 if dry_run else len(tracks),
        dry_run=dry_run,
        action=action,
        history_refresh=history_refresh,
        ranking_preview=ranking[:10],
        artist=artist,
        spotify_artist=spotify_artist,
        mode=mode,
        release=release,
        tracks=tracks,
    )
    if not dry_run:
        _append_log(summary, log_path)
    return summary
