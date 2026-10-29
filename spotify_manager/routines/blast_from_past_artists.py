"""Recover recently dormant artists into A Blast from the Past."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from pathlib import Path

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.dormant_values import (
    BlastFromPastArtistsError as BlastFromPastArtistsError,
)
from spotify_manager.application.dormant_values import (
    DormantArtistSummary as DormantArtistSummary,
)
from spotify_manager.application.ports.runtime import NO_RETRY
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.runtime import ReviewProgress
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.dormant_artists import DormantArtist as DormantArtist
from spotify_manager.domain.dormant_artists import (
    DormantArtistResult as DormantArtistResult,
)
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.python_compat.retry import (
    BlockingRetry as LegacyRetry,
)

# UFI
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_kids
from spotify_manager.routines import release_check


type ProgressCallback = ReviewProgress


type Echo = Messages


type RetryCall = Retry


DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH
DEFAULT_COUNT = 5
LOOKBACK_YEARS = 4


CancelCheck = blast_from_past.CancelCheck


async def async_dormant_artists(
    path: Path = DEFAULT_SCROBBLES_PATH,
    *,
    today: date | None = None,
) -> tuple[DormantArtist, ...]:
    """Return original artists heard in every prior year but absent this year.

    Args:
        path: Original canonical history location.
        today: Optional effective local calendar date.

    Returns:
        Original alphabetical dormant candidates.

    Raises:
        LastFmExportError: The original history cannot be read or decoded.
    """
    from spotify_manager.domain.dormant_artists import eligible_artists

    current_date = today or datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    return eligible_artists(
        (await blast_from_past.async_load_scrobbles_by_date(path)),
        current_date.year,
        LOOKBACK_YEARS,
    )


async def _liked_statuses(
    sp: Spotify,
    tracks: tuple[new_kids.CatalogTrack, ...],
    retry_call: RetryCall,
) -> dict[str, bool]:
    statuses: dict[str, bool] = {}
    for start in range(0, len(tracks), new_kids.CONTAINS_BATCH_SIZE):
        batch = tracks[start : start + new_kids.CONTAINS_BATCH_SIZE]
        response = await _read_liked_track_batch(retry_call, batch, sp)
        from spotify_manager.infrastructure.dormant_catalog import liked_statuses

        statuses.update(liked_statuses(response, batch))
    return statuses


async def _catalog_tracks(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> tuple[new_kids.CatalogTrack, ...]:
    catalog = await new_kids.async_load_ranked_catalog(sp, artist_id, retry_call)
    tracks: dict[str, new_kids.CatalogTrack] = {}
    for release in catalog:
        for track in await new_kids.async_load_release_tracks(sp, release, retry_call):
            _remember_primary_track(tracks, track, artist_id)
    return tuple(tracks.values())


async def _track_popularities(
    sp: Spotify,
    tracks: tuple[new_kids.CatalogTrack, ...],
    retry_call: RetryCall,
) -> tuple[new_kids.CatalogTrack, ...]:
    populated: list[new_kids.CatalogTrack] = []
    by_id = {track.spotify_id: track for track in tracks}
    track_ids = list(by_id)
    for start in range(0, len(track_ids), new_kids.TRACK_BATCH_SIZE):
        batch = track_ids[start : start + new_kids.TRACK_BATCH_SIZE]
        response = await _read_popularity_batch(retry_call, batch, sp)
        from spotify_manager.infrastructure.dormant_catalog import popularity_details

        populated.extend(popularity_details(response, by_id))
    return tuple(populated)


async def async_most_popular_liked_track(
    sp: Spotify,
    artist_id: str,
    retry_call: RetryCall,
) -> new_kids.CatalogTrack | None:
    """Return the original preferred live-liked primary-credit marker.

    Args:
        sp: Caller-owned Spotify client.
        artist_id: Original mapped artist.
        retry_call: Original retry policy.

    Returns:
        Original preferred marker or no liked primary-credit track.

    Raises:
        BlastFromPastArtistsError: Original liked/detail response is invalid.
    """
    from spotify_manager.interfaces.operations.blast_from_past_artists import (
        most_popular_liked_track as operation,
    )

    return await operation(sp, artist_id, retry_call)


async def _spotify_artist(
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
    exact = []
    for candidate in await release_check.async_search_spotify_artists(
        sp, ranked, retry_call
    ):
        if candidate.exact_name:
            exact.append(candidate)
    return exact[0] if len(exact) == 1 else None


async def async_add_dormant_artists_to_blast_from_past(
    sp: Spotify,
    playlist_id: str,
    *,
    count: int = DEFAULT_COUNT,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = NO_RETRY,
    cancel_check: CancelCheck | None = None,
    dry_run: bool = False,
) -> DormantArtistSummary:
    """Recover the requested original alphabetical dormant artists.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Original destination.
        count: Requested marker count.
        path: Original canonical history location.
        today: Optional effective local calendar date.
        echo: Original skipped-candidate presentation.
        progress_callback: Original candidate and completion presentation.
        retry_call: Original retry policy.
        cancel_check: Original cancellation callback.
        dry_run: Original preview mode, retaining added result labels.

    Returns:
        Original completed recovery summary.

    Raises:
        ValueError: Count is below the original minimum.
        BlastFromPastArtistsError: Original catalog observations are unusable.
        BlastFromPastCancelledError: Original safe cancellation is requested.
    """
    from spotify_manager.interfaces.operations.blast_from_past_artists import (
        add_dormant_artists_to_blast_from_past as operation,
    )

    return await operation(
        sp,
        playlist_id,
        count=count,
        path=path,
        today=today,
        echo=echo,
        progress_callback=progress_callback,
        retry_call=retry_call,
        cancel_check=cancel_check,
        dry_run=dry_run,
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


def _remember_primary_track(
    tracks: dict[str, new_kids.CatalogTrack],
    track: new_kids.CatalogTrack,
    artist_id: str,
) -> None:
    if track.primary_artist_id == artist_id:
        tracks.setdefault(track.spotify_id, track)


async def _read_liked_track_batch(
    retry_call: RetryCall, batch: tuple[new_kids.CatalogTrack, ...], sp: Spotify
) -> object:
    for attempt in retry_call.attempts(f"checking {len(batch)} tracks in Liked Songs"):
        async with attempt:
            return await sp.current_user_saved_tracks_contains(
                [track.spotify_id for track in batch]
            )
    raise AssertionError("Retry scopes must include an attempt")


async def _read_popularity_batch(
    retry_call: RetryCall, batch: list[str], sp: Spotify
) -> object:
    for attempt in retry_call.attempts(
        f"loading popularity for {len(batch)} liked tracks"
    ):
        async with attempt:
            return await sp.tracks(batch)
    raise AssertionError("Retry scopes must include an attempt")


def dormant_artists(
    path: Path = DEFAULT_SCROBBLES_PATH, *, today: date | None = None
) -> tuple[DormantArtist, ...]:
    """Return original artists heard in every prior year but absent this year.

    Args:
        path: Original canonical history location.
        today: Optional effective local calendar date.

    Returns:
        Original alphabetical dormant candidates.

    Raises:
        LastFmExportError: The original history cannot be read or decoded.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_dormant_artists(path, today=today))


