"""Assemble lookup stages independently of production composition."""

from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from spotipy import Spotify

from spotify_manager.application import library_lookup_run as workflow
from spotify_manager.application import lookup_resolution as resolution
from spotify_manager.application.lookup_effects import AlbumLookup
from spotify_manager.application.lookup_effects import ArtistLookup
from spotify_manager.application.lookup_effects import CachedTracks
from spotify_manager.application.lookup_effects import LocalAlbumLookup
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.application.lookup_effects import TrackLookup
from spotify_manager.application.scrobble_lookup_run import TrackHistoryLookup
from spotify_manager.application.scrobble_lookup_run import status
from spotify_manager.domain.lookup_selection import local_album
from spotify_manager.infrastructure import lookup_records as records
from spotify_manager.infrastructure import scrobble_lookup as history
from spotify_manager.processors import library_lookups as library
from spotify_manager.processors import scrobble_lookups as scrobbles
from tests.support.library_lookup_run import LookupCatalog
from tests.support.library_lookup_run import LookupScenario


def run_lookup(scenario: LookupScenario, catalog: LookupCatalog) -> object:
    """Run extracted workflows against explicit recorded boundaries.

    Args:
        scenario: Frozen original workflow and response profile.
        catalog: Recorded external SDK boundary.

    Returns:
        Original result without calling a public routine coordinator.
    """
    spotify = cast(Spotify, catalog)
    artist = ArtistLookup(
        partial(library._direct_artist_identity, spotify),
        partial(artist_candidates, spotify),
    )
    if scenario.workflow == "artist-id":
        return resolution.artist(artist, None, "artist")
    if scenario.workflow == "artist-name":
        return resolution.artist(artist, " Artist ", None)
    if scenario.workflow == "artist-stats":
        return artist_statistics(artist, spotify)
    if scenario.workflow.startswith("album-"):
        return resolve_album(scenario, spotify)
    return other_lookup(scenario, catalog)


def artist_candidates(spotify: Spotify, name: str) -> list[tuple[str, str]]:
    """Parse external artist candidates without production composition.

    Args:
        spotify: Recorded SDK boundary.
        name: Original reference.

    Returns:
        Parsed candidates in encounter order.
    """
    return records.artist_identities(library._artist_search_items(spotify, name))


def artist_statistics(deps: ArtistLookup, spotify: Spotify) -> object:
    """Inject every ordered artist statistics stage.

    Args:
        deps: Direct and name lookup observations.
        spotify: Recorded SDK boundary.

    Returns:
        Original statistics response.
    """
    return workflow.artist_statistics(
        workflow.ArtistStatistics(
            partial(resolution.artist, deps, "Artist", None),
            partial(library._live_artist_release_ids, spotify),
            partial(
                workflow.count_contains,
                contains=partial(library._saved_artist_statuses, spotify),
                resource="Saved Albums",
                batch_size=20,
            ),
            partial(library._live_primary_track_ids, spotify),
            partial(
                workflow.count_contains,
                contains=partial(library._liked_artist_statuses, spotify),
                resource="Liked Songs",
                batch_size=20,
            ),
        )
    )


def resolve_album(scenario: LookupScenario, spotify: Spotify) -> object:
    """Resolve album metadata with explicitly supplied catalog observations.

    Args:
        scenario: Original direct or search reference.
        spotify: Recorded SDK boundary.

    Returns:
        Original album identity.
    """
    deps = AlbumLookup(
        partial(library._direct_album, spotify),
        partial(library._album_search, spotify),
    )
    if scenario.workflow == "album-id":
        return resolution.album(deps, None, "album", None)
    return resolution.album(deps, " Album ", None, None)


def cached_tracks(catalog: LookupCatalog) -> tuple[list[LookupTrack], bool]:
    """Supply cache authority separately from the catalog fetch.

    Args:
        catalog: Recorded SDK and cache boundary.

    Returns:
        Original track rows and cache flag.
    """
    deps = CachedTracks(
        catalog.memory.read_cache,
        catalog.memory.save_cache,
        partial(library._fetch_album_tracks, cast(Spotify, catalog)),
    )
    return workflow.tracklist(deps, "album", True, False)


def local_tracks(
    catalog: LookupCatalog, identifier: str
) -> tuple[list[LookupTrack], bool]:
    """Adapt the original single album fixture to an explicit track boundary.

    Args:
        catalog: Recorded SDK boundary.
        identifier: Requested original album identity.

    Returns:
        Original complete track observation.
    """
    assert identifier == "album"
    return cached_tracks(catalog)


def other_lookup(scenario: LookupScenario, catalog: LookupCatalog) -> object:
    """Inject local evaluation and history stages without routine coordinators.

    Args:
        scenario: Original workflow profile.
        catalog: Recorded SDK and local authorities.

    Returns:
        Original local or track lookup result.
    """
    if scenario.workflow == "local-album":
        return local_album(catalog.memory.read_library().albums, "Album", None, None)
    if scenario.workflow == "local-evaluate":
        deps = LocalAlbumLookup(
            catalog.memory.read_library, partial(local_tracks, catalog)
        )
        return workflow.evaluate_local(deps, "Album", None, None, None, 0.5)
    if scenario.workflow == "tracklist":
        return cached_tracks(catalog)
    return track_lookup(scenario, cast(Spotify, catalog), catalog)


def track_candidates(spotify: Spotify, name: str) -> list[scrobbles.ResolvedTrack]:
    """Parse original track search observations.

    Args:
        spotify: Recorded SDK boundary.
        name: Original track reference.

    Returns:
        Original complete candidates.
    """
    return records.track_identities(scrobbles._track_search(spotify, name))


def fixed_now() -> datetime:
    """Observe the fixed original clock.

    Returns:
        Original UTC instant.
    """
    return datetime(2026, 9, 24, tzinfo=UTC)


def track_lookup(
    scenario: LookupScenario, spotify: Spotify, catalog: LookupCatalog
) -> object:
    """Inject track resolution and latest-history observations.

    Args:
        scenario: Original direct, search or status workflow.
        spotify: Recorded SDK boundary.
        catalog: Original history authority.

    Returns:
        Original track identity or seasonal status.
    """
    deps = TrackLookup(
        partial(scrobbles._direct_track, spotify), partial(track_candidates, spotify)
    )
    if scenario.workflow == "track-id":
        return resolution.track(deps, None, "track")
    if scenario.workflow == "track-name":
        return resolution.track(deps, "Track", None)
    timezone = ZoneInfo("Europe/Berlin")
    return status(
        TrackHistoryLookup(
            partial(resolution.track, deps, "Track", None),
            partial(
                history.latest,
                catalog.memory.history,
                Path("/tmp/history.json"),
                timezone=timezone,
            ),
            fixed_now,
            timezone,
        )
    )
