"""Recover removed albums through ordered observations and explicit effects."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import date

from spotify_manager.application.ports.listening import Clock
from spotify_manager.application.ports.recovery import RecoveryLibrary
from spotify_manager.application.ports.recovery import RecoveryPresentation
from spotify_manager.application.recovery_values import RecoveryAlbum
from spotify_manager.application.recovery_values import RecoveryCounts
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.application.recovery_values import RecoverySummary
from spotify_manager.application.recovery_values import RemovedAlbumRecord
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.domain.library import release_is_in_future


type Progress = Callable[[int, int], None]


def _event(record: RemovedAlbumRecord, timestamp: str) -> dict[str, object]:
    return {
        "event": "album_processed",
        "processed_at": timestamp,
        "status": "unavailable",
        "spotify_id": record.spotify_id,
        "album": record.album,
        "artist": record.artist,
    }


def _credits(artists: tuple[AlbumArtist, ...]) -> list[dict[str, str]]:
    result = []
    for artist in artists:
        result.append({"spotify_id": artist.spotify_id, "name": artist.name})
    return result


def _available_event(
    record: RemovedAlbumRecord,
    album: RecoveryAlbum,
    timestamp: str,
    future: bool,
    restoration: tuple[bool, bool, bool],
) -> dict[str, object]:
    already_saved, restored, local_added = restoration
    event = _event(record, timestamp)
    event.update(
        status="available",
        album=album.name or record.album,
        credited_artists=_credits(album.artists),
        release_date=album.release_date,
        release_date_precision=album.precision,
        future_release=future,
        already_saved=already_saved,
        restored=restored,
        local_album_added=local_added,
    )
    return event


@dataclass
class RecoveryRun:
    """Mutable invocation state with each effect at a named recovery stage.

    Args:
        library: Existing observation, mutation, and audit boundaries.
        presentation: Existing message delivery.
        state: Completed-work state and its persistence callback.
        dry_run: Preview without remote or durable writes.
        clock: Original per-album audit timestamp source.
        today: Date source read only when the observed release date is nonempty.
        progress: Optional completion/cancellation callback.
        completed: Prior completed records included in the input.
        total: Progress denominator, respecting the original limit semantics.
    """

    library: RecoveryLibrary
    presentation: RecoveryPresentation
    state: RecoveryState
    dry_run: bool
    clock: Clock
    today: Callable[[], date]
    progress: Progress | None
    completed: int
    total: int
    counts: RecoveryCounts = field(default_factory=RecoveryCounts, init=False)

    def _notify_progress(self) -> None:
        if self.progress is not None:
            self.progress(self.completed, self.total)

    def _restore(
        self, record: RemovedAlbumRecord, album: RecoveryAlbum
    ) -> tuple[bool, bool, bool]:
        self.counts.future += 1
        saved = self.library.saved(record)
        restored = False
        if not saved:
            restored = self._save_future(record, album)
        if self.dry_run:
            return saved, restored, False
        local_added = self.library.record_album(album, record)
        if restored:
            self.presentation.future(
                record, album.release_date, "Restored future release"
            )
        else:
            self.presentation.future(
                record, album.release_date, "Future release already saved"
            )
        return saved, restored, local_added

    def _save_future(self, record: RemovedAlbumRecord, album: RecoveryAlbum) -> bool:
        if self.dry_run:
            self.presentation.future(
                record, album.release_date, "Would restore future release"
            )
            self.counts.restored += 1
            return False
        self.library.restore(record)
        self.counts.restored += 1
        return True

    def _available(
        self, record: RemovedAlbumRecord, album: RecoveryAlbum, timestamp: str
    ) -> dict[str, object]:
        if len(album.artists) > 1:
            self.counts.multiple += 1
            self.presentation.credits(album, record)
        future = False
        if album.release_date:
            future = release_is_in_future(
                album.release_date, album.precision, self.today()
            )
        restoration = self._restore(record, album) if future else (False, False, False)
        return _available_event(record, album, timestamp, future, restoration)

    def _album(self, record: RemovedAlbumRecord, album: RecoveryAlbum | None) -> None:
        timestamp = self.clock().isoformat()
        if album is None:
            self.counts.unavailable += 1
            self.presentation.unavailable(record)
            event = _event(record, timestamp)
        else:
            event = self._available(record, album, timestamp)
        if not self.dry_run:
            self.library.audit(event)
        self.state.processed_album_ids.add(record.spotify_id)
        if not self.dry_run:
            self.state.persist()
        self.completed += 1
        self.counts.processed += 1
        self._notify_progress()

    def _batch(self, records: list[RemovedAlbumRecord]) -> None:
        albums = self.library.albums(records)
        artists: list[AlbumArtist] = []
        for album in albums:
            if album is not None:
                artists.extend(album.artists)
        checked, followed = self.library.follow_artists(
            artists, self.state, self.dry_run
        )
        self.counts.checked += checked
        self.counts.followed += followed
        for record, album in zip(records, albums, strict=True):
            self._album(record, album)

    def execute(self, records: list[RemovedAlbumRecord]) -> RecoverySummary:
        """Run original twenty-album batches and present the final result.

        Args:
            records: Ordered pending records after applying the original limit.

        Returns:
            Original immutable result counts.

        Raises:
            RuntimeError: An integration or callback interrupts execution.
            ValueError: A response contains more albums than requested.
        """
        self._notify_progress()
        for start in range(0, len(records), 20):
            self._batch(records[start : start + 20])
        summary = self.counts.summary()
        self.presentation.finish(summary, self.dry_run)
        return summary


def _pending(
    records: list[RemovedAlbumRecord], state: RecoveryState, limit: int | None
) -> tuple[list[RemovedAlbumRecord], int, int]:
    identifiers = {record.spotify_id for record in records}
    completed = len(state.processed_album_ids.intersection(identifiers))
    pending = []
    for record in records:
        if record.spotify_id not in state.processed_album_ids:
            pending.append(record)
    if limit is None:
        return pending, completed, len(records)
    pending = pending[:limit]
    return pending, completed, completed + len(pending)


def recover_albums(
    library: RecoveryLibrary,
    presentation: RecoveryPresentation,
    clock: Clock,
    today: Callable[[], date],
    *,
    dry_run: bool = False,
    limit: int | None = None,
    progress: Progress | None = None,
) -> RecoverySummary:
    """Resume recovery while preserving accepted writes and checkpoint timing.

    Args:
        library: Run-scoped observations and ordered effects.
        presentation: Existing user-facing output.
        clock: Per-album audit timestamp source.
        today: Per-album date source for nonempty release dates.
        dry_run: Preview without remote or durable writes.
        limit: Original slice limit, including zero and negative values.
        progress: Optional completion and cancellation callback.

    Returns:
        Counts for work completed in this invocation.

    Raises:
        RuntimeError: An integration or callback interrupts execution.
        ValueError: Metadata batch size or stored input is invalid.
    """
    records, state = library.load()
    pending, completed, total = _pending(records, state, limit)
    run = RecoveryRun(
        library, presentation, state, dry_run, clock, today, progress, completed, total
    )
    return run.execute(pending)
