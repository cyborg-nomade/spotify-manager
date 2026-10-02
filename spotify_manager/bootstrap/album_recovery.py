"""Compose removed-album recovery from caller-owned synchronous dependencies."""

from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.album_recovery import Progress
from spotify_manager.application.album_recovery import recover_albums
from spotify_manager.application.credited_artists import CreditedArtistDependencies
from spotify_manager.application.credited_artists import follow_credited_artists
from spotify_manager.application.ports.listening import Clock
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.application.recovery_values import RecoverySummary
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.infrastructure.legacy.album_recovery import CreditedArtistAdapter
from spotify_manager.infrastructure.legacy.album_recovery import LegacyAlbumRecovery
from spotify_manager.interfaces.presenters.album_recovery import RecoveryPresenter
from spotify_manager.interfaces.presenters.album_recovery import announce_artist
from spotify_manager.models.your_library import YourLibraryArtist


def run_artist_recovery(
    spotify: Spotify,
    artists: list[AlbumArtist],
    state: RecoveryState,
    total_artists: list[YourLibraryArtist],
    known_ids: set[str],
    retry: Callable[[Callable[[], object], str], object],
    echo: Callable[[str], None],
    audit_path: Path,
    dry_run: bool,
    clock: Clock,
) -> tuple[int, int]:
    """Bind credited-artist recovery without creating clients or changing retries.

    Args:
        spotify: Caller-owned client.
        artists: Original album credits.
        state: Current completed-work state.
        total_artists: Mutable mirror snapshot.
        known_ids: IDs already in the mirror.
        retry: Original retry callback.
        echo: Original output callback.
        audit_path: Original recovery audit destination.
        dry_run: Preview without remote or durable writes.
        clock: Original batch timestamp source.

    Returns:
        Original completed-check and new-follow counts.
    """
    access = CreditedArtistAdapter(spotify, total_artists, known_ids, retry, audit_path)
    dependencies = CreditedArtistDependencies(
        access, clock, partial(announce_artist, echo)
    )
    return follow_credited_artists(dependencies, artists, state, dry_run)


def run_album_recovery(
    spotify: Spotify,
    echo: Callable[[str], None],
    progress: Progress | None,
    removal_log: Path,
    recovery_log: Path,
    dry_run: bool,
    limit: int | None,
    today: Callable[[], date],
    clock: Clock,
    sleep: Callable[[float], None],
    retry_delay: int,
    max_attempts: int,
    state_service: StateService | None,
) -> RecoverySummary:
    """Bind the original adapters and messages to the recovery use case.

    Args:
        spotify: Caller-owned client.
        echo: Original output sink.
        progress: Optional completion callback.
        removal_log: Original removal history path.
        recovery_log: Original recovery audit path.
        dry_run: Preview without remote or durable writes.
        limit: Original pending-record slice limit.
        today: Original per-album date source.
        clock: Original per-album audit timestamp source.
        sleep: Retry wait callback.
        retry_delay: Retry delay.
        max_attempts: Retry limit.
        state_service: Optional shared-state service.

    Returns:
        Original immutable recovery counts.
    """
    library = LegacyAlbumRecovery(
        spotify,
        echo,
        removal_log,
        recovery_log,
        state_service,
        sleep,
        retry_delay,
        max_attempts,
    )
    return recover_albums(
        library,
        RecoveryPresenter(echo),
        clock,
        today,
        dry_run=dry_run,
        limit=limit,
        progress=progress,
    )
