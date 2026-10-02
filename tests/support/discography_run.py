"""Freeze original Discography planning and accepted mutation prefixes."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import discography as legacy
from tests.support.queue_neighbors import NOW


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/discography_run.json"
PROFILES = (
    "normal",
    "round",
    "decline",
    "empty",
    "overshoot",
    "reverse",
    "duplicate-choice",
    "unknown-choice",
    "shared",
    "fallback",
    "fallback-unused",
)
FAILURES = (
    "state-access",
    "state-load",
    "queues",
    "catalog:a",
    "choose:a",
    "history",
    "map",
    "progress:1",
    "progress:2",
    "progress:3",
)


def release(identity: str, default: bool = True) -> legacy.CatalogRelease:
    """Build complete original canonical facts.

    Args:
        identity: Original release identity.
        default: Original silent packing qualification.

    Returns:
        Complete original catalog release.
    """
    return legacy.CatalogRelease(
        identity,
        f"spotify:album:{identity}",
        identity,
        "Album",
        "2020",
        "2020",
        10,
        identity,
        False,
        True,
        0,
        default,
    )


def historical() -> legacy.HistoricalArtistSelection:
    """Build original fallback facts without external reads.

    Returns:
        Complete original historical selection.
    """
    return legacy.HistoricalArtistSelection(
        NOW, NOW.date(), 2, NOW.date(), 1, 3, 2, legacy.HistoricalArtist("Past", 9)
    )


@dataclass
class PlanReads:
    """Observe original preflight, lazy reads and interactive selection.

    Args:
        profile: Configured original candidate and selection behavior.
        start: Original persisted starting queue.
        failure: Optional original observation that fails.
        trace: Ordered original boundary observations.
    """

    profile: str
    start: legacy.QueueName
    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)

    def record(self, action: str, *details: object) -> None:
        """Observe a boundary and its configured failure.

        Args:
            action: Original boundary identity.
            details: Complete observed arguments.

        Raises:
            RuntimeError: The configured boundary fails.
        """
        self.trace.append([action, *details])
        count = sum(row[0] == action for row in self.trace)
        if self.failure in {action, f"{action}:{count}"}:
            raise RuntimeError(f"{self.failure} failed")

    def state(self, path: Path, service: StateService | None) -> RoutineState:
        """Observe original state resolution.

        Args:
            path: Original location.
            service: Original optional shared state service.

        Returns:
            Original in-memory state access.
        """
        self.record("state-access", str(path), service is None)
        return cast(RoutineState, self)

    def load(self) -> dict[str, object]:
        """Read original complete priority state.

        Returns:
            Original priority and retained unknown fields.
        """
        self.record("state-load")
        return {"version": 1, "next_queue": self.start, "retained": "value"}

    def queues(
        self,
    ) -> tuple[
        dict[legacy.QueueName, tuple[legacy.QueueArtist, ...]],
        dict[str, tuple[legacy.ArtistMarkers, ...]],
    ]:
        """Supply original ordered candidates and grouped markers.

        Returns:
            Original complete candidate and marker facts.
        """
        self.record("queues")
        queues: dict[legacy.QueueName, tuple[legacy.QueueArtist, ...]] = {
            "newfoundland": (legacy.QueueArtist("a", "Alpha", "newfoundland"),),
            "memory_lane": (
                legacy.QueueArtist("b", "Beta", "memory_lane"),
                legacy.QueueArtist("c", "Gamma", "memory_lane"),
            ),
            "requeue": (legacy.QueueArtist("d", "Delta", "requeue"),),
        }
        if self.profile.startswith("fallback"):
            queues["memory_lane"] = ()
        if self.profile == "shared":
            queues["memory_lane"] = (legacy.QueueArtist("a", "Alias", "memory_lane"),)
        return queues, markers()

    def legacy_queues(
        self,
        spotify: Spotify,
        ids: dict[legacy.QueueName, str],
        retry: legacy.RetryCall,
        extra: str | None,
    ) -> tuple[
        dict[legacy.QueueName, tuple[legacy.QueueArtist, ...]],
        dict[str, tuple[legacy.ArtistMarkers, ...]],
    ]:
        """Bind the original queue helper signature.

        Args:
            spotify: Original caller-owned SDK boundary.
            ids: Original configured sources.
            retry: Original caller retry.
            extra: Original auxiliary marker playlist.

        Returns:
            Original queue and marker facts.
        """
        return self.queues()

    def catalog(
        self, candidate: legacy.QueueArtist
    ) -> tuple[legacy.CatalogRelease, ...]:
        """Supply original canonical and optional releases.

        Args:
            candidate: Original visited artist.

        Returns:
            Complete original catalog in chronology order.
        """
        self.record(f"catalog:{candidate.spotify_id}")
        if self.profile == "empty":
            return ()
        count = {"a": 4, "b": 8, "c": 6, "d": 2, "past": 6}[candidate.spotify_id]
        if self.profile in {"round", "fallback-unused"}:
            count = 10
        values = []
        for index in range(count):
            values.append(release(f"{candidate.spotify_id}-{index}"))
        if self.profile == "overshoot" and candidate.spotify_id == "c":
            values.extend((release("extra-1", False), release("extra-2", False)))
        return tuple(values)

    def legacy_catalog(
        self,
        spotify: Spotify,
        identity: str,
        retry: legacy.RetryCall,
    ) -> tuple[legacy.CatalogRelease, ...]:
        """Bind original catalog reads.

        Args:
            spotify: Original SDK boundary.
            identity: Original artist identity.
            retry: Original retry seam.

        Returns:
            Original catalog facts.
        """
        return self.catalog(legacy.QueueArtist(identity, identity, self.start))

    def choose(
        self,
        candidate: legacy.QueueArtist,
        catalog: tuple[legacy.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        """Observe original interactive choices.

        Args:
            candidate: Original candidate source and spelling.
            catalog: Complete original ordered catalog.

        Returns:
            Original chosen identities, including deliberately malformed choices.
        """
        self.record(f"choose:{candidate.spotify_id}", asdict(candidate), list(catalog))
        ids = tuple(item.spotify_id for item in catalog)
        if self.profile == "decline":
            return ()
        if self.profile == "duplicate-choice" and ids:
            return (ids[0], ids[0])
        if self.profile == "unknown-choice":
            return ("unknown",)
        return tuple(reversed(ids)) if self.profile == "reverse" else ids

    def history(self, **kwargs: object) -> legacy.HistoricalArtistSelection:
        """Supply original lazy historical fallback.

        Args:
            kwargs: Original optional facade bindings.

        Returns:
            Complete original historical facts.
        """
        self.record("history")
        return historical()

    def map(self, *args: object) -> legacy.QueueArtist:
        """Supply original mapped fallback candidate.

        Args:
            args: Original optional facade bindings.

        Returns:
            Original resolved Memory Lane artist.
        """
        self.record("map")
        return legacy.QueueArtist("past", "Past", "memory_lane")

    def progress(self, message: str) -> None:
        """Observe original stage presentation.

        Args:
            message: Original visible text.
        """
        self.record("progress", message)


def markers() -> dict[str, tuple[legacy.ArtistMarkers, ...]]:
    """Build original auxiliary-marker qualification scenarios.

    Returns:
        Marker groups with and without a Newfoundland authority.
    """
    return {
        "a": (
            legacy.ArtistMarkers("newfoundland", "nf", ("a",)),
            legacy.ArtistMarkers("queue_3", "extra", ("extra-a",)),
        ),
        "c": (
            legacy.ArtistMarkers("memory_lane", "ml", ("c",)),
            legacy.ArtistMarkers("queue_3", "extra", ("extra-c",)),
        ),
    }


def original_plan(edge: PlanReads) -> legacy.DiscographyPlan:
    """Run the original public coordinator through observed seams.

    Args:
        edge: Original configured facts and observations.

    Returns:
        Original complete plan.
    """
    bindings = {
        "_state_access": edge.state,
        "_load_artist_queues": edge.legacy_queues,
        "load_release_catalog": edge.legacy_catalog,
        "select_historical_artist": edge.history,
        "resolve_historical_artist": edge.map,
    }
    with ExitStack() as stack:
        for name, callback in bindings.items():
            stack.enter_context(patch.object(legacy, name, callback))
        return legacy.build_discography_plan(
            cast(Spotify, edge),
            {"newfoundland": "nf", "memory_lane": "ml", "requeue": "rq"},
            edge.choose,
            state_path=Path("state"),
            progress_callback=edge.progress,
        )


def plan_outcome(
    edge: PlanReads, run: Callable[[PlanReads], legacy.DiscographyPlan]
) -> object:
    """Record a complete plan or original failure prefix.

    Args:
        edge: Original configured observations.
        run: Original or independently injected coordinator.

    Returns:
        JSON-compatible complete original evidence.
    """
    outcome: dict[str, object] = {}
    try:
        plan = run(edge)
        outcome["result"] = asdict(plan)
        outcome["days"] = plan.days
        outcome["artist_days"] = [artist.days for artist in plan.artists]
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=serialize))


def serialize(value: object) -> object:
    """Serialize observed catalog facts using their original fields.

    Args:
        value: Original structured observation.

    Returns:
        Complete record or original string representation.
    """
    return asdict(value) if isinstance(value, legacy.CatalogRelease) else str(value)


def cases(name: str = "discography_run.json") -> list[dict[str, object]]:
    """Read immutable original observations.

    Args:
        name: Original fixture filename.

    Returns:
        Complete original inputs and outcomes.
    """
    return cast(
        list[dict[str, object]], json.loads(FIXTURE.with_name(name).read_text())
    )
