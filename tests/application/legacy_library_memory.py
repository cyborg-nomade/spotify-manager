"""Construct legacy application stages independently of production bootstrap."""

from collections.abc import Callable
from functools import partial
from typing import cast

from spotipy import Spotify

from spotify_manager.application import legacy_library_control as control
from spotify_manager.application import legacy_library_conversion as conversion
from spotify_manager.application import legacy_library_monthly as monthly
from spotify_manager.application import legacy_library_refresh as refresh
from spotify_manager.application.legacy_library_effects import AlbumRefresh
from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import ConversionCatalog
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.application.legacy_library_effects import MonthlyActions
from spotify_manager.application.legacy_library_effects import MonthlyPlaylist
from spotify_manager.application.legacy_library_effects import Page
from spotify_manager.application.legacy_library_effects import PlaylistClock
from spotify_manager.application.legacy_library_effects import TrackRead
from spotify_manager.infrastructure import legacy_library_records as records
from spotify_manager.infrastructure.legacy_library_errors import LegacyFailure
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.processors import control_file_processors as old_control
from spotify_manager.processors import total_albums_processor as old_total
from spotify_manager.processors import your_library_processors as library
from spotify_manager.utils import comparison
from tests.support.effects import FixedDatetime
from tests.support.legacy_library_run import Catalog
from tests.support.legacy_library_run import Memory
from tests.support.legacy_library_run import Scenario


def files(memory: Memory) -> LegacyFiles:
    return LegacyFiles(
        memory.read_albums,
        memory.read_control,
        memory.read_export,
        cast(Callable[[], Comparison], memory.read_comparison),
        partial(memory.write, "save_albums"),
        partial(memory.write, "save_control"),
        partial(memory.write, "save_stats"),
        partial(memory.write, "save_comparison"),
    )


def catalog(client: Catalog) -> ConversionCatalog:
    spotify = cast(Spotify, client)
    return ConversionCatalog(
        partial(contains, client),
        partial(old_control.enrich_album, sp=spotify),
        partial(library.is_in_library_artist, spotify),
        partial(library.is_in_library_track, spotify),
        partial(library.save_to_library_artist, spotify),
        partial(library.save_to_library_track, spotify),
        partial(contains, client),
    )


def contains(client: Catalog, identifier: str) -> object:
    return client.current_user_saved_albums_contains([identifier])[0]


def check(
    memory: Memory,
    client: Catalog,
    decisions: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
) -> bool:
    return control.check(
        decisions,
        albums,
        partial(control.unevaluated, echo=print),
        partial(control.evaluate, contains=partial(contains, client), echo=print),
        partial(control.reconcile, save=partial(memory.write, "save_albums")),
        partial(memory.write, "save_control"),
        print,
    )


def statistics(
    memory: Memory,
    decisions: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
) -> bool:
    return control.update_statistics(
        decisions,
        albums,
        partial(control.calculate, echo=print),
        partial(memory.write, "save_stats"),
        print,
    )


def tracks(client: Catalog, album: SimplifiedAlbum) -> list[SimplifiedTrack]:
    deps = TrackRead(
        cast(Callable[[str], Page], client.album_tracks),
        cast(Callable[[Page], Page], client.next),
        records.track_rows,
        records.sort_tracks,
        records.validate_tracks,
    )
    return refresh.tracks(deps, album, print)


def append(client: Catalog, values: list[SimplifiedTrack], identifier: str) -> None:
    refresh.append_tracks(
        values, identifier, client.playlist_add_items, client.playlist_add_items, print
    )


def create(client: Catalog, name: str) -> object:
    return client.user_playlist_create("12161013970", name=name)


def add_monthly(
    memory: Memory,
    client: Catalog,
    decisions: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    index: int,
) -> bool:
    clock = PlaylistClock(FixedDatetime.now, partial(create, client))
    deps = MonthlyPlaylist(
        old_total.get_months_items,
        partial(refresh.playlist, clock, print),
        partial(tracks, client),
        partial(append, client),
        partial(memory.write, "save_control"),
    )
    return refresh.add_monthly(deps, decisions, albums, index, print, LegacyFailure)


def saved(client: Catalog, offset: int) -> Page:
    return cast(
        Page,
        client.current_user_saved_albums(limit=old_total.settings.limit, offset=offset),
    )


def run(scenario: Scenario, memory: Memory, client: Catalog) -> object:
    """Execute direct application stages against the original observations.

    Args:
        scenario: Original input and interruption.
        memory: Synthetic mutable file authority.
        client: Synthetic SDK boundary.

    Returns:
        Original complete workflow result.
    """
    if scenario.workflow in ("update", "incremental"):
        deps = AlbumRefresh(
            partial(saved, client),
            partial(saved, client),
            cast(Callable[[Page], Page], client.next),
            records.saved_albums,
            memory.read_albums,
            partial(memory.write, "save_albums"),
            limit,
        )
        return refresh.refresh(
            deps, scenario.workflow == "incremental", print, LegacyFailure
        )
    if scenario.workflow == "monthly":
        actions = MonthlyActions(
            partial(check, memory, client),
            partial(statistics, memory),
            partial(control.starting_index, echo=print),
            partial(add_monthly, memory, client),
        )
        monthly.run(files(memory), actions, print)
        return None
    if scenario.workflow == "control":
        return check(memory, client, memory.control, memory.albums)
    if scenario.workflow == "stats":
        return statistics(memory, memory.control, memory.albums)
    return other_run(scenario, memory, client)


def limit() -> int:
    return old_total.settings.limit


def other_run(scenario: Scenario, memory: Memory, client: Catalog) -> object:
    if scenario.workflow == "convert":
        conversion.convert(files(memory), catalog(client), print)
        return None
    if scenario.workflow == "analyse":
        conversion.analyse(
            files(memory), partial(contains, client), partial(contains, client), print
        )
        return None
    if scenario.workflow == "restore":
        conversion.restore(files(memory), catalog(client), print)
        return None
    if scenario.workflow == "compare":
        conversion.compare(
            files(memory),
            partial(
                conversion.compare_ids,
                enrich=comparison.enrich_id_to_album_dict,
                echo=print,
            ),
        )
        return None
    return monthly.count_artists(memory.read_export)
