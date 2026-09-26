"""Typed refill ports with independent live membership and durable checkpoints."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotify_manager.application.new_wine_values import CellarRefillResult
from spotify_manager.application.wine_cellar import Inventory
from spotify_manager.application.wine_cellar import LibraryCounts
from spotify_manager.domain.catalog import PlaylistTrack


@dataclass
class MemoryCellar:
    """Model playlist writes and checkpoint acceptance without files or Spotify.

    Args:
        playlists: Current marker lists keyed by source/destination identifier.
        stored: Last accepted complete namespace checkpoint.
        eligibility: Scripted counts keyed by normalized artist name.
        events: Ordered observations and effects.
        audits: Accepted result records.
        failure: Boundary to interrupt once.
        accepted: Whether interruption occurs after accepting the effect.
        occurrence: Which boundary invocation to interrupt.
        calls: Boundary invocation counters.
    """

    playlists: dict[str, list[PlaylistTrack]]
    stored: dict[str, object] = field(default_factory=dict)
    eligibility: dict[str, LibraryCounts] = field(default_factory=dict)
    events: list[tuple[str, object]] = field(default_factory=list)
    audits: list[CellarRefillResult] = field(default_factory=list)
    failure: str | None = None
    accepted: bool = False
    occurrence: int = 1
    calls: dict[str, int] = field(default_factory=dict)

    def _before(self, name: str, value: object = None) -> None:
        self.events.append((name, deepcopy(value)))
        self.calls[name] = self.calls.get(name, 0) + 1
        self._fault(name, False)

    def _fault(self, name: str, accepted: bool) -> None:
        if (name, accepted, self.calls.get(name)) != (
            self.failure,
            self.accepted,
            self.occurrence,
        ):
            return
        self.failure = None
        raise RuntimeError(f"{name} interrupted")

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read ordered live markers.

        Args:
            playlist_id: Source or destination identifier.

        Returns:
            Current ordered markers.
        """
        self._before("playlist", playlist_id)
        return tuple(self.playlists[playlist_id])

    def inventory(self) -> Inventory:
        """Record the point at which mirror inventory is requested.

        Returns:
            Empty maps; scripted counts are supplied independently.
        """
        self._before("inventory")
        return {}, {}

    def counts(self, artist: str, inventory: Inventory) -> LibraryCounts:
        """Read scripted live affinity counts.

        Args:
            artist: Original primary artist name.
            inventory: Previously observed candidate maps.

        Returns:
            Scripted counts, defaulting to no affinity.
        """
        self._before("counts", artist)
        return self.eligibility.get(artist.strip().casefold(), (0, 0, False))

    def append(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Accept a destination marker before removing its source.

        Args:
            playlist_id: New Wine destination.
            source: Original cellar marker.

        Raises:
            RuntimeError: A scripted failure occurs before or after acceptance.
        """
        self._before("append", source.spotify_id)
        self.playlists[playlist_id].append(source)
        self._fault("append", True)

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Accept removal of matching source markers.

        Args:
            playlist_id: Wine Cellar source.
            source: Original marker.

        Raises:
            RuntimeError: A scripted failure occurs before or after acceptance.
        """
        self._before("remove", source.spotify_id)
        remaining = []
        for track in self.playlists[playlist_id]:
            if track.spotify_id != source.spotify_id:
                remaining.append(track)
        self.playlists[playlist_id] = remaining
        self._fault("remove", True)

    def save(self, state: dict[str, object]) -> None:
        """Accept a detached namespace snapshot.

        Args:
            state: Complete working namespace.

        Raises:
            RuntimeError: A scripted failure occurs before or after acceptance.
        """
        self._before("save", state)
        self.stored = deepcopy(state)
        self._fault("save", True)

    def audit(self, run_id: str, result: CellarRefillResult) -> None:
        """Accept one refill audit record.

        Args:
            run_id: Original run identifier.
            result: Refill outcome.

        Raises:
            RuntimeError: A scripted failure occurs before or after acceptance.
        """
        self._before("audit", (run_id, result))
        self.audits.append(result)
        self._fault("audit", True)

    def source(self, raw: object) -> PlaylistTrack:
        """Recover the original marker by ID from either simulated playlist.

        Args:
            raw: Serialized pending source record.

        Returns:
            The original marker value.

        Raises:
            AssertionError: Neither playlist has the pending source.
        """
        self._before("source", raw)
        spotify_id = cast(dict[str, object], raw)["spotify_id"]
        tracks = self.playlists["cellar"] + self.playlists["new"]
        for track in tracks:
            if track.spotify_id == spotify_id:
                return track
        raise AssertionError("Unknown pending source")

    def moved(self, source: PlaylistTrack, duplicate: bool, dry_run: bool) -> None:
        """Observe transfer presentation before the pending checkpoint is cleared.

        Args:
            source: Original marker.
            duplicate: Whether the destination already contained it.
            dry_run: Whether effects were previewed.
        """
        self._before("moved", (source.spotify_id, duplicate, dry_run))