def most_popular_liked_track(
    sp: LegacySpotify, artist_id: str, retry_call: RetryCall | LegacyRetry
) -> new_kids.CatalogTrack | None:
    """Return the original preferred live-liked primary-credit marker.

    Args:
        sp: Caller-owned Spotify client.
        artist_id: Original mapped artist.
        retry_call: Original retry policy.

    Returns:
        Original preferred marker or no liked primary-credit track.

    Raises:
        BlastFromPastArtistsError: Original liked/detail response is invalid.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.retry import PythonRetry
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_most_popular_liked_track(
            legacy_spotify(sp), artist_id, PythonRetry(retry_call)
        )
    )


def add_dormant_artists_to_blast_from_past(
    sp: LegacySpotify,
    playlist_id: str,
    *,
    count: int = DEFAULT_COUNT,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    echo: Echo = STANDARD_OUTPUT,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | LegacyRetry = NO_RETRY,
    cancel_check: CancelCheck | None = None,
    dry_run: bool = False,
) -> DormantArtistSummary:
    """Recover the requested original alphabetical dormant artists.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Original destination.
        count: Requested marker count.
        path: Original canonical history location.
        today: Optional effective local calendar date.
        echo: Original skipped-candidate presentation.
        progress_callback: Original candidate and completion presentation.
        retry_call: Original retry policy.
        cancel_check: Original cancellation callback.
        dry_run: Original preview mode, retaining added result labels.

    Returns:
        Original completed recovery summary.

    Raises:
        ValueError: Count is below the original minimum.
        BlastFromPastArtistsError: Original catalog observations are unusable.
        BlastFromPastCancelledError: Original safe cancellation is requested.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.retry import PythonRetry
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_add_dormant_artists_to_blast_from_past(
            legacy_spotify(sp),
            playlist_id,
            count=count,
            path=path,
            today=today,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=PythonRetry(retry_call),
            cancel_check=cancel_check,
            dry_run=dry_run,
        )
    )
