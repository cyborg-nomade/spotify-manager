"""Rebuild Last.fm-style album recommendations for Sauvignon Terre-Neuve."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal
from typing import Protocol

from spotipy import Spotify

from spotify_manager.application.sauvignon_values import (
    SauvignonConfigError as SauvignonConfigError,
)
from spotify_manager.application.sauvignon_values import (
    SauvignonError as SauvignonError,
)
from spotify_manager.application.sauvignon_values import (
    SauvignonSpotifyError as SauvignonSpotifyError,
)
from spotify_manager.application.sauvignon_values import (
    SauvignonStateError as SauvignonStateError,
)
from spotify_manager.application.sauvignon_values import (
    SauvignonSummary as SauvignonSummary,
)
from spotify_manager.domain import album_recommendations as album_policy
from spotify_manager.domain.album_recommendations import (
    AlbumRecommendation as AlbumRecommendation,
)
from spotify_manager.domain.album_recommendations import FirstTrack as FirstTrack
from spotify_manager.domain.album_recommendations import (
    SpotifyAlbumOption as SpotifyAlbumOption,
)
from spotify_manager.domain.album_recommendations import (
    _AlbumAccumulator as _AlbumAccumulator,
)
from spotify_manager.domain.album_selection import SauvignonAction as SauvignonAction
from spotify_manager.domain.album_selection import SauvignonResult as SauvignonResult

# UFI
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art
from spotify_manager.routines import new_wine
from spotify_manager.routines.slow_listening import release_identity as release_identity


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


class LastFmReader(found_art.LastFmReader, Protocol):
    """Last.fm methods required through the shared Found Art machinery."""


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
    """Return the original edition-tolerant artist and album identity.

    Args:
        artist: Original credited artist spelling.
        album: Original album display title.

    Returns:
        Normalized artist and edition-neutral release title.
    """
    return album_policy.canonical_album_key(artist, album)


def heard_album_keys(
    scrobbles: list[blast_from_past.Scrobble],
) -> set[AlbumKey]:
    """Return every original valid album identity present in canonical history.

    Args:
        scrobbles: Original ordered canonical plays.

    Returns:
        Distinct valid album identities, excluding absent album names.
    """
    return album_policy.heard_album_keys(scrobbles)


def previously_added_album_keys(path: Path = DEFAULT_LOG_PATH) -> set[AlbumKey]:
    """Read original actual additions from the configured audit.

    Args:
        path: Original audit location.

    Returns:
        Distinct normalized accepted album identities.

    Raises:
        SauvignonStateError: The original audit cannot be read or decoded.
    """
    from spotify_manager.infrastructure.sauvignon_data import (
        previously_added_album_keys as read,
    )

    return read(path)


def _artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    from spotify_manager.infrastructure.album_recommendations import artist_pairs

    return artist_pairs(raw)


def _positive_int(raw: object) -> int:
    from spotify_manager.infrastructure.album_recommendations import positive_int

    return positive_int(raw)


def _album_option(
    raw_track: object,
    candidate: found_art.FoundArtCandidate,
    search_rank: int,
) -> SpotifyAlbumOption | None:
    from spotify_manager.infrastructure.album_recommendations import parse_album_option

    return parse_album_option(
        raw_track, candidate, search_rank, blast_from_past.matching_spotify_track
    )


def search_candidate_albums(
    spotify: Spotify,
    candidate: found_art.FoundArtCandidate,
    retry_call: RetryCall,
) -> tuple[SpotifyAlbumOption, ...]:
    """Read and decode original eligible album editions for one recommended track.

    Args:
        spotify: Caller-owned Spotify client.
        candidate: Original ranked Last.fm candidate.
        retry_call: Existing caller-owned retry boundary.

    Returns:
        Preferred eligible editions in original deterministic preference order.

    Raises:
        SauvignonSpotifyError: Search response lacks the original items list.
    """
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
    from spotify_manager.infrastructure.album_recommendations import parse_album_search

    return parse_album_search(response, candidate, _album_option)


def _option_rank(option: SpotifyAlbumOption) -> tuple[float, int, int]:
    return album_policy.option_rank(option)


def _option_sort_key(option: SpotifyAlbumOption) -> tuple[float, int, int, str]:
    return album_policy.option_sort_key(option)


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
    """Resolve original track evidence and rank eligible observed albums.

    Args:
        spotify: Caller-owned Spotify client.
        candidates: Original ordered ranked track pool.
        excluded_keys: Original heard and previously added album keys.
        existing_album_ids: Original represented destination album identities.
        maximum_candidates: Original Python-slice limit on considered tracks.
        week_start: Original effective listening week.
        retry_call: Existing caller-owned retry behavior.
        progress_callback: Optional original candidate presenter.

    Returns:
        Original ranked album recommendations after all observations succeed.

    Raises:
        SauvignonSpotifyError: Existing catalog observations are unusable.
    """
    from spotify_manager.bootstrap.album_recommendations import gather_albums

    return gather_albums(
        spotify,
        candidates,
        excluded_keys,
        existing_album_ids,
        maximum_candidates,
        week_start,
        retry_call,
        progress_callback,
    )


def _genuinely_ambiguous(options: tuple[SpotifyAlbumOption, ...]) -> bool:
    """Return whether editions differ in visible release metadata."""
    return album_policy.genuinely_ambiguous(options)


def choose_album_option(
    recommendation: AlbumRecommendation,
    choice_reader: AlbumChoiceReader | None,
) -> SpotifyAlbumOption | Literal["skip", "quit"]:
    """Preserve automatic selection and original ambiguous-edition interaction.

    Args:
        recommendation: Original ranked evidence and ordered preferred editions.
        choice_reader: Original interaction, absent for noninteractive runs.

    Returns:
        First equivalent edition, selected first matching identity, skip or quit.
    """
    from spotify_manager.application.album_recommendations import choose_album

    return choose_album(recommendation, choice_reader, CHOICE_SKIP, CHOICE_QUIT)


def load_first_track(
    spotify: Spotify,
    album: SpotifyAlbumOption,
    retry_call: RetryCall,
) -> FirstTrack:
    """Read the first originally playable track without reordering the response.

    Args:
        spotify: Caller-owned Spotify client.
        album: Original chosen edition.
        retry_call: Existing caller-owned retry boundary.

    Returns:
        First original valid track identity, URI and display name.

    Raises:
        SauvignonSpotifyError: Response is invalid or has no playable track.
    """
    response = retry_call(
        partial(spotify.album_tracks, album.spotify_id, limit=50, offset=0),
        f"loading the first track of {album.artist} - {album.album}",
    )
    from spotify_manager.infrastructure.album_recommendations import parse_first_track

    return parse_first_track(response, album)


def _result_record(result: SauvignonResult) -> dict[str, object]:
    from spotify_manager.infrastructure.sauvignon_data import _result_record as record

    return record(result)


def append_log(summary: SauvignonSummary, path: Path = DEFAULT_LOG_PATH) -> None:
    """Append the original completed outcome after accepted playlist effects.

    Args:
        summary: Original complete run result.
        path: Original audit destination.

    Raises:
        SauvignonStateError: The original log cannot be written.
    """
    from spotify_manager.infrastructure.sauvignon_data import append_log as append

    append(summary, path)


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
    from spotify_manager.bootstrap.sauvignon import run_sauvignon

    return run_sauvignon(
        spotify,
        lastfm,
        playlist_id,
        choice_reader,
        count,
        max_playlist_length,
        seed_count,
        dry_run,
        echo,
        progress_callback,
        retry_call,
        export_path,
        recent_path,
        cache_path,
        log_path,
        now,
    )


def _append_recommendation_albums(
    spotify: Spotify,
    playlist_id: str,
    additions: list[tuple[SpotifyAlbumOption, FirstTrack]],
) -> object:
    return spotify._post(
        f"playlists/{playlist_id}/items",
        payload={"uris": [track.uri for _album, track in additions]},
    )
