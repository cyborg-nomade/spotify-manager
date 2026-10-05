"""Acquire discography facts through the existing catalog and history stages."""

from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.discography_catalog import DiscographyCatalog
from spotify_manager.application.discography_catalog import DiscographyPage
from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.discography_queues import DiscographyQueues
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName
from spotify_manager.infrastructure.discography_records import catalog_page
from spotify_manager.infrastructure.discography_records import saved_statuses
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import discography as legacy
from spotify_manager.routines import new_wine


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def historical(
    path: Path,
    today: date | None,
    random: legacy.RandomIndexReader,
    progress: legacy.ProgressCallback | None,
) -> HistoricalArtistSelection:
    """Bind original history loading before calendar and random reads.

    Args:
        path: Original history export.
        today: Original optional effective date.
        random: Original caller index reader.
        progress: Original optional stage presenter.

    Returns:
        Complete original historical selection.
    """
    from spotify_manager.routines.blast_from_past import load_scrobbles_by_date
    from spotify_manager.routines.palace_of_memory import palace_cutoff

    return DiscographyHistory(
        partial(load_scrobbles_by_date, path),
        partial(palace_cutoff, today),
        random,
        partial(_progress, progress),
        blast_from_past.FIRST_ELIGIBLE_DATE,
    ).run()


def _playlist(
    spotify: Spotify, retry: legacy.RetryCall, playlist: str
) -> tuple[PlaylistTrack, ...]:
    from spotify_manager.routines.new_wine import load_playlist_tracks

    try:
        return load_playlist_tracks(spotify, playlist, retry)
    except new_wine.NewWineError as exc:
        raise DiscographyError(str(exc)) from exc


def queues(
    spotify: Spotify,
    playlists: dict[QueueName, str],
    retry: legacy.RetryCall,
    extra: str | None,
) -> tuple[
    dict[QueueName, tuple[QueueArtist, ...]], dict[str, tuple[ArtistMarkers, ...]]
]:
    """Bind original playlist observations without importing private routine policies.

    Args:
        spotify: Original SDK client.
        playlists: Original source identities.
        retry: Original caller retry.
        extra: Original optional auxiliary playlist.

    Returns:
        Original complete queues and marker groups.
    """
    return DiscographyQueues(partial(_playlist, spotify, retry), playlists, extra).run()


def _page(
    spotify: Spotify, artist: str, retry: legacy.RetryCall, offset: int
) -> DiscographyPage:
    from spotify_manager.routines.discography import _release_page

    return catalog_page(_release_page(spotify, artist, offset, retry), artist)


def _saved(
    spotify: Spotify, retry: legacy.RetryCall, identities: list[str]
) -> list[bool]:
    from spotify_manager.routines.discography import _saved_batch

    raw = _saved_batch(spotify, identities, retry)
    return saved_statuses(raw, len(identities))


def catalog(
    spotify: Spotify, artist: str, retry: legacy.RetryCall
) -> tuple[CatalogRelease, ...]:
    """Bind original raw pages and exact saved-status batch validation.

    Args:
        spotify: Original SDK client.
        artist: Original primary identity.
        retry: Original caller retry.

    Returns:
        Original canonical chronological catalog.
    """
    return DiscographyCatalog(
        partial(_page, spotify, artist, retry),
        partial(_saved, spotify, retry),
        legacy.SAVED_ALBUM_BATCH_SIZE,
    ).run()
