"""Recover recently dormant artists into A Blast from the Past."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal

from spotipy import Spotify

# UFI
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_kids
from spotify_manager.routines import release_check


DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH
DEFAULT_COUNT = 5
LOOKBACK_YEARS = 4

Echo = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
RetryCall = blast_from_past.RetryCall
CancelCheck = blast_from_past.CancelCheck


class BlastFromPastArtistsError(blast_from_past.BlastFromPastError):
    """Raised when dormant artists cannot be added safely."""


@dataclass(frozen=True)
class DormantArtist:
    """One artist heard recently, but not during the current year."""

    key: str
    name: str
    scrobbles: int


@dataclass(frozen=True)
class DormantArtistResult:
    """Spotify outcome for one alphabetically eligible artist."""

    artist: str
    scrobbles: int
    spotify_artist: str | None
    track: str | None
    popularity: int | None
    action: Literal["added", "no mapping", "no liked track"]


@dataclass(frozen=True)
class DormantArtistSummary:
    """Completed dormant-artist recovery update."""

    current_year: int
    history_years: tuple[int, ...]
    candidate_count: int
    represented_count: int
    playlist_length_before: int
    playlist_length_after: int
    requested_count: int
    results: tuple[DormantArtistResult, ...]

    @property
    def added(self) -> int:
        """Return how many liked tracks were appended."""
        return sum(result.action == "added" for result in self.results)


def dormant_artists(
    path: Path = DEFAULT_SCROBBLES_PATH,
    *,
    today: date | None = None,
) -> tuple[DormantArtist, ...]:
    """Return artists heard in every prior year, but not the current one."""
    current_date = today or datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    current_year = current_date.year
    history_years = set(range(current_year - LOOKBACK_YEARS, current_year))
    scrobbles_by_date = blast_from_past.load_scrobbles_by_date(path)
    current_keys: set[str] = set()
    keys_by_year: dict[int, set[str]] = {year: set() for year in history_years}
    names: dict[str, str] = {}
    counts: Counter[str] = Counter()

    for scrobble_date, scrobbles in scrobbles_by_date.items():
        if scrobble_date.year not in history_years | {current_year}:
            continue
        for scrobble in scrobbles:
            key = blast_from_past.normalize_name(scrobble.artist)
            if not key:
                continue
            names.setdefault(key, scrobble.artist)
            if scrobble_date.year == current_year:
                current_keys.add(key)
            else:
                keys_by_year[scrobble_date.year].add(key)
                counts[key] += 1

    eligible_keys = set.intersection(*keys_by_year.values()) - current_keys

    return tuple(
        sorted(
            (
                DormantArtist(key=key, name=names[key], scrobbles=count)
                for key, count in counts.items()
                if key in eligible_keys
            ),
            key=lambda artist: (artist.name.casefold(), artist.key),
        )
    )


def _liked_statuses(
    sp: Spotify,
    tracks: tuple[new_kids.CatalogTrack, ...],
    retry_call: RetryCall,
) -> dict[str, bool]:
    statuses: dict[str, bool] = {}
    for start in range(0, len(tracks), new_kids.CONTAINS_BATCH_SIZE):
        batch = tracks[start : start + new_kids.CONTAINS_BATCH_SIZE]
        response = retry_call(
            partial(
                sp.current_user_saved_tracks_contains,
                [track.spotify_id for track in batch],
            ),
            f"checking {len(batch)} tracks in Liked Songs",
        )
        if not isinstance(response, list) or len(response) != len(batch):
            raise BlastFromPastArtistsError(
                "Spotify returned invalid Liked Songs statuses."
            )
        statuses.update(
            {
                track.spotify_id: bool(liked)
                for track, liked in zip(batch, response, strict=True)
            }
        )
    return statuses


def _catalog_tracks(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[new_kids.CatalogTrack, ...]:
    catalog = new_kids.load_ranked_catalog(sp, artist_id, retry_call)
    tracks: dict[str, new_kids.CatalogTrack] = {}
    for release in catalog:
        for track in new_kids.load_release_tracks(sp, release, retry_call):
            if track.primary_artist_id == artist_id:
                tracks.setdefault(track.spotify_id, track)
    return tuple(tracks.values())


def _track_popularities(
    sp: Spotify,
    tracks: tuple[new_kids.CatalogTrack, ...],
    retry_call: RetryCall,
) -> tuple[new_kids.CatalogTrack, ...]:
    populated: list[new_kids.CatalogTrack] = []
    by_id = {track.spotify_id: track for track in tracks}
    track_ids = list(by_id)
    for start in range(0, len(track_ids), new_kids.TRACK_BATCH_SIZE):
        batch = track_ids[start : start + new_kids.TRACK_BATCH_SIZE]
        response = retry_call(
            partial(sp.tracks, batch),
            f"loading popularity for {len(batch)} liked tracks",
        )
        raw_tracks = response.get("tracks") if isinstance(response, dict) else None
        if not isinstance(raw_tracks, list):
            raise BlastFromPastArtistsError(
                "Spotify returned invalid liked-track details."
            )
        for raw_track in raw_tracks:
            if not isinstance(raw_track, dict):
                continue
            spotify_id = str(raw_track.get("id") or "").strip()
            source = by_id.get(spotify_id)
            if source is None:
                continue
            popularity = raw_track.get("popularity")
            populated.append(
                replace(
                    source,
                    popularity=popularity if isinstance(popularity, int) else None,
                )
            )
    return tuple(populated)


def most_popular_liked_track(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> new_kids.CatalogTrack | None:
    """Return the artist's most popular live-liked primary-credit track."""
    _album_ranks, top_tracks = new_kids.load_top_track_data(
        sp,
        artist_id,
        retry_call,
    )
    top_liked = _liked_statuses(sp, top_tracks, retry_call)
    liked_top_tracks = tuple(
        track for track in top_tracks if top_liked.get(track.spotify_id, False)
    )
    if liked_top_tracks:
        return max(
            liked_top_tracks,
            key=lambda track: (
                track.popularity if track.popularity is not None else -1,
                -track.track_number,
                track.name.casefold(),
            ),
        )

    catalog_tracks = _catalog_tracks(sp, artist_id, retry_call)
    liked = _liked_statuses(sp, catalog_tracks, retry_call)
    liked_tracks = tuple(
        track for track in catalog_tracks if liked.get(track.spotify_id, False)
    )
    if not liked_tracks:
        return None
    populated = _track_popularities(sp, liked_tracks, retry_call)
    if not populated:
        return None
    return max(
        populated,
        key=lambda track: (
            track.popularity if track.popularity is not None else -1,
            -track.disc_number,
            -track.track_number,
            track.name.casefold(),
        ),
    )


