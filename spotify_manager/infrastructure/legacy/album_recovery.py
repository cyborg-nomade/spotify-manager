"""Recovery adapters retaining the original transport and persistence helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.credited_artists import CreditedArtistDependencies
from spotify_manager.application.credited_artists import follow_credited_artists
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.recovery_values import RecoveryAlbum
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.application.recovery_values import RemovedAlbumRecord
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.interfaces.presenters.album_recovery import announce_artist
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist


@dataclass
class CreditedArtistAdapter:
    """Bind the existing artist effects to the shared recovery application service.

    Args:
        spotify: Caller-owned client.
        artists: Mutable mirror snapshot.
        known_ids: IDs already present in that snapshot.
        retry: Original retry callback.
        audit_path: Recovery audit destination.
    """

    spotify: Spotify
    artists: list[YourLibraryArtist]
    known_ids: set[str]
    retry: Callable[[Callable[[], object], str], object]
    audit_path: Path

    def statuses(self, artists: list[AlbumArtist]) -> list[bool]:
        """Read original ordered membership statuses.

        Args:
            artists: Current batch.

        Returns:
            Original membership response.
        """
        from spotify_manager.routines.recover_removed_albums import _artist_statuses

        return _artist_statuses(self.spotify, artists, self.retry)

    def follow(self, artists: list[AlbumArtist]) -> None:
        """Follow the missing batch through its original retry boundary.

        Args:
            artists: Missing artists in original order.
        """
        from spotify_manager.routines.recover_removed_albums import (
            _follow_missing_artists,
        )

        _follow_missing_artists(self.spotify, artists, self.retry)

    def record(self, artists: list[AlbumArtist]) -> set[str]:
        """Publish artist mirror and statistics changes in their original order.

        Args:
            artists: Complete checked batch.

        Returns:
            IDs added to the mirror.
        """
        from spotify_manager.routines.recover_removed_albums import (
            add_artists_to_local_files,
        )

        return add_artists_to_local_files(artists, self.artists, self.known_ids)

    def audit(self, events: list[dict[str, object]]) -> None:
        """Append the original artist events.

        Args:
            events: Completed artist observations.
        """
        from spotify_manager.routines.recover_removed_albums import (
            append_recovery_events,
        )

        append_recovery_events(events, self.audit_path)


def _persist_state(access: RoutineState, state: RecoveryState) -> None:
    from spotify_manager.routines.recover_removed_albums import _serialize_state

    access.save(_serialize_state(state))


def _text(value: object) -> str | None:
    return str(value) if value is not None else None


def _album(raw: object) -> RecoveryAlbum | None:
    from spotify_manager.routines.recover_removed_albums import spotify_album_artists

    if not isinstance(raw, dict):
        return None
    return RecoveryAlbum(
        str(raw["name"]) if raw.get("name") else None,
        str(raw["uri"]) if raw.get("uri") else None,
        tuple(spotify_album_artists(raw)),
        _text(raw.get("release_date")),
        _text(raw.get("release_date_precision")),
    )


def _payload(album: RecoveryAlbum) -> dict[str, object]:
    artists = []
    for artist in album.artists:
        artists.append({"id": artist.spotify_id, "name": artist.name})
    return {"name": album.name, "uri": album.uri, "artists": artists}


@dataclass
class LegacyAlbumRecovery:
    """Run-scoped integration state; construction performs no I/O.

    Args:
        spotify: Caller-owned synchronous client.
        echo: Existing effect and retry message sink.
        removal_log_path: Original removal history.
        recovery_log_path: Original recovery audit path.
        state_service: Optional injected shared-state service.
        sleep: Existing retry wait callback.
        retry_delay: Original retry delay.
        max_attempts: Original retry limit.
    """

    spotify: Spotify
    echo: Callable[[str], None]
    removal_log_path: Path
    recovery_log_path: Path
    state_service: StateService | None
    sleep: Callable[[float], None]
    retry_delay: int
    max_attempts: int
    _artists: list[YourLibraryArtist] = field(default_factory=list, init=False)
    _albums: list[YourLibraryAlbum] = field(default_factory=list, init=False)
    _artist_ids: set[str] = field(default_factory=set, init=False)
    _album_ids: set[str] = field(default_factory=set, init=False)

    def _retry[T](self, operation: Callable[[], T], description: str) -> T:
        from spotify_manager.infrastructure.spotify.retry import (
            retry_spotify_server_errors,
        )

        return retry_spotify_server_errors(
            operation,
            description,
            self.echo,
            self.sleep,
            self.retry_delay,
            self.max_attempts,
        )

    def load(self) -> tuple[list[RemovedAlbumRecord], RecoveryState]:
        """Load records, progress, artists, and albums in their original order.

        Returns:
            Original records and state with a bound persistence callback.
        """
        from spotify_manager.loaders_savers import load_total_albums_new_file
        from spotify_manager.loaders_savers import load_total_artists_file
        from spotify_manager.routines.recover_removed_albums import _deserialize_state
        from spotify_manager.routines.recover_removed_albums import _state_access
        from spotify_manager.routines.recover_removed_albums import (
            load_removed_album_records,
        )

        records = load_removed_album_records(self.removal_log_path)
        access = _state_access(self.recovery_log_path, self.state_service)
        state = _deserialize_state(access.load())
        state.persist = partial(_persist_state, access, state)
        self._artists = load_total_artists_file()
        self._albums = load_total_albums_new_file()
        self._artist_ids = {artist.spotify_id for artist in self._artists}
        self._album_ids = {album.spotify_id for album in self._albums}
        return records, state

    def albums(
        self, records: list[RemovedAlbumRecord]
    ) -> tuple[RecoveryAlbum | None, ...]:
        """Parse and pad one original-size metadata batch.

        Args:
            records: Ordered requested records.

        Returns:
            Observations including excess entries, preserving strict-zip failures.

        Raises:
            RuntimeError: The albums member is not a list.
        """
        from spotify_manager.routines.recover_removed_albums import (
            _fetch_album_metadata,
        )

        album_ids = [record.spotify_id for record in records]
        raw = _fetch_album_metadata(self.spotify, album_ids, self._retry)
        padded = [*raw, *([None] * (len(records) - len(raw)))]
        return tuple(_album(item) for item in padded)

    def follow_artists(
        self, artists: list[AlbumArtist], state: RecoveryState, dry_run: bool
    ) -> tuple[int, int]:
        """Retain credited-artist checks, writes, mirror updates, and checkpoints.

        Args:
            artists: Ordered credited observations.
            state: Completed-work state.
            dry_run: Preview without remote or durable writes.

        Returns:
            Checked and newly followed counts.
        """
        from spotify_manager.routines.recover_removed_albums import _clock

        access = CreditedArtistAdapter(
            self.spotify,
            self._artists,
            self._artist_ids,
            self._retry,
            self.recovery_log_path,
        )
        dependencies = CreditedArtistDependencies(
            access, _clock, partial(announce_artist, self.echo)
        )
        return follow_credited_artists(dependencies, artists, state, dry_run)

    def saved(self, record: RemovedAlbumRecord) -> bool:
        """Read the original first saved-album status.

        Args:
            record: Original identity and retry label.

        Returns:
            Truthiness of the first observation, or False for an empty response.
        """
        from spotify_manager.routines.recover_removed_albums import _saved_album

        return _saved_album(self.spotify, record, self._retry)

    def restore(self, record: RemovedAlbumRecord) -> None:
        """Restore a future album through the original retry callback.

        Args:
            record: Original identity and retry label.
        """
        from spotify_manager.routines.recover_removed_albums import _restore_album

        _restore_album(self.spotify, record, self._retry)

    def record_album(self, album: RecoveryAlbum, record: RemovedAlbumRecord) -> bool:
        """Retain ordered mirror and statistics publication.

        Args:
            album: Parsed observations.
            record: Original identity and fallback labels.

        Returns:
            Whether the local mirror gained this album.
        """
        from spotify_manager.routines.recover_removed_albums import (
            add_album_to_local_files,
        )

        return add_album_to_local_files(
            _payload(album),
            record,
            self._albums,
            self._album_ids,
        )

    def audit(self, event: dict[str, object]) -> None:
        """Append one original recovery event.

        Args:
            event: Existing heterogeneous JSON event.
        """
        from spotify_manager.routines.recover_removed_albums import (
            append_recovery_events,
        )

        append_recovery_events([event], self.recovery_log_path)
