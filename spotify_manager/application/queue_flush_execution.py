"""Execute original Queue plans while preserving destination-before-removal order."""

from dataclasses import dataclass

from spotify_manager.application.queue_flush_effects import QueueFlushEffects
from spotify_manager.application.queue_flush_values import QueueFlushFacts
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.queue_flush import removable_sources
from spotify_manager.domain.queue_flush import remove_membership


@dataclass(frozen=True)
class QueueFlushExecution:
    """Preserve accepted writes and local membership across partial failures.

    Args:
        effects: Original accepted-effect and presentation boundaries.
        facts: Caller-owned initial observations and evolving membership sets.
        preview: Original preview behavior.
    """

    effects: QueueFlushEffects
    facts: QueueFlushFacts
    preview: bool

    async def run(self, source: PlaylistTrack, plan: dict[str, object]) -> None:
        """Execute one original plan before constructing its completion result.

        Args:
            source: Original authoritative source marker.
            plan: Original authoritative cached or newly accepted plan.

        Raises:
            QueueStateError: Original stored source URIs are malformed.
        """
        action = str(plan.get("action") or "")
        target = self.effects.decode_target(plan.get("target"))
        raw_uris = plan.get("source_uris")
        if not isinstance(raw_uris, list):
            raise QueueStateError("Queue plan has invalid source URIs.")
        uris = [str(uri) for uri in raw_uris]
        await self._destination(action, source, target)
        if action in {"unlucky", "unfollow"}:
            await self._unfollow(source)
        if action == "blocked":
            return
        removable = removable_sources(uris, self.facts.live_uris, action, target)
        if removable and not self.preview:
            await self.effects.remove(source, removable)
        remove_membership(
            self.facts.tracks, removable, self.facts.live_ids, self.facts.live_uris
        )

    async def _destination(
        self,
        action: str,
        source: PlaylistTrack,
        target: CatalogTrack | None,
    ) -> None:
        if target is None:
            return
        if action == "advance":
            await self._advance(source, target)
        elif action == "promote":
            await self._promote(source, target)
        elif action == "unlucky":
            await self._unlucky(source, target)

    async def _advance(self, source: PlaylistTrack, target: CatalogTrack) -> None:
        if target.spotify_id not in self.facts.live_ids and not self.preview:
            await self.effects.append("queue", source, target)
        self.facts.live_ids.add(target.spotify_id)
        self.facts.live_uris.add(target.uri)
        self.effects.present("advance", source, target, self.preview)

    async def _promote(self, source: PlaylistTrack, target: CatalogTrack) -> None:
        if source.primary_artist_id not in self.facts.queue_2_artists:
            if not self.preview:
                await self.effects.append("queue2", source, target)
            self.facts.queue_2_artists.add(source.primary_artist_id)
        self.effects.present("promote", source, target, self.preview)

    async def _unlucky(self, source: PlaylistTrack, target: CatalogTrack) -> None:
        if source.primary_artist_id not in self.facts.unlucky_artists:
            if not self.preview:
                await self.effects.append("unlucky", source, target)
            self.facts.unlucky_artists.add(source.primary_artist_id)
        self.effects.present("unlucky", source, target, self.preview)

    async def _unfollow(self, source: PlaylistTrack) -> None:
        if not (await self.effects.following(source)):
            return
        if not self.preview:
            await self.effects.unfollow(source)
            await self.effects.remove_local(source)
        self.effects.present("unfollow", source, None, self.preview)
