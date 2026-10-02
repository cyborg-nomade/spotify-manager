"""Typed in-memory ports for independently replaying original Queue flush traces."""

import json
from dataclasses import asdict
from dataclasses import dataclass

from spotify_manager.application.queue_flush import QueueFlush
from spotify_manager.application.queue_flush import new_flush_run
from spotify_manager.application.queue_flush_values import FlushResult
from spotify_manager.application.queue_state import QueueStateAccess
from spotify_manager.application.queue_values import QueueSpotifyError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.infrastructure.queue_records import catalog_track
from spotify_manager.infrastructure.queue_records import flush_result
from spotify_manager.infrastructure.queue_records import playlist_track
from tests.support.queue_flush import SOURCE
from tests.support.queue_flush import FlushObservations


@dataclass
class MemoryQueueFlush:
    """Provide original scenario facts without the compatibility runner or SDK.

    Args:
        observations: Original shared scenario observations.
    """

    observations: FlushObservations

    def configure(self) -> None:
        """Use direct in-memory calls without an external retry observation."""

    def state(self) -> QueueStateAccess:
        """Return caller-owned original state observations.

        Returns:
            In-memory state reader and accepted checkpoint writer.
        """
        return self.observations

    def default_state(self) -> dict[str, object]:
        """Create original empty preview state without durable reads.

        Returns:
            Original default versioned document.
        """
        return {"version": 1, "artist_mappings": {}, "active_flush": None}

    def queue_id(self) -> str:
        """Return the original configured Queue identity.

        Returns:
            Original Queue identity.
        """
        return "queue"

    def queue(self) -> tuple[PlaylistTrack, ...]:
        """Observe original live Queue even when resuming.

        Returns:
            Current original ordered markers.
        """
        self.observations.record("playlist", "queue")
        return tuple(self.observations.playlists["queue"])

    def new_run(self, tracks: tuple[PlaylistTrack, ...]) -> dict[str, object]:
        """Snapshot original sources using independent application clocks.

        Args:
            tracks: Original live Queue markers.

        Returns:
            Original compatible new run.
        """
        return new_flush_run("queue", tracks, 10, self.observations.now)

    def queue_2(self) -> set[str]:
        """Observe original promotion membership before unlucky membership.

        Returns:
            Original represented primary artist identities.
        """
        self.observations.record("playlist", "queue2")
        return {
            track.primary_artist_id for track in self.observations.playlists["queue2"]
        }

    def unlucky(self) -> set[str]:
        """Observe original unlucky membership after promotion membership.

        Returns:
            Original represented primary artist identities.
        """
        self.observations.record("playlist", "unlucky")
        return {
            track.primary_artist_id for track in self.observations.playlists["unlucky"]
        }

    def decode_source(self, raw: object) -> PlaylistTrack:
        """Use the original boundary codec without a routine or startup dependency.

        Args:
            raw: Original unchecked stored source.

        Returns:
            Original authoritative marker.
        """
        return playlist_track(raw)

    def decode_target(self, raw: object) -> CatalogTrack | None:
        """Use the original boundary codec without a routine or startup dependency.

        Args:
            raw: Original unchecked stored target.

        Returns:
            Original optional target marker.
        """
        return catalog_track(raw)

    def plan(self, source: PlaylistTrack, uris: list[str]) -> dict[str, object]:
        """Observe live planning before the accepted original checkpoint.

        Args:
            source: Original authoritative source marker.
            uris: Original live or fallback source URIs.

        Returns:
            Original configured plan record.
        """
        self.observations.record("plan", source.spotify_id, uris)
        return self.observations.plan_record(uris)

    def append(
        self, destination: str, source: PlaylistTrack, target: CatalogTrack
    ) -> None:
        """Accept the original destination marker before possible failure.

        Args:
            destination: Original configured destination role.
            source: Original authoritative source marker.
            target: Original selected marker.
        """
        marker = PlaylistTrack(
            target.spotify_id,
            target.uri,
            target.name,
            target.primary_artist_id,
            target.primary_artist_name,
            SOURCE.release,
        )
        self.observations.playlists[destination].append(marker)
        self.observations.record("append", destination, target.uri)

    def following(self, source: PlaylistTrack) -> bool:
        """Observe and validate original follow status even during preview.

        Args:
            source: Original authoritative source marker.

        Returns:
            Original first follow status.

        Raises:
            QueueSpotifyError: The original configured response is invalid.
        """
        statuses = self.observations.current_user_following_artists(
            [source.primary_artist_id]
        )
        if not statuses:
            raise QueueSpotifyError("Spotify returned invalid artist follow status.")
        return statuses[0]

    def unfollow(self, source: PlaylistTrack) -> None:
        """Accept the original artist URI removal.

        Args:
            source: Original authoritative source marker.
        """
        self.observations.record(
            "unfollow", [f"spotify:artist:{source.primary_artist_id}"]
        )

    def remove_local(self, source: PlaylistTrack) -> None:
        """Observe local mirror removal after accepted unfollow.

        Args:
            source: Original authoritative source marker.
        """
        self.observations.record("remove-local", source.primary_artist_id)

    def remove(self, source: PlaylistTrack, uris: list[str]) -> None:
        """Accept original source removal before possible failure.

        Args:
            source: Original authoritative source marker.
            uris: Original ordered removable URIs.
        """
        original = self.observations.playlists["queue"]
        retained: list[PlaylistTrack] = []
        for track in original:
            if track.uri not in uris:
                retained.append(track)
        self.observations.playlists["queue"] = retained
        self.observations.record("remove", "queue", uris)

    def result(
        self, source: PlaylistTrack, plan: dict[str, object], preview: bool
    ) -> FlushResult:
        """Use the original codec after ordered accepted mutations.

        Args:
            source: Original authoritative source marker.
            plan: Original authoritative plan.
            preview: Original preview behavior.

        Returns:
            Original completed outcome.
        """
        return flush_result(source, plan, preview)

    def audit(
        self, run: dict[str, object], source: PlaylistTrack, result: FlushResult
    ) -> None:
        """Accept the original audit before completion checkpointing.

        Args:
            run: Original authoritative run.
            source: Original authoritative source marker.
            result: Original completed outcome.
        """
        self.observations.record(
            "audit",
            "flush_artist_completed",
            {
                "run_id": run.get("run_id"),
                "artist_id": source.primary_artist_id,
                "result": asdict(result),
            },
        )

    def present(
        self,
        action: str,
        source: PlaylistTrack,
        target: CatalogTrack | None,
        preview: bool,
    ) -> None:
        """Observe original accepted destination or unfollow text.

        Args:
            action: Original action being presented.
            source: Original authoritative source marker.
            target: Original optional marker.
            preview: Original preview behavior.
        """
        self.observations.echo(_message(action, source, target, preview))

    def progress(self, done: int, total: int, message: str) -> None:
        """Observe original planning or completion progress.

        Args:
            done: Original completed count.
            total: Original stored entry count.
            message: Original stage text.
        """
        self.observations.progress(done, total, message)


