"""Persist explicit plans before restart-safe Queue 2 marker transfers."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.discovery_queue import QueueProjection
from spotify_manager.application.discovery_queue import QueueTransferResult
from spotify_manager.application.discovery_queue import _projection
from spotify_manager.application.new_kids_plan_records import plan_record
from spotify_manager.application.new_kids_plan_records import saved_plan
from spotify_manager.application.new_kids_plan_selection import AcceptedReleasePlan
from spotify_manager.application.new_kids_plan_selection import NewKidsPlanSelection
from spotify_manager.application.new_kids_state import logical_artist
from spotify_manager.application.new_kids_state import release_from_record
from spotify_manager.application.new_kids_state import source_from_record
from spotify_manager.application.new_kids_state import track_from_record
from spotify_manager.application.new_kids_values import FillResult
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.ports.state import AsyncRoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.new_kids_plans import plan_marker


def _intents(state: dict[str, object]) -> dict[str, object]:
    raw = state.setdefault("release_plan_transfers", {})
    if not isinstance(raw, dict):
        raise NewKidsStateError("New Kids planned transfers are invalid.")
    return cast(dict[str, object], raw)


def _without(tracks: list[PlaylistTrack], identity: str) -> list[PlaylistTrack]:
    return [track for track in tracks if track.spotify_id != identity]


def _contains(tracks: list[PlaylistTrack], identity: str) -> bool:
    return any(track.spotify_id == identity for track in tracks)


@dataclass
class TransferPreview:
    """Retain only invocation-local projected markers between prefill and refill.

    Args:
        tracks: Projected destination, absent before its first complete observation.
        moved: Source marker IDs already projected as removed.
    """

    tracks: list[PlaylistTrack] | None = None
    moved: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class PlannedTransfer:
    """Pin both sides of one accepted transfer until its effects are acknowledged.

    Args:
        source: Queue 2 marker to remove after securing the destination.
        target: First track of the first selected release.
        artist_id: Logical artist identity retained across performer credits.
        artist_name: Logical artist display name.
    """

    source: PlaylistTrack
    target: PlaylistTrack
    artist_id: str
    artist_name: str


@dataclass(frozen=True)
class PlannedDiscoveryTransfers(DiscoveryQueueTransfer):
    """Extend original transfer resources with plan selection and durable intent.

    Args:
        selection: Named read-only plan editor and catalogue stage.
        state_access: Existing New Kids namespace checkpoint authority.
    """

    selection: NewKidsPlanSelection
    state_access: AsyncRoutineState
    skipped: set[str] = field(default_factory=set)
    started: set[str] = field(default_factory=set)
    preview: TransferPreview = field(default_factory=TransferPreview)

    async def move(
        self,
        current: list[PlaylistTrack],
        state: dict[str, object],
        queue: list[PlaylistTrack] | None = None,
    ) -> QueueTransferResult:
        """Recover accepted transfers, then request plans for new eligible artists.

        Args:
            current: Complete observed destination markers, updated in place.
            state: Complete mutable namespace, cloned by preview callers.
            queue: Optional observed Queue 2 markers.

        Returns:
            Projected destination, transfer results and unprocessed source markers.

        Raises:
            NewKidsStateError: Saved intent conflicts with live playlist membership.
            ReleasePlanStopped: The operator stops before accepting another plan.
        """
        queued = (
            list(await self.access.playlist(self.source)) if queue is None else queue
        )
        if self.dry_run:
            current, queued = self._preview_inputs(current, queued)
        projection = _projection(current, state)
        results = await self._recover(projection, state, queued)
        remaining: list[PlaylistTrack] = []
        for marker in queued:
            artist_id, _name = logical_artist(state, marker)
            if len(current) >= self.capacity or artist_id in self.skipped:
                remaining.append(marker)
                continue
            result = await self._candidate(projection, state, marker)
            results.append(result)
            if result.action == "skipped":
                self.skipped.add(artist_id)
                remaining.append(marker)
        return current, tuple(results), remaining

    def _preview_inputs(
        self, current: list[PlaylistTrack], queued: list[PlaylistTrack]
    ) -> tuple[list[PlaylistTrack], list[PlaylistTrack]]:
        if self.preview.tracks is None:
            self.preview.tracks = current
        for identity in self.preview.moved:
            queued = _without(queued, identity)
        return self.preview.tracks, queued

    def review_markers(
        self, current: list[PlaylistTrack], state: dict[str, object]
    ) -> list[PlaylistTrack]:
        """Leave newly started plans at their first track until the next invocation.

        Args:
            current: Complete post-prefill destination.
            state: Logical artist routes.

        Returns:
            Only artists already in progress before these accepted transfers.
        """
        result = []
        for marker in current:
            if logical_artist(state, marker)[0] not in self.started:
                result.append(marker)
        return result

    def project_review(
        self, run: dict[str, object], live_ids: set[str], state: dict[str, object]
    ) -> None:
        """Apply previewed review transitions before calculating final refill capacity.

        Args:
            run: Run-local decisions accepted without durable writes.
            live_ids: Existing executor's projected destination membership.
            state: Preview-only namespace retaining logical composer routes.
        """
        current = self.preview.tracks
        if current is None:
            return
        retained = []
        for marker in current:
            if marker.spotify_id in live_ids:
                retained.append(marker)
        for target in _review_targets(run):
            if target.spotify_id in live_ids and not _contains(
                retained, target.spotify_id
            ):
                retained.append(target)
        current[:] = retained
        _project_composer_routes(run, state)

    async def _candidate(
        self,
        projection: QueueProjection,
        state: dict[str, object],
        marker: PlaylistTrack,
    ) -> FillResult:
        artist_id, name = logical_artist(state, marker)
        if artist_id in projection.artists:
            return await self._transfer(projection, marker, artist_id, name)
        accepted = await self.selection.run(marker, artist_id, name)
        if accepted is None:
            return FillResult(name, marker.name, "skipped")
        intent = PlannedTransfer(marker, accepted.marker, artist_id, name)
        await self._accept(state, intent, accepted)
        return await self._apply(projection, state, intent)

    async def _accept(
        self,
        state: dict[str, object],
        intent: PlannedTransfer,
        accepted: AcceptedReleasePlan,
    ) -> None:
        artists = state.get("artists")
        if not isinstance(artists, dict):
            raise NewKidsStateError("New Kids artist progress is invalid.")
        prior = artists.get(intent.artist_id)
        progress = dict(prior) if isinstance(prior, dict) else {}
        progress.update(
            {
                "artist_name": intent.artist_name,
                "current_release_id": accepted.plan.releases[0].spotify_id,
                "prior_unliked_streak": 0,
                "release_plan": plan_record(accepted.plan),
            }
        )
        artists[intent.artist_id] = progress
        _intents(state)[intent.source.spotify_id] = {
            **asdict(intent),
            "source_playlist": self.source,
            "destination_playlist": self.destination,
        }
        await self._checkpoint(state)

    async def _recover(
        self,
        projection: QueueProjection,
        state: dict[str, object],
        queued: list[PlaylistTrack],
    ) -> list[FillResult]:
        results = []
        for raw in tuple(_intents(state).values()):
            intent = self._decode(raw)
            _check_intent_plan(state, intent)
            source_present = _contains(queued, intent.source.spotify_id)
            if not source_present and intent.target.spotify_id not in projection.ids:
                raise NewKidsStateError(
                    "Neither side of a saved New Kids transfer is present."
                )
            results.append(await self._apply(projection, state, intent))
            queued[:] = _without(queued, intent.source.spotify_id)
        return results

    def _decode(self, raw: object) -> PlannedTransfer:
        if not isinstance(raw, dict):
            raise NewKidsStateError("New Kids transfer intent is invalid.")
        if (
            raw.get("source_playlist") != self.source
            or raw.get("destination_playlist") != self.destination
        ):
            raise NewKidsStateError(
                "Saved New Kids transfer belongs to different playlists."
            )
        if not raw.get("artist_id") or not raw.get("artist_name"):
            raise NewKidsStateError("New Kids transfer artist is invalid.")
        return PlannedTransfer(
            source_from_record(raw.get("source")),
            source_from_record(raw.get("target")),
            str(raw["artist_id"]),
            str(raw["artist_name"]),
        )

    async def _apply(
        self,
        projection: QueueProjection,
        state: dict[str, object],
        intent: PlannedTransfer,
    ) -> FillResult:
        if intent.target.spotify_id not in projection.ids:
            if (
                intent.artist_id in projection.artists
                or len(projection.tracks) >= self.capacity
            ):
                raise NewKidsStateError(
                    "The saved transfer conflicts with current New Kids "
                    "capacity or artist membership."
                )
            if not self.dry_run:
                await self.access.append(
                    self.destination,
                    intent.target,
                    f"starting {intent.artist_name}'s release plan",
                )
            projection.tracks.append(intent.target)
            projection.ids.add(intent.target.spotify_id)
            projection.artists.add(intent.artist_id)
        await self._remove(intent.source, f"removing {intent.artist_name} from Queue 2")
        _intents(state).pop(intent.source.spotify_id)
        await self._checkpoint(state)
        self.started.add(intent.artist_id)
        self.preview.moved.add(intent.source.spotify_id)
        await self._audit(intent.target, intent.artist_id, intent.artist_name)
        self.presentation.moved(intent.artist_name, self.dry_run)
        return FillResult(intent.artist_name, intent.target.name, "moved")

    async def _checkpoint(self, state: dict[str, object]) -> None:
        if not self.dry_run:
            await self.state_access.save(state)


def _review_targets(run: dict[str, object]) -> list[PlaylistTrack]:
    entries = run.get("entries")
    if not isinstance(entries, list):
        raise NewKidsStateError("New Kids preview entries are invalid.")
    targets = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("plan"), dict):
            continue
        plan = entry["plan"]
        target = track_from_record(plan.get("target"))
        if target is None or plan.get("target_release") is None:
            continue
        release = release_from_record(plan["target_release"])
        targets.append(plan_marker(release, target))
    return targets


def _project_composer_routes(run: dict[str, object], state: dict[str, object]) -> None:
    routes = state.get("composer_routes")
    entries = run.get("entries")
    if not isinstance(routes, dict) or not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("plan"), dict):
            continue
        plan = entry["plan"]
        route = routes.get(entry.get("artist_id"))
        if not plan.get("composer_playlist_id") or not isinstance(route, dict):
            continue
        target = track_from_record(plan.get("target"))
        if target is None:
            routes.pop(entry.get("artist_id"), None)
            continue
        route["current_track_id"] = target.spotify_id


def _check_intent_plan(state: dict[str, object], intent: PlannedTransfer) -> None:
    artists = state.get("artists")
    progress = artists.get(intent.artist_id) if isinstance(artists, dict) else None
    if not isinstance(progress, dict):
        raise NewKidsStateError("Saved transfer has no accepted artist plan.")
    plan = saved_plan(progress)
    if plan is None or plan.position != 0:
        raise NewKidsStateError("Saved transfer has no initial release plan.")
    if plan.releases[0].spotify_id != intent.target.release.spotify_id:
        raise NewKidsStateError(
            "Saved transfer does not match its accepted first album."
        )
