"""Fill available New Wine slots with ordered, resumable Wine Cellar transfers."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import Literal
from typing import Protocol
from typing import cast

from spotify_manager.application.cellar_review import CellarReview
from spotify_manager.application.new_wine_values import CellarRefillResult
from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import NewWineError
from spotify_manager.application.ports.cellar_review import TransferChoiceReader
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.flush_mode import discovery_fallback


type Inventory = tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]
type LibraryCounts = tuple[int | None, int, bool]


class TransferPresentation(Protocol):
    """Present a completed or previewed cellar transfer."""

    def moved(self, source: PlaylistTrack, duplicate: bool, dry_run: bool) -> None:
        """Present the original transfer result before checkpoint and audit.

        Args:
            source: Original cellar marker.
            duplicate: Whether the destination already had this marker.
            dry_run: Whether the transfer was previewed.
        """
        ...

    def recovery_exhausted(self, after: int, target: int) -> None:
        """Explain why normal discovery may fill the remaining capacity.

        Args:
            after: Destination size after recovery.
            target: Maximum destination size.
        """
        ...


class CellarAccess(Protocol):
    """Observe playlists and library eligibility, then perform individual effects."""

    async def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read ordered current markers.

        Args:
            playlist_id: Source or destination to observe.

        Returns:
            Parsed playable markers in existing order.
        """

    async def inventory(self) -> Inventory:
        """Read local candidate IDs by normalized primary artist name.

        Returns:
            Liked-track and saved-album candidate maps.
        """

    async def counts(self, artist: str, inventory: Inventory) -> LibraryCounts:
        """Observe library counts until either existing eligibility threshold is met.

        Args:
            artist: Source marker's primary artist display name.
            inventory: Candidate IDs read from the canonical mirrors.

        Returns:
            Liked count (possibly omitted), saved-album count and eligibility.
        """

    async def append(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Append a source marker as a destination track.

        Args:
            playlist_id: New Wine destination.
            source: Original Wine Cellar marker.
        """

    async def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove the source after its destination marker is secure.

        Args:
            playlist_id: Wine Cellar source.
            source: Original marker to remove.
        """

    async def save(self, state: dict[str, object]) -> None:
        """Persist the complete namespace at one pending-transfer boundary.

        Args:
            state: Namespace containing the active run and pending transfer.
        """

    async def audit(self, run_id: str, result: CellarRefillResult) -> None:
        """Append a transfer or eligibility result, including previews.

        Args:
            run_id: Active run identifier.
            result: Original refill result value.
        """

    def source(self, raw: object) -> PlaylistTrack:
        """Reconstruct a legacy pending marker at its original read boundary.

        Args:
            raw: Persisted source record.

        Returns:
            Parsed original marker.
        """


@dataclass(frozen=True)
class CellarOptions:
    """Run-specific refill settings, including preview membership projections.

    Args:
        destination: New Wine playlist identifier.
        source: Wine Cellar playlist identifier.
        no_discovery: Whether to require existing library affinity.
        dry_run: Whether to preview without remote or checkpoint writes.
        target_size: Existing destination marker limit.
        projected_ids: Preview membership after the preceding flush, when supplied.
    """

    destination: str
    source: str
    no_discovery: bool
    dry_run: bool
    target_size: int = 10
    projected_ids: set[str] | None = None


@dataclass(frozen=True)
class CellarWorkflow:
    """Own the named refill stage and its invocation-owned external resources.

    Args:
        access: Original playlist, membership and persistence boundary.
        moved: Original transfer presentation resource.
        presentation: Named presenter for accepted workflow outcomes.
        reader: Optional explicit no-discovery transfer interaction.
    """

    access: CellarAccess
    presentation: TransferPresentation
    reader: TransferChoiceReader | None = None

    async def run(
        self, options: CellarOptions, state: dict[str, object], run: dict[str, object]
    ) -> CellarRefillSummary:
        """Run ordered cellar decisions and accepted transfer effects.

        Args:
            options: Effective source, destination and preview settings.
            state: Complete mutable namespace.
            run: Active run retaining pending-transfer authority.

        Returns:
            Original ordered refill results and destination counts.
        """
        return await refill_cellar(
            self.access, options, state, run, self.presentation, self.reader
        )


async def refill_cellar(
    access: CellarAccess,
    options: CellarOptions,
    state: dict[str, object],
    run: dict[str, object],
    presentation: TransferPresentation,
    reader: TransferChoiceReader | None = None,
) -> CellarRefillSummary:
    """Resume any pending transfer, then fill available slots in cellar order.

    Args:
        access: Explicit playlist, inventory, checkpoint and audit boundaries.
        options: Existing refill settings and optional preview projection.
        state: Complete mutable New Wine namespace.
        run: Active run inside that namespace.
        presentation: Named presenter for accepted workflow outcomes.
        reader: Optional explicit no-discovery transfer interaction.

    Returns:
        Original refill summary with observed and projected membership counts.
    """
    raw = run.get("refill_pending")
    pending = raw if isinstance(raw, dict) and raw.get("source") is not None else None
    ids = await _destination_ids(access, options)
    if len(ids) >= options.target_size and pending is None:
        return _full_summary(options, len(ids))
    sources = await access.playlist(options.source)
    review = CellarReview(reader if options.no_discovery else None)
    review.restore(run)
    session = CellarRefill(
        access, options, state, run, presentation, ids, sources, review
    )
    return await session.execute(cast(dict[str, object] | None, pending))


async def _destination_ids(access: CellarAccess, options: CellarOptions) -> set[str]:
    if options.projected_ids is not None:
        return set(options.projected_ids)
    return {track.spotify_id for track in (await access.playlist(options.destination))}


def _full_summary(options: CellarOptions, before: int) -> CellarRefillSummary:
    return CellarRefillSummary(
        options.target_size, before, before, 0, 0, 0, options.no_discovery, ()
    )


def _optional_count(raw: object) -> int | None:
    return raw if isinstance(raw, int) else None


@dataclass
class CellarRefill:
    """Own one refill's observed IDs, accepted counters and pending-transfer state.

    Args:
        access: Explicit effect boundaries.
        options: Existing refill settings.
        state: Complete namespace to checkpoint.
        run: Active run containing pending-transfer state.
        moved: Original transfer message resource.
        destination_ids: Current or projected destination membership.
        sources: Original ordered cellar observations.
        review: Run-owned confirmation, cancellation and skipped-marker state.
        results: Results produced by this invocation.
        added: Destination markers accepted or previewed.
        removed: Source markers removed or previewed.
        ineligible: Sources left in the cellar by the existing eligibility rule.
        counts: Eligibility observations cached by normalized artist name.
        presentation: Named presenter for accepted workflow outcomes.
    """

    access: CellarAccess
    options: CellarOptions
    state: dict[str, object]
    run: dict[str, object]
    presentation: TransferPresentation
    destination_ids: set[str]
    sources: tuple[PlaylistTrack, ...]
    review: CellarReview
    results: list[CellarRefillResult] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    ineligible: int = 0
    counts: dict[str, LibraryCounts] = field(default_factory=dict)

    async def execute(self, pending: dict[str, object] | None) -> CellarRefillSummary:
        """Apply the pending transfer before eligibility reads and normal scanning.

        Args:
            pending: Existing accepted transfer intent, if any.

        Returns:
            Ordered results and legacy projected counts.
        """
        cellar_ids = {source.spotify_id for source in self.sources}
        before = len(self.destination_ids)
        run_id = str(self.run["run_id"])
        if pending is not None:
            await self._resume(pending, cellar_ids, run_id)
        inventory = await self._inventory()
        await self._scan(cellar_ids, inventory, run_id)
        await self._discovery_fallback(cellar_ids, run_id)
        return CellarRefillSummary(
            self.options.target_size,
            before,
            len(self.destination_ids),
            self.added,
            self.removed,
            self.ineligible,
            self.options.no_discovery,
            tuple(self.results),
            self.review.paused,
            bool(self.run.get("discovery_fallback")),
        )

    async def _discovery_fallback(self, cellar_ids: set[str], run_id: str) -> None:
        if self.review.paused or not discovery_fallback(
            self.options.no_discovery,
            len(self.destination_ids),
            self.options.target_size,
        ):
            return
        self.presentation.recovery_exhausted(
            len(self.destination_ids), self.options.target_size
        )
        self.options = replace(self.options, no_discovery=False)
        self.run["no_discovery"] = False
        self.run["discovery_fallback"] = True
        if not self.options.dry_run:
            await self.access.save(self.state)
        await self._scan(cellar_ids, ({}, {}), run_id)

    async def _inventory(self) -> Inventory:
        if (
            self.options.no_discovery
            and len(self.destination_ids) < self.options.target_size
        ):
            return await self.access.inventory()
        return {}, {}

    async def _resume(
        self, pending: dict[str, object], cellar_ids: set[str], run_id: str
    ) -> None:
        source = self.access.source(pending["source"])
        liked = _optional_count(pending.get("liked_tracks"))
        albums = _optional_count(pending.get("saved_albums"))
        result = await self._transfer(source, liked, albums, cellar_ids)
        await self._pending(None)
        await self._record(result, run_id)

    async def _scan(
        self, cellar_ids: set[str], inventory: Inventory, run_id: str
    ) -> None:
        for source in self.sources:
            if (
                self.review.paused
                or len(self.destination_ids) >= self.options.target_size
            ):
                break
            if (
                source.spotify_id not in cellar_ids
                or source.spotify_id in self.review.skipped
            ):
                continue
            await self._consider(source, cellar_ids, inventory, run_id)

    async def _consider(
        self,
        source: PlaylistTrack,
        cellar_ids: set[str],
        inventory: Inventory,
        run_id: str,
    ) -> None:
        liked, albums, eligible = await self._eligibility(source, inventory)
        if not eligible:
            result = CellarRefillResult(
                source.name,
                source.primary_artist_name,
                "ineligible",
                liked,
                albums,
                self.options.dry_run,
            )
            self.ineligible += 1
            await self._record(result, run_id)
            return
        if not await self._confirm(source, liked, albums, run_id):
            return
        await self._pending(
            {
                "source": asdict(source),
                "liked_tracks": liked,
                "saved_albums": albums,
            }
        )
        result = await self._transfer(source, liked, albums, cellar_ids)
        await self._pending(None)
        await self._record(result, run_id)

    async def _confirm(
        self, source: PlaylistTrack, liked: int | None, albums: int | None, run_id: str
    ) -> bool:
        reader = self.review.reader
        if not self.options.no_discovery or reader is None:
            return True
        self.review.check()
        choice = await reader.choose_transfer(source, liked, albums)
        self.review.check()
        if choice == "quit":
            self.review.paused = True
            return False
        if choice == "skip":
            await self._skip(source, liked, albums, run_id)
            return False
        if choice != "accept":
            raise NewWineError("The Wine Cellar transfer choice is not available.")
        await self._fresh_transfer(source)
        return True

    async def _skip(
        self, source: PlaylistTrack, liked: int | None, albums: int | None, run_id: str
    ) -> None:
        self.review.skipped.add(source.spotify_id)
        if not self.options.dry_run:
            self.run["refill_skipped"] = sorted(self.review.skipped)
            await self.access.save(self.state)
        result = CellarRefillResult(
            source.name,
            source.primary_artist_name,
            "skipped",
            liked,
            albums,
            self.options.dry_run,
        )
        await self._record(result, run_id)

    async def _fresh_transfer(self, source: PlaylistTrack) -> None:
        sources = await self.access.playlist(self.options.source)
        if source not in sources:
            raise NewWineError(
                "Wine Cellar changed during confirmation. Run again to review it."
            )
        if self.options.dry_run:
            return
        destination = await self.access.playlist(self.options.destination)
        ids = {track.spotify_id for track in destination}
        if source.spotify_id not in ids and len(ids) >= self.options.target_size:
            raise NewWineError(
                "New Wine filled during confirmation. No transfer was applied."
            )
        self.destination_ids.clear()
        self.destination_ids.update(ids)

    async def _eligibility(
        self, source: PlaylistTrack, inventory: Inventory
    ) -> tuple[int | None, int | None, bool]:
        if not self.options.no_discovery:
            return None, None, True
        key = source.primary_artist_name.strip().casefold()
        if key not in self.counts:
            self.counts[key] = await self.access.counts(
                source.primary_artist_name, inventory
            )
        return self.counts[key]

    async def _transfer(
        self,
        source: PlaylistTrack,
        liked: int | None,
        albums: int | None,
        cellar_ids: set[str],
    ) -> CellarRefillResult:
        duplicate = source.spotify_id in self.destination_ids
        in_cellar = source.spotify_id in cellar_ids
        self.review.check()
        if not duplicate:
            await self._append(source)
        self.review.check()
        if in_cellar:
            await self._remove(source, cellar_ids)
        action: Literal["already present", "moved"] = (
            "already present" if duplicate else "moved"
        )
        result = CellarRefillResult(
            source.name,
            source.primary_artist_name,
            action,
            liked,
            albums,
            self.options.dry_run,
        )
        self.presentation.moved(source, duplicate, self.options.dry_run)
        return result

    async def _append(self, source: PlaylistTrack) -> None:
        if not self.options.dry_run:
            await self.access.append(self.options.destination, source)
        self.destination_ids.add(source.spotify_id)
        self.added += 1

    async def _remove(self, source: PlaylistTrack, cellar_ids: set[str]) -> None:
        if not self.options.dry_run:
            await self.access.remove(self.options.source, source)
        cellar_ids.discard(source.spotify_id)
        self.removed += 1

    async def _pending(self, pending: dict[str, object] | None) -> None:
        if not self.options.dry_run:
            self.run["refill_pending"] = pending
            await self.access.save(self.state)

    async def _record(self, result: CellarRefillResult, run_id: str) -> None:
        self.results.append(result)
        await self.access.audit(run_id, result)
