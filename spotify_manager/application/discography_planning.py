"""Coordinate lazy Discography reads, cached choices and round-week packing."""

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol
from typing import cast

from spotify_manager.application.discography_catalog import DiscographyCatalog
from spotify_manager.application.discography_history import DiscographyArtistMapping
from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.discography_queues import DiscographyQueues
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.discography_batches import next_queue
from spotify_manager.domain.discography_batches import next_start_queue
from spotify_manager.domain.discography_batches import queue_cycle
from spotify_manager.domain.discography_batches import removal_markers
from spotify_manager.domain.discography_batches import selected_releases
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import ArtistSelection
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import DiscographyPlan
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName


class ReleaseSelector(Protocol):
    """Own the operator interaction for select releases."""

    async def select_releases(
        self, artist: QueueArtist, releases: tuple[CatalogRelease, ...], /
    ) -> tuple[str, ...]:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            releases: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class PriorityState(Protocol):
    """Read the current original discography priority namespace."""

    async def load(self) -> dict[str, object]:
        """Return the complete original priority state before queue observations.

        Returns:
            Original complete priority namespace retaining unknown fields.
        """


@dataclass(frozen=True)
class DiscographyReads:
    """Bind original complete facts, interaction and progress boundaries.

    Args:
        state: Original preflight priority read.
        queues: Original ordered queue and marker gathering.
        history: Original lazily requested historical artist facts.
        mapping: Named historical artist-mapping stage.
        catalog: Original complete catalog reader.
        choose: Original release-selection interaction.
        progress: Original optional stage presenter.
    """

    state: PriorityState
    queues: DiscographyQueues
    history: DiscographyHistory
    mapping: DiscographyArtistMapping
    catalog: DiscographyCatalog
    choose: ReleaseSelector
    progress: Messages


@dataclass
class DiscographyPlanning:
    """Retain original run-scoped caches and global accepted/declined identities.

    Args:
        reads: Original caller-owned facts and interaction.
        week_releases: Original week packing size.
        queues: Original gathered candidates, including lazy fallback replacement.
        markers: Original gathered complete marker groups.
        catalogs: Original canonical cache, retaining empty hits.
        choices: Original interactive cache, retaining empty hits.
        selected: Original globally accepted identities.
        declined: Original globally declined identities.
        memory_loaded: Whether Memory Lane authority has been gathered.
    """

    reads: DiscographyReads
    week_releases: int = 10
    queues: dict[QueueName, tuple[QueueArtist, ...]] = field(default_factory=dict)
    markers: dict[str, tuple[ArtistMarkers, ...]] = field(default_factory=dict)
    catalogs: dict[str, tuple[CatalogRelease, ...]] = field(default_factory=dict)
    choices: dict[str, tuple[CatalogRelease, ...]] = field(default_factory=dict)
    selected: set[str] = field(default_factory=set)
    declined: set[str] = field(default_factory=set)
    memory_loaded: bool = False

    async def run(self) -> DiscographyPlan:
        """Read priority first and select the original round-week batch without writes.

        Returns:
            Original complete plan, preserving lazy reads and catalog choice order.

        Raises:
            DiscographyError: An original fact or interactive choice is invalid.
        """
        start = cast(QueueName, (await self.reads.state.load())["next_queue"])
        self.reads.progress.echo("Loading discography artist queues")
        self.queues, self.markers = await self.reads.queues.run()
        self.memory_loaded = bool(self.queues["memory_lane"])
        first = await self._find(start, None)
        if first is None:
            return DiscographyPlan(start, start, (), 0, 0)
        return await self._pack(start, first)

    async def _pack(self, start: QueueName, first: ArtistSelection) -> DiscographyPlan:
        artists = [first]
        self.selected.add(first.spotify_id)
        total = first.release_count
        last_queue = first.source_queue
        while (remaining := (-total) % self.week_releases) != 0:
            match = await self._find(next_queue(last_queue), remaining)
            if match is None:
                break
            artists.append(match)
            self.selected.add(match.spotify_id)
            total += match.release_count
            last_queue = match.source_queue
        return DiscographyPlan(
            start,
            next_start_queue(start),
            tuple(artists),
            total,
            (-total) % self.week_releases,
        )

    async def _find(
        self, start: QueueName, remaining: int | None
    ) -> ArtistSelection | None:
        for queue in queue_cycle(start):
            match = await self._find_in_queue(
                (await self._candidates(queue)), remaining
            )
            if match is not None:
                return match
        return None

    async def _find_in_queue(
        self,
        candidates: tuple[QueueArtist, ...],
        remaining: int | None,
    ) -> ArtistSelection | None:
        for candidate in candidates:
            if candidate.spotify_id in self.selected | self.declined:
                continue
            if remaining is not None and not (await self._fits(candidate, remaining)):
                continue
            releases = await self._choose(candidate)
            if not releases:
                self.declined.add(candidate.spotify_id)
                continue
            markers = removal_markers(self.markers.get(candidate.spotify_id, ()))
            return ArtistSelection(
                candidate.spotify_id, candidate.name, candidate.queue, releases, markers
            )
        return None

    async def _candidates(self, queue: QueueName) -> tuple[QueueArtist, ...]:
        if queue != "memory_lane" or self.memory_loaded:
            return self.queues[queue]
        selection = await self.reads.history.run()
        self.reads.progress.echo(
            f"Random.org selected {selection.selected_date.isoformat()}; "
            f"second {selection.generated_at.second} chose "
            f"{selection.artist.name} ({selection.position} of "
            f"{selection.artists_on_date} artists)"
        )
        candidate = await self.reads.mapping.resolve(selection)
        self.queues["memory_lane"] = (candidate,)
        self.memory_loaded = True
        return self.queues["memory_lane"]

    async def _catalog(self, candidate: QueueArtist) -> tuple[CatalogRelease, ...]:
        cached = self.catalogs.get(candidate.spotify_id)
        if cached is not None:
            return cached
        self.reads.progress.echo(f"Loading {candidate.name}'s release catalog")
        catalog = await self.reads.catalog.run(candidate.spotify_id)
        self.catalogs[candidate.spotify_id] = catalog
        return catalog

    async def _choose(self, candidate: QueueArtist) -> tuple[CatalogRelease, ...]:
        cached = self.choices.get(candidate.spotify_id)
        if cached is not None:
            return cached
        catalog = await self._catalog(candidate)
        identities = await self.reads.choose.select_releases(candidate, catalog)
        releases = selected_releases(catalog, identities)
        if releases is None:
            raise DiscographyError(
                f"Release selection for {candidate.name} was not valid."
            )
        self.choices[candidate.spotify_id] = releases
        return releases

    async def _fits(self, candidate: QueueArtist, remaining: int) -> bool:
        defaults = sum(release.default for release in (await self._catalog(candidate)))
        return 0 < defaults <= remaining