def _message(
    action: str, source: PlaylistTrack, target: CatalogTrack | None, preview: bool
) -> str:
    if action == "unfollow":
        return (
            f"{'Would unfollow' if preview else 'Unfollowed'} "
            f"{source.primary_artist_name}."
        )
    assert target is not None
    if action == "advance":
        return (
            f"{'Would advance' if preview else 'Advanced'} "
            f"{source.primary_artist_name} to {target.name}."
        )
    if action == "promote":
        return (
            f"{'Would promote' if preview else 'Promoted'} "
            f"{source.primary_artist_name} to Queue 2 with {target.name}."
        )
    return (
        f"{'Would add' if preview else 'Added'} "
        f"{source.primary_artist_name} to Unlucky Ones with {target.name}."
    )


def application_outcome(scenario: str, preview: bool, failure: str | None) -> object:
    """Replay original scenarios through independent application boundaries.

    Args:
        scenario: Original configured facts and restart authority.
        preview: Original preview behavior.
        failure: Optional accepted boundary that raises.

    Returns:
        JSON-compatible original outcomes, effects and checkpoint evidence.
    """
    edge = FlushObservations(scenario, failure)
    edge.setup()
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = asdict(QueueFlush(MemoryQueueFlush(edge)).run(preview))
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome.update(trace=edge.trace, state=edge.state, checkpoints=edge.checkpoints)
    playlists: dict[str, list[str]] = {}
    for key, tracks in edge.playlists.items():
        playlists[key] = [track.spotify_id for track in tracks]
    outcome["playlists"] = playlists
    return json.loads(json.dumps(outcome, default=str))
