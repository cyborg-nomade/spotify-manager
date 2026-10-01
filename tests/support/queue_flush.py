"""Capture original Queue flush effects, accepted checkpoints and restart authority."""

import json
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import the_queue as legacy
from tests.support.queue_fill import TRACK
from tests.support.queue_neighbors import NOW


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/queue_flush.json"
SOURCE = PlaylistTrack(
    "source",
    "spotify:track:source",
    "Source",
    "artist",
    "Artist",
    ReleaseCandidate(
        "release",
        "spotify:album:release",
        "Release",
        "album",
        "2020",
        3,
        "artist",
        "Artist",
    ),
)


def _initial_state() -> dict[str, object]:
    return {"version": 1, "artist_mappings": {}, "active_flush": None}


def _playlists() -> dict[str, list[PlaylistTrack]]:
    return {"queue": [SOURCE], "queue2": [], "unlucky": []}


@dataclass
class FlushObservations:
    """Record original effects while retaining accepted remote and state mutations.

    Args:
        scenario: Original action, membership or restart scenario.
        failure: Optional accepted effect that raises.
        trace: Original observed effects and arguments.
        state: Caller-owned original restart document.
        checkpoints: Independent accepted checkpoint snapshots.
        playlists: Original live playlist observations.
    """

    scenario: str
    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=_initial_state)
    checkpoints: list[dict[str, object]] = field(default_factory=list)
    playlists: dict[str, list[PlaylistTrack]] = field(default_factory=_playlists)

    def setup(self) -> None:
        """Supply original membership and stored-run facts before observations."""
        if self.scenario in {"promote-present", "unlucky-present"}:
            destination = "queue2" if self.scenario == "promote-present" else "unlucky"
            self.playlists[destination].append(SOURCE)
        if self.scenario == "advance-present":
            self.playlists["queue"].append(self._target_marker())
        if self.scenario.startswith("resume"):
            self.state["active_flush"] = self._stored_run()
        if self.scenario == "empty":
            self.playlists["queue"] = []

    def _stored_run(self) -> dict[str, object]:
        entry: dict[str, object] = {
            "source": asdict(SOURCE),
            "status": "pending",
            "plan": None,
        }
        if self.scenario == "resume-plan":
            entry["plan"] = self.plan_record([SOURCE.uri])
        if self.scenario == "resume-completed":
            entry["status"] = "completed"
        entries: object = [entry]
        if self.scenario == "resume-bad-entries":
            entries = {}
        if self.scenario == "resume-bad-entry":
            entries = [None]
        if self.scenario == "resume-bad-source":
            entry["source"] = None
        return {"run_id": "stored", "playlist_id": "queue", "entries": entries}

    def _target_marker(self) -> PlaylistTrack:
        return PlaylistTrack(
            TRACK.spotify_id,
            TRACK.uri,
            TRACK.name,
            TRACK.primary_artist_id,
            TRACK.primary_artist_name,
            SOURCE.release,
        )

    def record(self, effect: str, *details: object) -> None:
        """Observe an effect and fail only after its configured acceptance.

        Args:
            effect: Original boundary identifier.
            details: Original observed arguments.

        Raises:
            RuntimeError: The configured accepted effect fails.
        """
        self.trace.append([effect, *details])
        count = sum(row[0] == effect for row in self.trace)
        if self.failure in {effect, f"{effect}:{count}"}:
            raise RuntimeError(effect)

    def now(self, zone: tzinfo | None = None) -> datetime:
        """Observe each original run clock separately.

        Args:
            zone: Original requested UTC timezone.

        Returns:
            Fixed original timestamp.
        """
        self.record("clock")
        return NOW

    def load(self) -> dict[str, object]:
        """Observe original real-run state loading.

        Returns:
            Original caller-owned state.
        """
        self.record("load")
        return self.state

    def save(self, state: dict[str, object]) -> None:
        """Accept an independent original checkpoint before possible failure.

        Args:
            state: Complete caller-owned working state.
        """
        self.checkpoints.append(deepcopy(state))
        self.record("save")

    def playlist(
        self,
        spotify: Spotify,
        playlist: str,
        retry: legacy.RetryCall,
    ) -> tuple[PlaylistTrack, ...]:
        """Observe original ordered destination reads.

        Args:
            spotify: Original client boundary.
            playlist: Original requested identity.
            retry: Original retry boundary.

        Returns:
            Original current ordered membership.
        """
        self.record("playlist", playlist)
        return tuple(self.playlists[playlist])

    def plan_record(self, uris: list[str]) -> dict[str, object]:
        """Build configured original plan facts without performing an effect.

        Args:
            uris: Original source marker URIs.

        Returns:
            Original compatible stored plan.
        """
        action = self.scenario.split("-", 1)[0]
        if action not in {
            "advance",
            "promote",
            "unlucky",
            "unfollow",
            "blocked",
            "unknown",
        }:
            action = "advance"
        target = asdict(TRACK) if action in {"advance", "promote", "unlucky"} else None
        return {
            "action": action,
            "source_uris": uris,
            "target": target,
            "target_release": "Release" if action == "promote" else None,
            "top_tracks": 10,
            "top_liked_tracks": 2,
            "total_liked_tracks": 3,
            "reason": "original reason",
        }

    def plan(
        self,
        spotify: Spotify,
        source: PlaylistTrack,
        uris: list[str],
        retry: legacy.RetryCall,
    ) -> dict[str, object]:
        """Observe original live planning before its durable checkpoint.

        Args:
            spotify: Original client boundary.
            source: Original snapshotted source marker.
            uris: Original live source markers or fallback source URI.
            retry: Original retry boundary.

        Returns:
            Original configured plan facts.
        """
        self.record("plan", source.spotify_id, uris)
        return self.plan_record(uris)

    def append(self, spotify: Spotify, playlist: str, uri: str) -> None:
        """Accept the original destination marker before a possible failure.

        Args:
            spotify: Original client boundary.
            playlist: Original destination identity.
            uri: Original selected marker.
        """
        self.playlists[playlist].append(self._target_marker())
        self.record("append", playlist, uri)

    def remove(self, spotify: Spotify, playlist: str, uris: list[str]) -> None:
        """Accept the original source removal before possible failure.

        Args:
            spotify: Original client boundary.
            playlist: Original Queue identity.
            uris: Original ordered removable URIs.
        """
        retained: list[PlaylistTrack] = []
        for track in self.playlists[playlist]:
            if track.uri not in uris:
                retained.append(track)
        self.playlists[playlist] = retained
        self.record("remove", playlist, uris)

    def current_user_following_artists(self, artists: list[str]) -> list[bool]:
        """Observe original follow status even during preview.

        Args:
            artists: Original ordered artist identities.

        Returns:
            Original configured status response.
        """
        self.record("following", artists)
        if self.scenario == "unfollow-bad":
            return []
        return [self.scenario != "unfollow-absent"]

    def unfollow(self, spotify: Spotify, uris: list[str]) -> None:
        """Accept the original library artist removal.

        Args:
            spotify: Original client boundary.
            uris: Original artist URIs.
        """
        self.record("unfollow", uris)

    def remove_local(self, artist: str, path: Path) -> None:
        """Observe original mirror removal after accepted unfollow.

        Args:
            artist: Original artist identity.
            path: Original mirror location.
        """
        self.record("remove-local", artist)

    def audit(self, path: Path, event: str, **details: object) -> None:
        """Accept the original completion event before entry checkpointing.

        Args:
            path: Original audit location.
            event: Original event name.
            details: Original event fields.
        """
        self.record("audit", event, details)

    def echo(self, message: str) -> None:
        """Observe original user-facing text.

        Args:
            message: Original presentation text.
        """
        self.record("echo", message)

    def progress(self, done: int, total: int, message: str) -> None:
        """Observe original planning and completion progress.

        Args:
            done: Original completed count.
            total: Original entry count.
            message: Original stage text.
        """
        self.record("progress", done, total, message)


