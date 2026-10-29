"""Ordered playlist effects for Friday and anniversary historical track batches."""

from dataclasses import dataclass

from spotify_manager.application.historical_resolution import HistoricalResolution
from spotify_manager.application.historical_selection import AnniversarySelection
from spotify_manager.application.historical_selection import BlastSelection
from spotify_manager.application.historical_values import BlastFromPastConfigError
from spotify_manager.application.historical_values import BlastFromPastSpotifySummary
from spotify_manager.application.historical_values import DailyMindRadioSpotifySummary
from spotify_manager.application.historical_values import SpotifySelectionResolution
from spotify_manager.application.ports.history import HistoricalPlaylist
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.application.ports.runtime import Messages


@dataclass(frozen=True)
class HistoricalPlaylistEffects:
    """Read and resolve playlists without owning a client or retry implementation.

    Args:
        access: Original playlist reads and accepted appends.
        resolution: Named application stage for search and liked decisions.
        check_cancel: Check cancellation at the routine's original boundaries.
        progress: Present original progress messages.
    """

    access: HistoricalPlaylist
    resolution: HistoricalResolution
    check_cancel: Cancellation
    progress: Messages

    async def apply(self, resolution: SpotifySelectionResolution, dry_run: bool) -> int:
        """Append pending tracks and return the actual projected increase.

        Args:
            resolution: Selected matches and pending additions.
            dry_run: Suppress append and adding message.

        Returns:
            Added track count, or zero in preview mode.
        """
        if not resolution.pending_matches or dry_run:
            return 0
        self.progress.echo(
            f"Adding {len(resolution.pending_matches)} tracks to Spotify"
        )
        await self.access.append(list(resolution.pending_matches))
        return len(resolution.pending_matches)


def _validate_request(count: int | None, maximum: int | None) -> None:
    if count is not None and maximum is not None:
        raise BlastFromPastConfigError(
            "Use either count or maximum playlist length, not both."
        )
    if count is not None and count < 1:
        raise BlastFromPastConfigError("Count must be at least 1.")
    if maximum is not None and maximum < 1:
        raise BlastFromPastConfigError("Maximum playlist length must be at least 1.")


def _requested_count(count: int | None, maximum: int | None, total: int) -> int:
    if maximum is not None:
        return max(0, maximum - total)
    return 10 if count is None else count


@dataclass(frozen=True)
class BlastPlaylist:
    """Observe destination capacity before selecting historical dates.

    Args:
        effects: Existing playlist and presentation boundaries.
        selection: Named historical selection stage.
    """

    effects: HistoricalPlaylistEffects
    selection: BlastSelection

    async def run(
        self, playlist_id: str, count: int | None, maximum: int | None, dry_run: bool
    ) -> BlastFromPastSpotifySummary:
        """Resolve and append the requested batch without changing preview actions.

        Args:
            playlist_id: Destination identifier for the summary.
            count: Explicit date count or default fallback.
            maximum: Optional destination capacity.
            dry_run: Suppress remote writes.

        Returns:
            Original playlist lengths and selection results.

        Raises:
            BlastFromPastConfigError: Count and capacity configuration is invalid.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        _validate_request(count, maximum)
        self.effects.check_cancel.check()
        self.effects.progress.echo("Loading the Spotify playlist")
        playlist = await self.effects.access.read()
        requested = _requested_count(count, maximum, playlist.total_items)
        if requested == 0:
            return BlastFromPastSpotifySummary(
                playlist_id, 0, playlist.total_items, playlist.total_items, None, ()
            )
        batch = await self.selection.run(requested)
        self.effects.check_cancel.check()
        resolution = await self.effects.resolution.run(batch.selections, playlist)
        added = await self.effects.apply(resolution, dry_run)
        return BlastFromPastSpotifySummary(
            playlist_id,
            requested,
            playlist.total_items,
            playlist.total_items + added,
            batch,
            resolution.results,
        )


@dataclass(frozen=True)
class AnniversaryPlaylist:
    """Select anniversary plays before observing the destination playlist.

    Args:
        effects: Existing playlist and presentation boundaries.
        selection: Named anniversary selection stage.
    """

    effects: HistoricalPlaylistEffects
    selection: AnniversarySelection

    async def run(
        self, playlist_id: str, dry_run: bool
    ) -> DailyMindRadioSpotifySummary:
        """Skip all Spotify observations when no anniversary date is populated.

        Args:
            playlist_id: Destination identifier for the summary.
            dry_run: Suppress remote writes.

        Returns:
            Original nullable playlist lengths and resolution results.

        Raises:
            BlastFromPastCancelledError: Cancellation is requested.
        """
        self.effects.check_cancel.check()
        batch = await self.selection.run()
        self.effects.check_cancel.check()
        if not batch.selections:
            return DailyMindRadioSpotifySummary(playlist_id, batch, None, None, ())
        self.effects.progress.echo("Loading the Spotify playlist")
        playlist = await self.effects.access.read()
        resolution = await self.effects.resolution.run(batch.selections, playlist)
        added = await self.effects.apply(resolution, dry_run)
        return DailyMindRadioSpotifySummary(
            playlist_id,
            batch,
            playlist.total_items,
            playlist.total_items + added,
            resolution.results,
        )
