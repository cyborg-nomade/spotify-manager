"""Gather ordered candidates before optional auxiliary markers."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography_queues import marker_groups
from spotify_manager.domain.discography_queues import queue_artists
from spotify_manager.domain.discography_values import QUEUE_ORDER
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName


class DiscographyPlaylists(Protocol):
    """Read ordered playable markers through the original playlist adapter."""

    async def read(self, playlist: str) -> tuple[PlaylistTrack, ...]:
        """Read complete current playlist observations.

        Args:
            playlist: Original playlist identity.

        Returns:
            Playable markers in original order.
        """


@dataclass(frozen=True)
class DiscographyQueues:
    """Bind complete playlist facts and original source configuration.

    Args:
        source: Original checked and retried playlist integration.
        playlists: Original source identities.
        extra: Original optional auxiliary marker source.
    """

    source: DiscographyPlaylists
    playlists: dict[QueueName, str]
    extra: str | None

    async def run(
        self,
    ) -> tuple[
        dict[QueueName, tuple[QueueArtist, ...]],
        dict[str, tuple[ArtistMarkers, ...]],
    ]:
        """Read every source in queue order, then optional Queue 3 markers.

        Returns:
            Original complete candidate queues and matching marker groups.
        """
        queues = {}
        markers: dict[str, list[ArtistMarkers]] = defaultdict(list)
        for queue in QUEUE_ORDER:
            playlist = self.playlists[queue]
            tracks = await self.source.read(playlist)
            queues[queue] = queue_artists(tracks, queue)
            _retain(markers, marker_groups(tracks, queue, playlist))
        if self.extra is not None:
            tracks = await self.source.read(self.extra)
            _retain(markers, marker_groups(tracks, "queue_3", self.extra))
        result = {identity: tuple(groups) for identity, groups in markers.items()}
        return queues, result


def _retain(
    groups: dict[str, list[ArtistMarkers]], observed: dict[str, ArtistMarkers]
) -> None:
    for identity, markers in observed.items():
        groups[identity].append(markers)
