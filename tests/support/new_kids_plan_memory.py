"""Stateful plan interactions and transfer acknowledgements without external I/O."""

from copy import deepcopy

from spotify_manager.application.ports.new_kids_plans import ReleasePlanDraft
from spotify_manager.application.ports.new_kids_plans import ReleasePlanSubmission
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.discovery_memory import MemoryDiscovery


class PlanMemory(MemoryDiscovery):
    """Record plan decisions, durable snapshots and actual simulated membership."""

    def __init__(self) -> None:
        """Create independent state and empty scripted operator responses."""
        super().__init__()
        self.answers: list[ReleasePlanSubmission] = []
        self.drafts: list[ReleasePlanDraft] = []
        self.persisted: dict[str, object] = {"artists": {}, "composer_routes": {}}
        self.snapshots: list[dict[str, object]] = []
        self.fail_at: str | None = None

    async def choose_plan(self, draft: ReleasePlanDraft) -> ReleasePlanSubmission:
        """Read one scripted ordered decision.

        Args:
            draft: Offered complete catalogue.

        Returns:
            Next scripted response, otherwise the first four explicitly selected.
        """
        self.drafts.append(draft)
        self.events.append(("plan_choice", draft))
        if self.answers:
            return self.answers.pop(0)
        ids = tuple(release.spotify_id for release in draft.releases[:4])
        return ReleasePlanSubmission("select", ids, len(ids) < 4)

    async def save(
        self, value: dict[str, object], *, message: str | None = None
    ) -> None:
        """Acknowledge a durable checkpoint, optionally failing beforehand.

        Args:
            value: Complete namespace to save.
            message: Optional existing checkpoint description.
        """
        self._fail("save")
        self.persisted = deepcopy(value)
        self.snapshots.append(deepcopy(value))
        self.events.append(("save", deepcopy(value)))

    async def load(self) -> dict[str, object]:
        """Reload the last acknowledged namespace.

        Returns:
            Independent durable snapshot.
        """
        return deepcopy(self.persisted)

    async def append(
        self, playlist_id: str, source: PlaylistTrack, description: str
    ) -> None:
        """Accept an append, including an optional lost acknowledgement.

        Args:
            playlist_id: Destination playlist.
            source: Pinned first marker.
            description: Effect context.
        """
        self._fail("append")
        self.playlists[playlist_id] = (*self.playlists.get(playlist_id, ()), source)
        self.events.append(("append", (playlist_id, source.spotify_id)))
        self._fail("append_ack")

    async def remove(
        self, playlist_id: str, source: PlaylistTrack, description: str
    ) -> None:
        """Accept removal, including an optional lost acknowledgement.

        Args:
            playlist_id: Queue source.
            source: Original source marker.
            description: Effect context.
        """
        self._fail("remove")
        remaining = []
        for marker in self.playlists.get(playlist_id, ()):
            if marker.spotify_id != source.spotify_id:
                remaining.append(marker)
        self.playlists[playlist_id] = tuple(remaining)
        self.events.append(("remove", (playlist_id, source.spotify_id)))
        self._fail("remove_ack")

    def moved(self, artist: str, dry_run: bool) -> None:
        """Record accepted transfer presentation.

        Args:
            artist: Logical display name.
            dry_run: Whether membership was projected.
        """
        self.events.append(("moved", (artist, dry_run)))

    def _fail(self, boundary: str) -> None:
        if self.fail_at == boundary:
            self.fail_at = None
            raise OSError(boundary)
