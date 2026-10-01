"""Bind restartable Queue flush to original synchronous SDK and storage seams."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.queue_flush_values import FlushResult
from spotify_manager.application.queue_state import QueueStateAccess
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.routines import the_queue as legacy


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


@dataclass
class LegacyQueueFlush:
    """Retain original caller-owned clients, authority, retry and presentation.

    Args:
        spotify: Original caller-owned client.
        playlists: Original configured destination identities.
        echo: Original text presenter.
        callback: Original optional status presenter.
        configured_retry: Original optional retry boundary.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        log_path: Original audit location.
        artists_path: Original artist mirror location.
        retry: Original effective retry resolved before state authority.
    """

    spotify: Spotify
    playlists: legacy.QueuePlaylists
    echo: legacy.Echo
    callback: legacy.ProgressCallback | None
    configured_retry: legacy.RetryCall | None
    state_path: Path
    state_service: StateService | None
    log_path: Path
    artists_path: Path
    retry: legacy.RetryCall = _immediate

    def configure(self) -> None:
        """Resolve the original falsey retry boundary before state authority."""
        self.retry = self.configured_retry or _immediate

    def state(self) -> QueueStateAccess:
        """Resolve original state authority even during preview.

        Returns:
            Original caller-owned state handle.
        """
        return legacy._state_access(self.state_path, self.state_service)

    def default_state(self) -> dict[str, object]:
        """Create original empty preview state without durable reads.

        Returns:
            Original empty versioned state.
        """
        return legacy._default_state()

    def queue_id(self) -> str:
        """Return the original configured Queue identity.

        Returns:
            Original Queue playlist identity.
        """
        return self.playlists.queue

    def queue(self) -> tuple[PlaylistTrack, ...]:
        """Read original live Queue membership even during resumed execution.

        Returns:
            Original live markers in source order.
        """
        return legacy.new_wine.load_playlist_tracks(
            self.spotify, self.playlists.queue, self.retry
        )

    def new_run(self, tracks: tuple[PlaylistTrack, ...]) -> dict[str, object]:
        """Retain the original daily snapshot seam and distinct clock reads.

        Args:
            tracks: Original live Queue observations.

        Returns:
            Original mutable daily snapshot.
        """
        return legacy._new_flush_run(self.playlists.queue, tracks)

    def queue_2(self) -> set[str]:
        """Read original promotion membership before unlucky membership.

        Returns:
            Original represented primary artist identities.
        """
        tracks = legacy.new_wine.load_playlist_tracks(
            self.spotify, self.playlists.queue_2, self.retry
        )
        return {track.primary_artist_id for track in tracks}

    def unlucky(self) -> set[str]:
        """Read original unlucky membership after promotion membership.

        Returns:
            Original represented primary artist identities.
        """
        tracks = legacy.new_wine.load_playlist_tracks(
            self.spotify, self.playlists.unlucky_ones, self.retry
        )
        return {track.primary_artist_id for track in tracks}

    def decode_source(self, raw: object) -> PlaylistTrack:
        """Preserve original stored-source tolerance and errors.

        Args:
            raw: Original unchecked source record.

        Returns:
            Original authoritative source marker.
        """
        return legacy._playlist_track_from_record(raw)

    def decode_target(self, raw: object) -> CatalogTrack | None:
        """Preserve original optional target tolerance and errors.

        Args:
            raw: Original unchecked target record.

        Returns:
            Original target marker or no target.
        """
        return legacy._catalog_track_from_record(raw)

    def plan(self, source: PlaylistTrack, uris: list[str]) -> dict[str, object]:
        """Retain original live planning before its accepted checkpoint.

        Args:
            source: Original authoritative source marker.
            uris: Original live or fallback source URIs.

        Returns:
            Original compatible plan record.
        """
        return legacy._plan_flush_entry(self.spotify, source, uris, self.retry)

    def append(
        self, destination: str, source: PlaylistTrack, target: CatalogTrack
    ) -> None:
        """Accept the original destination marker with its unchanged retry text.

        Args:
            destination: Original configured destination role.
            source: Original authoritative source marker.
            target: Original selected destination marker.
        """
        playlist, description = self._destination(destination, source)
        self.retry(
            partial(legacy.add_playlist_item, self.spotify, playlist, target.uri),
            description,
        )

    def _destination(self, destination: str, source: PlaylistTrack) -> tuple[str, str]:
        if destination == "queue":
            return (
                self.playlists.queue,
                f"adding the next Queue track for {source.primary_artist_name}",
            )
        if destination == "queue2":
            return (
                self.playlists.queue_2,
                f"promoting {source.primary_artist_name} to Queue 2",
            )
        return (
            self.playlists.unlucky_ones,
            f"adding {source.primary_artist_name} to Unlucky Ones",
        )

    def following(self, source: PlaylistTrack) -> bool:
        """Read and validate original follow status even during preview.

        Args:
            source: Original authoritative source marker.

        Returns:
            Original first observed follow status.
        """
        return legacy._flush_following(self.spotify, source, self.retry)

    def unfollow(self, source: PlaylistTrack) -> None:
        """Accept original artist removal before local mirror removal.

        Args:
            source: Original authoritative source marker.
        """
        self.retry(
            partial(
                legacy.remove_library_artists,
                self.spotify,
                [f"spotify:artist:{source.primary_artist_id}"],
            ),
            f"unfollowing {source.primary_artist_name}",
        )

    def remove_local(self, source: PlaylistTrack) -> None:
        """Retain original mirror removal after accepted unfollow.

        Args:
            source: Original authoritative source marker.
        """
        legacy.new_kids.remove_local_artist(source.primary_artist_id, self.artists_path)

    def remove(self, source: PlaylistTrack, uris: list[str]) -> None:
        """Accept original source marker removal with unchanged retry text.

        Args:
            source: Original authoritative source marker.
            uris: Original ordered removable URIs.
        """
        self.retry(
            partial(
                legacy.remove_playlist_items, self.spotify, self.playlists.queue, uris
            ),
            f"removing the previous Queue marker for {source.primary_artist_name}",
        )

    def result(
        self, source: PlaylistTrack, plan: dict[str, object], preview: bool
    ) -> FlushResult:
        """Preserve result decoding after accepted source removal.

        Args:
            source: Original authoritative source marker.
            plan: Original authoritative plan.
            preview: Original preview behavior.

        Returns:
            Original presented completion outcome.
        """
        return legacy._flush_result(source, plan, preview)

    def audit(
        self, run: dict[str, object], source: PlaylistTrack, result: FlushResult
    ) -> None:
        """Accept original completion fields before marking the entry completed.

        Args:
            run: Original authoritative run.
            source: Original authoritative source marker.
            result: Original completed outcome.
        """
        legacy.append_event(
            self.log_path,
            "flush_artist_completed",
            run_id=run.get("run_id"),
            artist_id=source.primary_artist_id,
            result=asdict(result),
        )

    def present(
        self,
        action: str,
        source: PlaylistTrack,
        target: CatalogTrack | None,
        preview: bool,
    ) -> None:
        """Preserve original destination and unfollow text.

        Args:
            action: Original destination or unfollow action.
            source: Original authoritative source marker.
            target: Original optional target marker.
            preview: Original preview behavior.
        """
        self.echo(_action_message(action, source, target, preview))

    def progress(self, done: int, total: int, message: str) -> None:
        """Preserve original optional planning and completion progress.

        Args:
            done: Original completed-entry count.
            total: Original stored-entry count.
            message: Original stage text.
        """
        if self.callback is not None:
            self.callback(done, total, message)


def _action_message(
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
