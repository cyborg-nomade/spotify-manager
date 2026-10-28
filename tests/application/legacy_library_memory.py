"""Construct named external resources independently of production bootstrap."""

from dataclasses import dataclass
from typing import cast

from spotify_manager.application import legacy_library_control as control
from spotify_manager.application import legacy_library_conversion as conversion
from spotify_manager.application import legacy_library_monthly as monthly
from spotify_manager.application import legacy_library_refresh as refresh
from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import LegacyFiles
from spotify_manager.application.legacy_library_effects import MonthlyActions
from spotify_manager.application.legacy_library_effects import MonthlyPlaylist
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.legacy_library_resources import LegacyMonthlyLimits
from spotify_manager.infrastructure.legacy_library_resources import (
    NativeComparisonMetadata,
)
from spotify_manager.infrastructure.legacy_library_resources import SpotifyAlbumRefresh
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyControlMembership,
)
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyConversionCatalog,
)
from spotify_manager.infrastructure.legacy_library_resources import SpotifyPlaylistClock
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyPlaylistWrites,
)
from spotify_manager.infrastructure.legacy_library_resources import SpotifyTrackRead
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.your_library import YourLibraryFile
from tests.support.legacy_library_run import Catalog
from tests.support.legacy_library_run import Memory
from tests.support.legacy_library_run import MemoryComparisonClients
from tests.support.legacy_library_run import Scenario


@dataclass(frozen=True)
class MemoryFiles:
    """Observe complete file reads and accepted writes.

    Args:
        memory: Recorded file authority.
    """

    memory: Memory

    async def albums(self) -> list[SimplifiedAlbum]:
        """Observe albums at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.memory.read_albums()

    async def control(self) -> list[ControlFileItem]:
        """Observe control at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.memory.read_control()

    async def export(self) -> YourLibraryFile:
        """Observe export at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.memory.read_export()

    async def comparison(self) -> Comparison:
        """Observe comparison at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return cast(Comparison, self.memory.read_comparison())

    async def save_albums(self, albums: list[SimplifiedAlbum]) -> None:
        """Observe save albums at the recorded boundary.

        Args:
            albums: Complete saved-album models.
        """
        self.memory.write("save_albums", albums)

    async def save_control(self, control: list[ControlFileItem]) -> None:
        """Observe save control at the recorded boundary.

        Args:
            control: Complete accepted control-file values.
        """
        self.memory.write("save_control", control)

    async def save_stats(self, stats: StatsFileItem) -> None:
        """Observe save stats at the recorded boundary.

        Args:
            stats: Accepted statistics model.
        """
        self.memory.write("save_stats", stats)

    async def save_comparison(self, comparison: Comparison) -> None:
        """Observe save comparison at the recorded boundary.

        Args:
            comparison: Complete comparison result.
        """
        self.memory.write("save_comparison", comparison)


@dataclass(frozen=True)
class MemoryAlbumRefresh(SpotifyAlbumRefresh):
    """Read recorded SDK pages while keeping file authority in memory.

    Args:
        spotify: Recorded SDK client.
        memory: Recorded file authority.
    """

    memory: Memory

    async def load(self) -> list[SimplifiedAlbum]:
        """Observe load at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.memory.read_albums()

    async def save(self, albums: list[SimplifiedAlbum]) -> None:
        """Observe save at the recorded boundary.

        Args:
            albums: Complete saved-album models.
        """
        self.memory.write("save_albums", albums)


def files(memory: Memory) -> LegacyFiles:
    """Observe files at the recorded boundary.

    Args:
        memory: Recorded inputs and accepted file or remote effects.

    Returns:
        Recorded boundary result.
    """
    return MemoryFiles(memory)


def catalog(client: Catalog) -> SpotifyConversionCatalog:
    """Observe catalog at the recorded boundary.

    Args:
        client: Recorded caller-owned transport.

    Returns:
        Recorded boundary result.
    """
    return SpotifyConversionCatalog(cast(Spotify, client))


async def check(
    memory: Memory,
    client: Catalog,
    decisions: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
) -> bool:
    """Observe check at the recorded boundary.

    Args:
        memory: Recorded inputs and accepted file or remote effects.
        client: Recorded caller-owned transport.
        decisions: Original control-file decisions.
        albums: Complete saved-album models.

    Returns:
        Recorded boundary result.
    """
    return await control.check(
        decisions,
        albums,
        SpotifyControlMembership(cast(Spotify, client)),
        files(memory),
        STANDARD_OUTPUT,
    )


async def statistics(
    memory: Memory, decisions: list[ControlFileItem], albums: list[SimplifiedAlbum]
) -> bool:
    """Observe statistics at the recorded boundary.

    Args:
        memory: Recorded inputs and accepted file or remote effects.
        decisions: Original control-file decisions.
        albums: Complete saved-album models.

    Returns:
        Recorded boundary result.
    """
    return await control.update_statistics(
        decisions, albums, files(memory), STANDARD_OUTPUT
    )


def playlist(memory: Memory, client: Catalog) -> MonthlyPlaylist:
    """Observe playlist at the recorded boundary.

    Args:
        memory: Recorded inputs and accepted file or remote effects.
        client: Recorded caller-owned transport.

    Returns:
        Recorded boundary result.
    """
    spotify = cast(Spotify, client)
    return MonthlyPlaylist(
        SpotifyPlaylistClock(spotify),
        SpotifyTrackRead(spotify),
        SpotifyPlaylistWrites(spotify),
        files(memory),
        LegacyMonthlyLimits(),
    )


async def run(scenario: Scenario, memory: Memory, client: Catalog) -> object:
    """Run direct application stages with the original recorded authorities.

    Args:
        scenario: Original inputs and interruption.
        memory: Synthetic file authority.
        client: Synthetic SDK authority.

    Returns:
        Original complete workflow result.
    """
    if scenario.workflow in ("update", "incremental"):
        deps = MemoryAlbumRefresh(cast(Spotify, client), memory)
        return await refresh.refresh(
            deps, scenario.workflow == "incremental", STANDARD_OUTPUT
        )
    if scenario.workflow == "monthly":
        actions = MonthlyActions(
            SpotifyControlMembership(cast(Spotify, client)), playlist(memory, client)
        )
        (await monthly.run(files(memory), actions, STANDARD_OUTPUT))
        return None
    if scenario.workflow == "control":
        return await check(memory, client, memory.control, memory.albums)
    if scenario.workflow == "stats":
        return await statistics(memory, memory.control, memory.albums)
    return await other_run(scenario, memory, client)


async def other_run(scenario: Scenario, memory: Memory, client: Catalog) -> object:
    """Observe other run at the recorded boundary.

    Args:
        scenario: Scenario supplied by this fixture.
        memory: Recorded inputs and accepted file or remote effects.
        client: Recorded caller-owned transport.

    Returns:
        Recorded boundary result.
    """
    if scenario.workflow == "convert":
        (await conversion.convert(files(memory), catalog(client), STANDARD_OUTPUT))
        return None
    if scenario.workflow == "analyse":
        (await conversion.analyse(files(memory), catalog(client), STANDARD_OUTPUT))
        return None
    if scenario.workflow == "restore":
        (await conversion.restore(files(memory), catalog(client), STANDARD_OUTPUT))
        return None
    if scenario.workflow == "compare":
        (
            await conversion.compare(
                files(memory),
                NativeComparisonMetadata(MemoryComparisonClients(client)),
                STANDARD_OUTPUT,
            )
        )
        return None
    return await monthly.count_artists(files(memory))
