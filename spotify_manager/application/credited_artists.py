"""Recover all credited artist follows with the original batch/checkpoint rules."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.ports.listening import Clock
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.domain.library import AlbumArtist


class CreditedArtistAccess(Protocol):
    """Fresh membership, remote follows, mirror publication, and audit effects."""

    def statuses(self, artists: list[AlbumArtist]) -> list[bool]:
        """Read ordered current membership without normalizing response length.

        Args:
            artists: Original forty-artist batch.

        Returns:
            Ordered membership observations.
        """

    def follow(self, artists: list[AlbumArtist]) -> None:
        """Follow the missing artists as one original-size request.

        Args:
            artists: Ordered artists whose observed membership is falsey.
        """

    def record(self, artists: list[AlbumArtist]) -> set[str]:
        """Publish all checked artists to the local mirror and statistics.

        Args:
            artists: Complete checked batch, including previously followed artists.

        Returns:
            IDs newly inserted into the local artist mirror.
        """

    def audit(self, events: list[dict[str, object]]) -> None:
        """Append completed artist events before persisting the checkpoint.

        Args:
            events: Original heterogeneous JSON event documents.
        """


@dataclass(frozen=True)
class CreditedArtistDependencies:
    """Effects and presentation needed while recovering credited artists.

    Args:
        access: Current observations and original ordered effects.
        clock: Timestamp source read after mirror publication for each batch.
        announce: Original follow/preview message delivery.
    """

    access: CreditedArtistAccess
    clock: Clock
    announce: Callable[[AlbumArtist, bool], None]


def _distinct(artists: list[AlbumArtist], checked: set[str]) -> list[AlbumArtist]:
    distinct = {}
    for artist in artists:
        if artist.spotify_id not in checked:
            distinct[artist.spotify_id] = artist
    return list(distinct.values())


def _missing(artists: list[AlbumArtist], statuses: list[bool]) -> list[AlbumArtist]:
    if len(statuses) != len(artists):
        raise RuntimeError("Spotify returned an incomplete artist-follow response.")
    missing = []
    for artist, followed in zip(artists, statuses, strict=True):
        if not followed:
            missing.append(artist)
    return missing


def _event(
    artist: AlbumArtist,
    followed: bool,
    recorded: set[str],
    timestamp: str,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "event": "artist_checked",
        "checked_at": timestamp,
        "spotify_id": artist.spotify_id,
        "artist": artist.name,
        "was_followed": bool(followed),
        "followed_now": not followed and not dry_run,
        "recorded_locally": artist.spotify_id in recorded,
    }


def _events(
    dependencies: CreditedArtistDependencies,
    artists: list[AlbumArtist],
    statuses: list[bool],
    recorded: set[str],
    dry_run: bool,
) -> tuple[list[dict[str, object]], int]:
    timestamp = dependencies.clock().isoformat()
    events = []
    followed_count = 0
    for artist, followed in zip(artists, statuses, strict=True):
        if not followed:
            dependencies.announce(artist, dry_run)
            followed_count += 1
        events.append(_event(artist, followed, recorded, timestamp, dry_run))
    return events, followed_count


def _batch(
    dependencies: CreditedArtistDependencies,
    artists: list[AlbumArtist],
    state: RecoveryState,
    dry_run: bool,
) -> int:
    statuses = dependencies.access.statuses(artists)
    missing = _missing(artists, statuses)
    if missing and not dry_run:
        dependencies.access.follow(missing)
    recorded = set() if dry_run else dependencies.access.record(artists)
    events, followed = _events(dependencies, artists, statuses, recorded, dry_run)
    state.checked_artist_ids.update(artist.spotify_id for artist in artists)
    if not dry_run:
        dependencies.access.audit(events)
        state.persist()
    return followed


def follow_credited_artists(
    dependencies: CreditedArtistDependencies,
    artists: list[AlbumArtist],
    state: RecoveryState,
    dry_run: bool,
) -> tuple[int, int]:
    """Check each unseen artist with stable duplicate and batching semantics.

    Args:
        dependencies: Existing observation, publication, audit, and message effects.
        artists: Album credits, including duplicates across albums.
        state: Mutable completed-work state and its persistence callback.
        dry_run: Preview without remote or durable writes.

    Returns:
        Completed artist-check and new-follow counts for this invocation.

    Raises:
        RuntimeError: A membership response is incomplete or an effect fails.
    """
    pending = _distinct(artists, state.checked_artist_ids)
    checked = 0
    followed = 0
    for start in range(0, len(pending), 40):
        batch = pending[start : start + 40]
        followed += _batch(dependencies, batch, state, dry_run)
        checked += len(batch)
    return checked, followed
