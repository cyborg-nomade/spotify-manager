"""Fill the Something Old slot from Last.fm Golden Oldies statistics."""

from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Protocol
from typing import cast

from spotipy import Spotify

from spotify_manager.application import golden_selection as selections
from spotify_manager.application.something_old_values import (
    SomethingOldConfigError as SomethingOldConfigError,
)

# UFI
from spotify_manager.application.something_old_values import (
    SomethingOldError as SomethingOldError,
)
from spotify_manager.application.something_old_values import (
    SomethingOldSpotifyError as SomethingOldSpotifyError,
)
from spotify_manager.application.something_old_values import (
    SomethingOldSummary as SomethingOldSummary,
)
from spotify_manager.application.something_old_values import (
    SummaryAction as SummaryAction,
)
from spotify_manager.domain import golden_markers
from spotify_manager.domain.golden_oldies import GoldenOldieArtist as GoldenOldieArtist
from spotify_manager.domain.golden_oldies import LastFmTrackStat as LastFmTrackStat
from spotify_manager.domain.golden_selection import SelectedTrack as SelectedTrack
from spotify_manager.domain.golden_selection import SelectionMode as SelectionMode
from spotify_manager.domain.golden_selection import (
    SpotifyArtistCandidate as SpotifyArtistCandidate,
)
from spotify_manager.infrastructure import golden_records
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_LOG_PATH = FILES_DIR / "something_old_log.jsonl"
MIN_ARTIST_SCROBBLES = 50
TOP_TRACK_LIMIT = 10
ARTIST_SEARCH_LIMIT = 10
ProgressCallback = Callable[[str], None]
RetryCall = slow_listening.RetryCall


class LastFmReader(scrobble_history.LastFmReader, Protocol):
    """Last.fm methods used by the shared history refresh."""


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
    """Extract the configured Something Old, Something New playlist id.

    Args:
        reference: Original configured identity, URI or playlist URL.

    Returns:
        Original parsed playlist identity.

    Raises:
        SomethingOldConfigError: The original reference is missing or invalid.
    """
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
    """Reproduce Last.fm Stats' oldest average artist ranking.

    Args:
        history: Original complete ordered history.

    Returns:
        Eligible exact-label artists in original oldest-average order.
    """
    from spotify_manager.domain.golden_oldies import rank_golden_oldies as rank_history

    return rank_history(history, MIN_ARTIST_SCROBBLES, TOP_TRACK_LIMIT)


def _positive_int(raw: object) -> int | None:
    return golden_records.positive_int(raw)


def _spotify_artist(raw: object, rank: int) -> SpotifyArtistCandidate | None:
    return golden_records.artist_record(raw, rank)


def resolve_spotify_artist(
    sp: Spotify,
    artist_name: str,
    artist_choice_reader: ArtistSearchChoiceReader | None,
    retry_call: RetryCall,
) -> SpotifyArtistCandidate | None:
    """Resolve one exact normalized artist, prompting only on ambiguity.

    Args:
        sp: Caller-owned Spotify client.
        artist_name: Original expected artist spelling.
        artist_choice_reader: Optional original ambiguity interaction.
        retry_call: Original read retry boundary.

    Returns:
        Original accepted mapping or cancellation.

    Raises:
        SomethingOldSpotifyError: Original search or ambiguity choice is unusable.
    """
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
    return selections.resolve_artist(
        artist_name,
        golden_records.artist_search(response, artist_name),
        artist_choice_reader,
    )


def _selected_from_match(
    match: blast_from_past.SpotifyTrackMatch,
    *,
    source: str,
    lastfm_scrobbles: int | None = None,
) -> SelectedTrack:
    return golden_markers.from_match(match, source, lastfm_scrobbles)


def select_lastfm_top_tracks(
    sp: Spotify,
    artist: GoldenOldieArtist,
    retry_call: RetryCall,
) -> tuple[SelectedTrack, ...]:
    """Resolve the artist's ranked titles before one live liked-membership read.

    Args:
        sp: Caller-owned Spotify client.
        artist: Selected history artist and original ranked titles.
        retry_call: Caller-owned read retry policy.

    Returns:
        Original ordered safe distinct markers.

    Raises:
        SomethingOldSpotifyError: Original catalog data or selection is unusable.
    """
    return selections.select_lastfm(
        artist,
        partial(_read_lastfm_matches, sp, artist, retry_call),
        partial(_read_lastfm_liked, sp, artist, retry_call),
        blast_from_past.ALBUM_MATCH_THRESHOLD,
    )


def _read_lastfm_matches(
    sp: Spotify,
    artist: GoldenOldieArtist,
    retry_call: RetryCall,
    track: LastFmTrackStat,
) -> tuple[blast_from_past.SpotifyTrackMatch, ...]:
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
    return matches


