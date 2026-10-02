"""Construct legacy workflow dependencies at original compatibility seams."""

from functools import partial

from spotipy import Spotify

from spotify_manager import loaders_savers as files
from spotify_manager.application.legacy_library_effects import AlbumRefresh
from spotify_manager.application.legacy_library_effects import ConversionCatalog
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.application.legacy_library_effects import MonthlyActions
from spotify_manager.application.legacy_library_effects import MonthlyPlaylist
from spotify_manager.application.legacy_library_effects import TrackRead
from spotify_manager.infrastructure import legacy_library_records as records
from spotify_manager.models.albums import SimplifiedAlbum
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
    from spotify_manager.routines import convert_library_file as conversion

    return LegacyFiles(
        conversion.load_total_albums_file,
        files.load_control_file,
        conversion.load_your_library_file,
        conversion.load_comparison_file,
        conversion.save_total_albums_file,
        files.save_control_file,
        files.save_stats_file,
        conversion.save_comparison_file,
    )


def monthly_files() -> LegacyFiles:
    """Bind original monthly facade's file reads.

    Returns:
        Original monthly file dependencies.
    """
    from spotify_manager.routines import monthly_routine as monthly

    return LegacyFiles(
        monthly.load_total_albums_file,
        monthly.load_control_file,
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
    from spotify_manager.routines import convert_library_file as conversion

    return ConversionCatalog(
        partial(conversion._contains_removed, spotify),
        partial(enrich_conversion_album, spotify),
        partial(conversion.is_in_library_artist, spotify),
        partial(conversion.is_in_library_track, spotify),
        partial(conversion.save_to_library_artist, spotify),
        partial(conversion.save_to_library_track, spotify),
        partial(conversion._contains_added, spotify),
    )


def monthly_actions(spotify: Spotify) -> MonthlyActions:
    """Bind original monthly public stages at invocation time.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original ordered stage callbacks.
    """
    from spotify_manager.routines import monthly_routine as monthly

    return MonthlyActions(
        partial(monthly.check_album_results, spotify),
        monthly.update_stats,
        monthly.get_starting_index,
        partial(monthly.add_monthly_albums, spotify),
    )


def monthly_playlist(spotify: Spotify) -> MonthlyPlaylist:
    """Bind original processor stage seams for monthly playlist execution.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original selected-track and accepted-write boundaries.
    """
    from spotify_manager.processors import total_albums_processor as total

    return MonthlyPlaylist(
        total.get_months_items,
        partial(total.create_playlist, spotify),
        partial(total.get_ordered_tracks, spotify),
        partial(total.append_to_playlist, spotify),
        total.save_control_file,
    )


def album_refresh(spotify: Spotify) -> AlbumRefresh:
    """Bind original incremental paging and file authority.

    Args:
        spotify: Original synchronous client.

    Returns:
        Original raw scan dependencies.
    """
    from spotify_manager.processors import total_albums_processor as total

    return AlbumRefresh(
        partial(total._saved_page, spotify),
        partial(total._recover_page, spotify),
        partial(total._next_album_page, spotify),
        records.saved_albums,
        total.load_total_albums_file,
        total.save_total_albums_file,
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
    from spotify_manager.processors import total_albums_processor as total

    return TrackRead(
        partial(total._track_page, spotify),
        partial(total._next_track_page, spotify),
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
    from spotify_manager.routines import convert_library_file as conversion

    return conversion.enrich_album(identifier, spotify)
