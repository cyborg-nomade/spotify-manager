"""Construct legacy workflow dependencies at original compatibility seams."""

from functools import partial

from spotipy import Spotify

from spotify_manager import loaders_savers as files
from spotify_manager.application import legacy_library_control
from spotify_manager.application import legacy_library_refresh
from spotify_manager.application.legacy_library_effects import AlbumRefresh
from spotify_manager.application.legacy_library_effects import ConversionCatalog
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.application.legacy_library_effects import MonthlyActions
from spotify_manager.application.legacy_library_effects import MonthlyPlaylist
from spotify_manager.application.legacy_library_effects import PlaylistClock
from spotify_manager.application.legacy_library_effects import TrackRead
from spotify_manager.domain.legacy_library import monthly_slice
from spotify_manager.infrastructure import legacy_library_records as records
from spotify_manager.infrastructure.legacy_library_errors import LegacyFailure
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.settings import Settings


def legacy_settings() -> Settings:
    """Construct original process-local legacy settings.

    Returns:
        Original environment-backed settings instance.
    """
    return Settings()


def conversion_files() -> LegacyFiles:
    """Bind original conversion facade's mutable file seams.

    Returns:
        Complete original legacy file dependencies.
    """
    return LegacyFiles(
        files.load_total_albums_file,
        files.load_control_file,
        files.load_your_library_file,
        files.load_comparison_file,
        files.save_total_albums_file,
        files.save_control_file,
        files.save_stats_file,
        files.save_comparison_file,
    )


def monthly_files() -> LegacyFiles:
    """Bind original monthly facade's file reads.

    Returns:
        Original monthly file dependencies.
    """
    return LegacyFiles(
        files.load_total_albums_file,
        files.load_control_file,
        files.load_your_library_file,
        files.load_comparison_file,
        files.save_total_albums_file,
        files.save_control_file,
        files.save_stats_file,
        files.save_comparison_file,
    )


def conversion_catalog(spotify: Spotify) -> ConversionCatalog:
    """Bind original caller-owned conversion membership and restore effects.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original membership and mutation callbacks.
    """
    from spotify_manager.processors.your_library_processors import is_in_library_artist
    from spotify_manager.processors.your_library_processors import is_in_library_track
    from spotify_manager.processors.your_library_processors import (
        save_to_library_artist,
    )
    from spotify_manager.processors.your_library_processors import save_to_library_track
    from spotify_manager.routines.convert_library_file import _contains_added
    from spotify_manager.routines.convert_library_file import _contains_removed

    return ConversionCatalog(
        partial(_contains_removed, spotify),
        partial(enrich_conversion_album, spotify),
        partial(is_in_library_artist, spotify),
        partial(is_in_library_track, spotify),
        partial(save_to_library_artist, spotify),
        partial(save_to_library_track, spotify),
        partial(_contains_added, spotify),
    )


def monthly_actions(spotify: Spotify) -> MonthlyActions:
    """Bind original monthly public stages at invocation time.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original ordered stage callbacks.
    """
    return MonthlyActions(
        partial(_check_control, spotify),
        _update_statistics,
        partial(legacy_library_control.starting_index, echo=print),
        partial(_add_monthly_albums, spotify),
    )


def monthly_playlist(spotify: Spotify) -> MonthlyPlaylist:
    """Bind original processor stage seams for monthly playlist execution.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original selected-track and accepted-write boundaries.
    """
    return MonthlyPlaylist(
        _monthly_selection,
        partial(_monthly_create, spotify),
        partial(_ordered_tracks, spotify),
        partial(_monthly_append, spotify),
        files.save_control_file,
    )


def album_refresh(spotify: Spotify) -> AlbumRefresh:
    """Bind original incremental paging and file authority.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original raw scan dependencies.
    """
    from spotify_manager.processors.total_albums_processor import _next_album_page
    from spotify_manager.processors.total_albums_processor import _recover_page
    from spotify_manager.processors.total_albums_processor import _saved_page

    return AlbumRefresh(
        partial(_saved_page, spotify),
        partial(_recover_page, spotify),
        partial(_next_album_page, spotify),
        records.saved_albums,
        files.load_total_albums_file,
        files.save_total_albums_file,
        page_limit,
    )


def page_limit() -> int:
    """Observe the original live page-size setting.

    Returns:
        Original result with unchanged native boundary errors.
    """
    from spotify_manager.processors import total_albums_processor as total

    return total.settings.limit


def track_read(spotify: Spotify) -> TrackRead:
    """Bind original track paging and tolerant conversion.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original ordered-track dependencies.
    """
    from spotify_manager.processors.total_albums_processor import _next_track_page
    from spotify_manager.processors.total_albums_processor import _track_page

    return TrackRead(
        partial(_track_page, spotify),
        partial(_next_track_page, spotify),
        records.track_rows,
        records.sort_tracks,
        records.validate_tracks,
    )


def enrich_conversion_album(spotify: Spotify, identifier: str) -> SimplifiedAlbum:
    """Invoke the original positional album-enrichment seam.

    Args:
        spotify: Original caller-owned synchronous client.
        identifier: Original requested album identity.

    Returns:
        Original simplified album observation.
    """
    from spotify_manager.processors.control_file_processors import enrich_album

    return enrich_album(identifier, spotify)


def _ordered_tracks(spotify: Spotify, album: SimplifiedAlbum) -> list[SimplifiedTrack]:
    return legacy_library_refresh.tracks(track_read(spotify), album, print)


def _add_monthly_albums(
    spotify: Spotify,
    control_file: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    start: int,
) -> bool:
    return legacy_library_refresh.add_monthly(
        monthly_playlist(spotify), control_file, albums, start, print, LegacyFailure
    )


def _check_control(
    spotify: Spotify, control: list[ControlFileItem], albums: list[SimplifiedAlbum]
) -> bool:
    from spotify_manager.processors.control_file_processors import _contains

    return legacy_library_control.check(
        control,
        albums,
        partial(legacy_library_control.unevaluated, echo=print),
        partial(
            legacy_library_control.evaluate,
            contains=partial(_contains, spotify),
            echo=print,
        ),
        partial(legacy_library_control.reconcile, save=files.save_total_albums_file),
        files.save_control_file,
        print,
    )


def _calculate_statistics(
    control: list[ControlFileItem], albums: list[SimplifiedAlbum]
) -> StatsFileItem:
    return legacy_library_control.calculate(control, albums, print)


def _update_statistics(
    control: list[ControlFileItem], albums: list[SimplifiedAlbum]
) -> bool:
    return legacy_library_control.update_statistics(
        control, albums, _calculate_statistics, files.save_stats_file, print
    )


def _monthly_selection(
    albums: list[SimplifiedAlbum], start: int
) -> list[SimplifiedAlbum]:
    from spotify_manager.processors import total_albums_processor as total

    return monthly_slice(albums, start, total.settings.albums_to_add)


def _monthly_create(spotify: Spotify) -> str:
    from spotify_manager.processors import total_albums_processor as total
    from spotify_manager.processors.total_albums_processor import _create_playlist

    return legacy_library_refresh.playlist(
        PlaylistClock(total.datetime.now, partial(_create_playlist, spotify)), print
    )


def _monthly_append(
    spotify: Spotify, tracks: list[SimplifiedTrack], playlist_id: str
) -> None:
    from spotify_manager.processors.total_albums_processor import _append_batch
    from spotify_manager.processors.total_albums_processor import _append_single

    legacy_library_refresh.append_tracks(
        tracks,
        playlist_id,
        partial(_append_single, spotify),
        partial(_append_batch, spotify),
        print,
    )