def _read_lastfm_liked(
    sp: Spotify,
    artist: GoldenOldieArtist,
    retry_call: RetryCall,
    groups: list[tuple[blast_from_past.SpotifyTrackMatch, ...]],
) -> set[str]:
    raw = retry_call(
        partial(blast_from_past.liked_spotify_track_ids, sp, groups),
        f"checking liked Spotify tracks for {artist.artist}",
    )
    if not isinstance(raw, set):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid liked-track data for {artist.artist}."
        )
    return cast(set[str], raw)


def _track_artist_data(raw: object) -> tuple[tuple[str, str], ...]:
    return golden_records.track_artist_data(raw)


def _spotify_top_track(
    raw: object, artist: SpotifyArtistCandidate
) -> SelectedTrack | None:
    return golden_records.popular_track(raw, artist)


def select_spotify_top_tracks(
    sp: Spotify,
    artist: SpotifyArtistCandidate,
    retry_call: RetryCall,
) -> tuple[SelectedTrack, ...]:
    """Return up to ten of Spotify's current top tracks for the artist.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original accepted artist mapping.
        retry_call: Original read retry boundary.

    Returns:
        Original capped distinct popular markers in response order.

    Raises:
        SomethingOldSpotifyError: Original top-track data is unusable.
    """
    response = retry_call(
        partial(sp.artist_top_tracks, artist.spotify_id),
        f"loading Spotify top tracks for {artist.name}",
    )
    return selections.select_popular(
        artist, golden_records.popular_tracks(response, artist), TOP_TRACK_LIMIT
    )


def select_album_tracks(
    sp: Spotify,
    artist: GoldenOldieArtist,
    spotify_artist: SpotifyArtistCandidate,
    album_choice_reader: AlbumChoiceReader,
    retry_call: RetryCall,
) -> tuple[slow_listening.DiscographyRelease | None, tuple[SelectedTrack, ...]]:
    """Request one studio release before reading its complete ordered tracklist.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original selected history artist.
        spotify_artist: Original accepted mapping.
        album_choice_reader: Caller-owned release interaction.
        retry_call: Original read retry policy.

    Returns:
        Original release and full track selection or cancellation.

    Raises:
        SomethingOldSpotifyError: Original catalog or release choice is unusable.
    """
    releases = _read_studio_releases(sp, spotify_artist, retry_call)
    return selections.select_album(
        artist,
        spotify_artist,
        releases,
        album_choice_reader,
        partial(_read_studio_tracks, sp, retry_call),
    )


def _read_studio_releases(
    sp: Spotify,
    artist: SpotifyArtistCandidate,
    retry_call: RetryCall,
) -> tuple[slow_listening.DiscographyRelease, ...]:
    try:
        return slow_listening.load_discography(sp, artist.spotify_id, retry_call)
    except slow_listening.SlowListeningError as exc:
        raise SomethingOldSpotifyError(str(exc)) from exc


def _read_studio_tracks(
    sp: Spotify,
    retry_call: RetryCall,
    release: slow_listening.DiscographyRelease,
) -> tuple[slow_listening.new_wine.ReleaseTrack, ...]:
    try:
        return slow_listening.load_release_tracks(sp, release, retry_call)
    except slow_listening.SlowListeningError as exc:
        raise SomethingOldSpotifyError(str(exc)) from exc


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
    from spotify_manager.infrastructure.something_old_audit import append_log

    append_log(summary, path)


def _read_golden_artist_choice(
    reader: ArtistChoiceReader | None,
    artist: GoldenOldieArtist,
    _artist_name: str,
    candidates: tuple[SpotifyArtistCandidate, ...],
) -> str:
    if reader is None:
        raise SomethingOldError("No Spotify artist choice reader is available.")
    return reader(artist, candidates)


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
    """Refresh history and fill an empty Something Old playlist cautiously.

    Args:
        sp: Caller-owned Spotify client.
        lastfm: Caller-owned history reader.
        playlist_id: Original destination identity.
        expected_username: Original expected Last.fm account.
        mode_reader: Original recipe interaction.
        album_choice_reader: Original studio-release interaction.
        artist_choice_reader: Optional original exact-artist ambiguity interaction.
        dry_run: Original preview behavior, including history refresh semantics.
        export_path: Original canonical history location.
        legacy_delta_path: Original optional history delta location.
        backup_dir: Original history backup directory.
        history_log_path: Original history refresh audit location.
        log_path: Original successful selection audit location.
        now: Original optional effective timestamp.
        progress_callback: Original optional stage presenter.
        retry_call: Original read retry policy.

    Returns:
        Original complete selected, cancelled or nonempty outcome.

    Raises:
        SomethingOldError: Original history, selection, authority or audit fails.
    """
    from spotify_manager.bootstrap.something_old_run import (
        run_something_old as run_workflow,
    )

    return run_workflow(
        sp,
        lastfm,
        playlist_id,
        expected_username,
        mode_reader,
        album_choice_reader,
        artist_choice_reader,
        dry_run,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        log_path,
        now,
        progress_callback,
        retry_call,
    )