def _spotify_artist(
    sp: Spotify,
    artist: DormantArtist,
    rank: int,
    retry_call: RetryCall,
) -> release_check.SpotifyArtistCandidate | None:
    ranked = release_check.RankedArtist(
        key=artist.key,
        name=artist.name,
        scrobbles=artist.scrobbles,
        rank=rank,
    )
    exact = tuple(
        candidate
        for candidate in release_check.search_spotify_artists(sp, ranked, retry_call)
        if candidate.exact_name
    )
    return exact[0] if len(exact) == 1 else None


def add_dormant_artists_to_blast_from_past(
    sp: Spotify,
    playlist_id: str,
    *,
    count: int = DEFAULT_COUNT,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = blast_from_past._direct_retry,
    cancel_check: CancelCheck | None = None,
    dry_run: bool = False,
) -> DormantArtistSummary:
    """Append five alphabetically selected dormant artists to the playlist."""
    if count < 1:
        raise ValueError("count must be at least 1")
    current_date = today or datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    history_years = tuple(range(current_date.year - LOOKBACK_YEARS, current_date.year))
    candidates = dormant_artists(path, today=current_date)
    playlist = blast_from_past.load_playlist_state(
        sp,
        playlist_id,
        retry_call,
        cancel_check,
    )
    represented = set(playlist.primary_artist_keys)
    represented_count = sum(candidate.key in represented for candidate in candidates)
    pending: list[new_kids.CatalogTrack] = []
    results: list[DormantArtistResult] = []

    for rank, candidate in enumerate(candidates, start=1):
        if len(pending) >= count:
            break
        blast_from_past.check_cancel(cancel_check)
        if candidate.key in represented:
            continue
        status = f"Checking dormant artist {candidate.name}"
        if progress_callback is not None:
            progress_callback(len(pending), count, status)
        spotify_artist = _spotify_artist(sp, candidate, rank, retry_call)
        if spotify_artist is None:
            echo(f"Skipped {candidate.name}: no unambiguous Spotify mapping.")
            results.append(
                DormantArtistResult(
                    artist=candidate.name,
                    scrobbles=candidate.scrobbles,
                    spotify_artist=None,
                    track=None,
                    popularity=None,
                    action="no mapping",
                )
            )
            continue
        track = most_popular_liked_track(sp, spotify_artist.spotify_id, retry_call)
        if track is None:
            echo(f"Skipped {candidate.name}: no liked primary-artist track.")
            results.append(
                DormantArtistResult(
                    artist=candidate.name,
                    scrobbles=candidate.scrobbles,
                    spotify_artist=spotify_artist.name,
                    track=None,
                    popularity=None,
                    action="no liked track",
                )
            )
            continue
        if track.spotify_id in playlist.track_ids or any(
            selected.spotify_id == track.spotify_id for selected in pending
        ):
            represented.add(candidate.key)
            continue
        pending.append(track)
        represented.add(candidate.key)
        results.append(
            DormantArtistResult(
                artist=candidate.name,
                scrobbles=candidate.scrobbles,
                spotify_artist=spotify_artist.name,
                track=track.name,
                popularity=track.popularity,
                action="added",
            )
        )

    if pending and not dry_run:
        blast_from_past.add_spotify_matches(
            sp,
            playlist_id,
            [
                blast_from_past.SpotifyTrackMatch(
                    spotify_id=track.spotify_id,
                    uri=track.uri,
                    track=track.name,
                    artists=(track.primary_artist_name,),
                    album="",
                    search_rank=1,
                    track_similarity=1.0,
                    album_similarity=None,
                    popularity=track.popularity,
                    liked=True,
                )
                for track in pending
            ],
            retry_call,
            cancel_check,
        )
    if progress_callback is not None:
        progress_callback(len(pending), count, "Dormant-artist recovery complete")
    return DormantArtistSummary(
        current_year=current_date.year,
        history_years=history_years,
        candidate_count=len(candidates),
        represented_count=represented_count,
        playlist_length_before=playlist.total_items,
        playlist_length_after=playlist.total_items + (0 if dry_run else len(pending)),
        requested_count=count,
        results=tuple(results),
    )


__all__ = [
    "BlastFromPastArtistsError",
    "DEFAULT_COUNT",
    "DormantArtist",
    "DormantArtistResult",
    "DormantArtistSummary",
    "add_dormant_artists_to_blast_from_past",
    "dormant_artists",
    "most_popular_liked_track",
]
