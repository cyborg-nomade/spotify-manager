"""Gather ordered candidates before optional auxiliary markers."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography_queues import marker_groups
from spotify_manager.domain.discography_queues import queue_artists
from spotify_manager.domain.discography_values import QUEUE_ORDER
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName


@dataclass(frozen=True)
class DiscographyQueues:
    """Bind complete playlist facts and original source configuration.

    Args:
        read: Original checked and retried playlist reader.
        playlists: Original source identities.
        extra: Original optional auxiliary marker source.
    """

    read: Callable[[str], tuple[PlaylistTrack, ...]]
    playlists: dict[QueueName, str]
    extra: str | None

    def run(
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
            tracks = self.read(playlist)
            queues[queue] = queue_artists(tracks, queue)
            _retain(markers, marker_groups(tracks, queue, playlist))
        if self.extra is not None:
            tracks = self.read(self.extra)
            _retain(markers, marker_groups(tracks, "queue_3", self.extra))
        result = {identity: tuple(groups) for identity, groups in markers.items()}
        return queues, result


def _retain(
    groups: dict[str, list[ArtistMarkers]], observed: dict[str, ArtistMarkers]
) -> None:
    for identity, markers in observed.items():
        groups[identity].append(markers)