def _patches(edge: FlushObservations) -> tuple[tuple[object, str, object], ...]:
    return (
        (new_wine, "load_playlist_tracks", edge.playlist),
        (legacy, "_plan_flush_entry", edge.plan),
        (legacy, "add_playlist_item", edge.append),
        (legacy, "remove_playlist_items", edge.remove),
        (legacy, "remove_library_artists", edge.unfollow),
        (new_kids, "remove_local_artist", edge.remove_local),
        (legacy, "append_event", edge.audit),
        (legacy, "datetime", edge),
    )


def _run(edge: FlushObservations, preview: bool) -> object:
    with ExitStack() as stack:
        for module, name, callback in _patches(edge):
            stack.enter_context(patch.object(module, name, callback))
        stack.enter_context(patch.object(legacy, "_state_access", return_value=edge))
        result = legacy.flush_queue(
            cast(Spotify, edge),
            legacy.QueuePlaylists("queue", "queue2", "new-kids", "queue3", "unlucky"),
            dry_run=preview,
            echo=edge.echo,
            progress_callback=edge.progress,
        )
    return asdict(result)


def original_outcome(scenario: str, preview: bool, failure: str | None) -> object:
    """Observe the original complete runner without files or external writes.

    Args:
        scenario: Original configured planning and restart facts.
        preview: Original preview behavior.
        failure: Optional accepted boundary that raises.

    Returns:
        JSON-compatible original results, traces and accepted checkpoint evidence.
    """
    edge = FlushObservations(scenario, failure)
    edge.setup()
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _run(edge, preview)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome.update(trace=edge.trace, state=edge.state, checkpoints=edge.checkpoints)
    playlists: dict[str, list[str]] = {}
    for key, tracks in edge.playlists.items():
        playlists[key] = [track.spotify_id for track in tracks]
    outcome["playlists"] = playlists
    return json.loads(json.dumps(outcome, default=str))


def cases() -> list[tuple[str, dict[str, object]]]:
    """Read immutable original Queue flush and restart observations.

    Returns:
        Named original inputs and complete outcomes.
    """
    raw = cast(dict[str, dict[str, object]], json.loads(FIXTURE.read_text()))
    return list(raw.items())


def restart_observations(case: dict[str, object]) -> FlushObservations:
    """Reconstruct accepted durable and remote observations after an interruption.

    Args:
        case: Original immutable failed-run inputs and observations.

    Returns:
        New invocation reading the last accepted checkpoint and remote membership.
    """
    outcome = cast(dict[str, object], case["outcome"])
    checkpoints = cast(list[dict[str, object]], outcome["checkpoints"])
    edge = FlushObservations(cast(str, case["scenario"]))
    edge.state = deepcopy(checkpoints[-1] if checkpoints else _initial_state())
    memberships = cast(dict[str, list[str]], outcome["playlists"])
    markers = {SOURCE.spotify_id: SOURCE, TRACK.spotify_id: edge._target_marker()}
    edge.playlists = {}
    for playlist, identities in memberships.items():
        edge.playlists[playlist] = [markers[identity] for identity in identities]
    return edge


def restart_cases() -> list[tuple[str, dict[str, object]]]:
    """Select original interruption scenarios with frozen resumed observations.

    Returns:
        Immutable failed-run inputs and original recovery outcomes.
    """
    selected: list[tuple[str, dict[str, object]]] = []
    for name, case in cases():
        if "restart_outcome" in case:
            selected.append((name, case))
    return selected
