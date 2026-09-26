"""Fill available New Wine slots with ordered, resumable Wine Cellar transfers."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Literal
from typing import Protocol
from typing import cast

from spotify_manager.application.new_wine_values import CellarRefillResult
from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.domain.catalog import PlaylistTrack


type Inventory = tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]
type LibraryCounts = tuple[int | None, int, bool]


class CellarAccess(Protocol):
    """Observe playlists and library eligibility, then perform individual effects."""

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read ordered current markers.

        Args:
            playlist_id: Source or destination to observe.

        Returns:
            Parsed playable markers in existing order.
        """

    def inventory(self) -> Inventory:
        """Read local candidate IDs by normalized primary artist name.

        Returns:
            Liked-track and saved-album candidate maps.
        """

    def counts(self, artist: str, inventory: Inventory) -> LibraryCounts:
        """Observe library counts until either existing eligibility threshold is met.

        Args:
            artist: Source marker's primary artist display name.
            inventory: Candidate IDs read from the canonical mirrors.

        Returns:
            Liked count (possibly omitted), saved-album count and eligibility.
        """

    def append(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Append a source marker as a destination track.

        Args:
            playlist_id: New Wine destination.
            source: Original Wine Cellar marker.
        """

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove the source after its destination marker is secure.

        Args:
            playlist_id: Wine Cellar source.
            source: Original marker to remove.
        """

    def save(self, state: dict[str, object]) -> None:
        """Persist the complete namespace at one pending-transfer boundary.

        Args:
            state: Namespace containing the active run and pending transfer.
        """

    def audit(self, run_id: str, result: CellarRefillResult) -> None:
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


def refill_cellar(
    access: CellarAccess,
    options: CellarOptions,
    state: dict[str, object],
    run: dict[str, object],
    moved: Callable[[PlaylistTrack, bool, bool], None],
) -> CellarRefillSummary:
    """Resume any pending transfer, then fill available slots in cellar order.

    Args:
        access: Explicit playlist, inventory, checkpoint and audit boundaries.
        options: Existing refill settings and optional preview projection.
        state: Complete mutable New Wine namespace.
        run: Active run inside that namespace.
        moved: Presentation callback receiving source, duplicate flag and preview flag.

    Returns:
        Original refill summary with observed and projected membership counts.
    """
    raw = run.get("refill_pending")
    pending = raw if isinstance(raw, dict) and raw.get("source") is not None else None
    ids = _destination_ids(access, options)
    if len(ids) >= options.target_size and pending is None:
        return _full_summary(options, len(ids))
    sources = access.playlist(options.source)
    session = CellarRefill(access, options, state, run, moved, ids, sources)
    return session.execute(cast(dict[str, object] | None, pending))


def _destination_ids(access: CellarAccess, options: CellarOptions) -> set[str]:
    if options.projected_ids is not None:
        return set(options.projected_ids)
    return {track.spotify_id for track in access.playlist(options.destination)}


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
        moved: Original transfer message callback.
        destination_ids: Current or projected destination membership.
        sources: Original ordered cellar observations.
        results: Results produced by this invocation.
        added: Destination markers accepted or previewed.
        removed: Source markers removed or previewed.
        ineligible: Sources left in the cellar by the existing eligibility rule.
        counts: Eligibility observations cached by normalized artist name.
    """

    access: CellarAccess
    options: CellarOptions
    state: dict[str, object]
    run: dict[str, object]
    moved: Callable[[PlaylistTrack, bool, bool], None]
    destination_ids: set[str]
    sources: tuple[PlaylistTrack, ...]
    results: list[CellarRefillResult] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    ineligible: int = 0
    counts: dict[str, LibraryCounts] = field(default_factory=dict)

    def execute(self, pending: dict[str, object] | None) -> CellarRefillSummary:
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
            self._resume(pending, cellar_ids, run_id)
        inventory = self._inventory()
        self._scan(cellar_ids, inventory, run_id)
        return CellarRefillSummary(
            self.options.target_size,
            before,
            len(self.destination_ids),
            self.added,
            self.removed,
            self.ineligible,
            self.options.no_discovery,
            tuple(self.results),
        )

    def _inventory(self) -> Inventory:
        if (
            self.options.no_discovery
            and len(self.destination_ids) < self.options.target_size
        ):
            return self.access.inventory()
        return {}, {}

    def _resume(
        self, pending: dict[str, object], cellar_ids: set[str], run_id: str
    ) -> None:
        source = self.access.source(pending["source"])
        liked = _optional_count(pending.get("liked_tracks"))
        albums = _optional_count(pending.get("saved_albums"))
        result = self._transfer(source, liked, albums, cellar_ids)
        self._pending(None)
        self._record(result, run_id)

    def _scan(self, cellar_ids: set[str], inventory: Inventory, run_id: str) -> None:
        for source in self.sources:
            if len(self.destination_ids) >= self.options.target_size:
                break
            if source.spotify_id not in cellar_ids:
                continue
            self._consider(source, cellar_ids, inventory, run_id)

    def _consider(
        self,
        source: PlaylistTrack,
        cellar_ids: set[str],
        inventory: Inventory,
        run_id: str,
    ) -> None:
        liked, albums, eligible = self._eligibility(source, inventory)
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
            self._record(result, run_id)
            return
        self._pending(
            {"source": asdict(source), "liked_tracks": liked, "saved_albums": albums}
        )
        result = self._transfer(source, liked, albums, cellar_ids)
        self._pending(None)
        self._record(result, run_id)

    def _eligibility(
        self, source: PlaylistTrack, inventory: Inventory
    ) -> tuple[int | None, int | None, bool]:
        if not self.options.no_discovery:
            return None, None, True
        key = source.primary_artist_name.strip().casefold()
        if key not in self.counts:
            self.counts[key] = self.access.counts(source.primary_artist_name, inventory)
        return self.counts[key]

    def _transfer(
        self,
        source: PlaylistTrack,
        liked: int | None,
        albums: int | None,
        cellar_ids: set[str],
    ) -> CellarRefillResult:
        duplicate = source.spotify_id in self.destination_ids
        in_cellar = source.spotify_id in cellar_ids
        if not duplicate:
            self._append(source)
        if in_cellar:
            self._remove(source, cellar_ids)
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
        self.moved(source, duplicate, self.options.dry_run)
        return result

    def _append(self, source: PlaylistTrack) -> None:
        if not self.options.dry_run:
            self.access.append(self.options.destination, source)
        self.destination_ids.add(source.spotify_id)
        self.added += 1

    def _remove(self, source: PlaylistTrack, cellar_ids: set[str]) -> None:
        if not self.options.dry_run:
            self.access.remove(self.options.source, source)
        cellar_ids.discard(source.spotify_id)
        self.removed += 1

    def _pending(self, pending: dict[str, object] | None) -> None:
        if not self.options.dry_run:
            self.run["refill_pending"] = pending
            self.access.save(self.state)

    def _record(self, result: CellarRefillResult, run_id: str) -> None:
        self.results.append(result)
        self.access.audit(run_id, result)
