"""Assemble lookup stages independently of production composition."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from spotify_manager.application import library_lookup_run as workflow
from spotify_manager.application import lookup_resolution as resolution
from spotify_manager.application.lookup_effects import ArtistLookup
from spotify_manager.application.lookup_effects import LocalAlbumLookup
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.scrobble_lookup_run import TrackHistoryLookup
from spotify_manager.application.scrobble_lookup_run import status
from spotify_manager.domain.lookup_selection import local_album
from spotify_manager.infrastructure import lookup_records as records
from spotify_manager.infrastructure import scrobble_lookup as history
from spotify_manager.infrastructure.lookup_resources import SpotifyAlbumLookup
from spotify_manager.infrastructure.lookup_resources import SpotifyArtistLookup
from spotify_manager.infrastructure.lookup_resources import SpotifyTrackLookup
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors import library_lookups as library
from spotify_manager.processors import scrobble_lookups as scrobbles
from tests.support.library_lookup_run import LookupCatalog
from tests.support.library_lookup_run import LookupScenario


async def run_lookup(scenario: LookupScenario, catalog: LookupCatalog) -> object:
    """Run extracted workflows against explicit recorded boundaries.

    Args:
        scenario: Frozen original workflow and response profile.
        catalog: Recorded external SDK boundary.

    Returns:
        Original result without calling a public routine coordinator.
    """
    spotify = cast(Spotify, catalog)
    artist = SpotifyArtistLookup(spotify)
    if scenario.workflow == "artist-id":
        return await resolution.artist(artist, None, "artist")
    if scenario.workflow == "artist-name":
        return await resolution.artist(artist, " Artist ", None)
    if scenario.workflow == "artist-stats":
        return await artist_statistics(artist, spotify)
    if scenario.workflow.startswith("album-"):
        return await resolve_album(scenario, spotify)
    return await other_lookup(scenario, catalog)


async def artist_candidates(spotify: Spotify, name: str) -> list[tuple[str, str]]:
    """Parse external artist candidates without production composition.

    Args:
        spotify: Recorded SDK boundary.
        name: Original reference.

    Returns:
        Parsed candidates in encounter order.
    """
    return records.artist_identities(await library._artist_search_items(spotify, name))


async def artist_statistics(deps: ArtistLookup, spotify: Spotify) -> object:
    """Inject every ordered artist statistics stage.

    Args:
        deps: Direct and name lookup observations.
        spotify: Recorded SDK boundary.

    Returns:
        Original statistics response.
    """
    return await workflow.artist_statistics(
        workflow.ArtistStatistics(SpotifyArtistLookup(spotify), "Artist", None, 20)
    )


async def resolve_album(scenario: LookupScenario, spotify: Spotify) -> object:
    """Resolve album metadata with explicitly supplied catalog observations.

    Args:
        scenario: Original direct or search reference.
        spotify: Recorded SDK boundary.

    Returns:
        Original album identity.
    """
    deps = SpotifyAlbumLookup(spotify)
    if scenario.workflow == "album-id":
        return await resolution.album(deps, None, "album", None)
    return await resolution.album(deps, " Album ", None, None)


async def cached_tracks(catalog: LookupCatalog) -> tuple[list[LookupTrack], bool]:
    """Supply cache authority separately from the catalog fetch.

    Args:
        catalog: Recorded SDK and cache boundary.

    Returns:
        Original track rows and cache flag.
    """
    deps = MemoryTrackCache(catalog)
    return await workflow.tracklist(deps, "album", True, False)


async def local_tracks(
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
    return await cached_tracks(catalog)


async def other_lookup(scenario: LookupScenario, catalog: LookupCatalog) -> object:
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
            MemoryLibrary(catalog), MemoryTrackCache(catalog), True, False
        )
        return await workflow.evaluate_local(deps, "Album", None, None, None, 0.5)
    if scenario.workflow == "tracklist":
        return await cached_tracks(catalog)
    return await track_lookup(scenario, cast(Spotify, catalog), catalog)


async def track_candidates(
    spotify: Spotify, name: str
) -> list[scrobbles.ResolvedTrack]:
    """Parse original track search observations.

    Args:
        spotify: Recorded SDK boundary.
        name: Original track reference.

    Returns:
        Original complete candidates.
    """
    return records.track_identities(await scrobbles._track_search(spotify, name))


def fixed_now() -> datetime:
    """Observe the fixed original clock.

    Returns:
        Original UTC instant.
    """
    return datetime(2026, 9, 24, tzinfo=UTC)


async def track_lookup(
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
    deps = SpotifyTrackLookup(spotify)
    if scenario.workflow == "track-id":
        return await resolution.track(deps, None, "track")
    if scenario.workflow == "track-name":
        return await resolution.track(deps, "Track", None)
    timezone = ZoneInfo("Europe/Berlin")
    return await status(
        TrackHistoryLookup(
            deps,
            MemoryHistory(catalog),
            "Track",
            None,
            FixedClock(),
            timezone,
        )
    )


@dataclass(frozen=True)
class MemoryTrackCache:
    """Observe cache storage and track reads independently of bootstrap.

    Args:
        catalog: Recorded SDK and memory authority.
    """

    catalog: LookupCatalog

    async def load(self) -> dict[str, list[LookupTrack]]:
        """Read recorded cache facts.

        Returns:
            Complete cache.
        """
        return self.catalog.memory.read_cache()

    async def save(self, cache: dict[str, list[LookupTrack]]) -> None:
        """Accept recorded cache facts.

        Args:
            cache: Complete cache.
        """
        self.catalog.memory.save_cache(cache)

    async def fetch(self, identifier: str) -> list[LookupTrack]:
        """Read every track through the original SDK boundary.

        Args:
            identifier: Requested album.

        Returns:
            Complete minimized tracks.
        """
        return await library._async_fetch_album_tracks(
            cast(Spotify, self.catalog), identifier
        )


@dataclass(frozen=True)
class MemoryLibrary:
    """Read a recorded export.

    Args:
        catalog: Recorded memory authority.
    """

    catalog: LookupCatalog

    async def library(self) -> YourLibraryFile:
        """Read local authority.

        Returns:
            Complete export.
        """
        return self.catalog.memory.read_library()


@dataclass(frozen=True)
class MemoryHistory:
    """Read recorded history through the original parser.

    Args:
        catalog: Recorded memory authority.
    """

    catalog: LookupCatalog

    async def latest(self, track: str, artist: str) -> datetime | None:
        """Observe the latest matching play.

        Args:
            track: Resolved title.
            artist: Resolved primary artist.

        Returns:
            Latest play time, or none.
        """
        payload = self.catalog.memory.history(Path("/tmp/history.json"))
        return history.latest_from_export(
            payload, track, artist, ZoneInfo("Europe/Berlin")
        )


class FixedClock:
    """Observe the frozen clock after history."""

    def now(self) -> datetime:
        """Observe effective time.

        Returns:
            Original frozen instant.
        """
        return fixed_now()
