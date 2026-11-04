"""Bind durable choice evidence to the existing namespace, audit and Spotify edges."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.application.ports.state import AsyncRoutineState
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.core.state.models import StateError
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.history_playlist_pages import SpotifyHistoryPages
from spotify_manager.infrastructure.something_old_choice_audit import read_choice_audit
from spotify_manager.infrastructure.something_old_choice_playlist import (
    read_choice_playlist,
)
from spotify_manager.infrastructure.something_old_choice_schema import (
    SomethingOldChoiceDefinition,
)
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class SomethingOldChoiceStorage:
    """Own all external observations for the choice-history stage.

    Args:
        state: Conflict-aware namespace boundary.
        log_path: Available legacy completion audit.
        spotify: Caller-owned Spotify client.
        retry: Caller-owned retry and cancellation resource.
    """

    state: AsyncRoutineState
    log_path: Path
    spotify: SpotifyClient
    retry: Retry

    async def load(self) -> ChoiceLedger:
        """Read validated history before making the current listening decision.

        Returns:
            Complete detached durable evidence.

        Raises:
            SomethingOldError: Shared history cannot be read or validated.
        """
        try:
            return SomethingOldChoiceDefinition().decode(await self.state.load())
        except StateError as exc:
            raise SomethingOldError(
                f"Could not load Something Old choice history: {exc}"
            ) from exc

    async def save(self, ledger: ChoiceLedger) -> None:
        """Checkpoint a complete history namespace using its revision guard.

        Args:
            ledger: Validated completed and pending evidence.

        Raises:
            SomethingOldError: The checkpoint cannot be accepted safely.
        """
        try:
            await self.state.save(
                SomethingOldChoiceDefinition().encode(ledger),
                message="Save Something Old choice history",
            )
        except StateError as exc:
            raise SomethingOldError(
                f"Could not save Something Old choice history: {exc}"
            ) from exc

    async def audit_choices(self) -> tuple[ArtistChoice, ...]:
        """Read legacy audit bytes inside the bounded blocking-file edge.

        Returns:
            Completed usable audit selections, retaining audit provenance.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(read_choice_audit, self.log_path)
            )
            return await finish_blocking(task)

    async def playlist(self, playlist_id: str) -> tuple[str | None, ...]:
        """Read current complete membership only for an interrupted selection.

        Args:
            playlist_id: Destination retained in the pending intent.

        Returns:
            Complete raw identities, retaining duplicates and unreadable items.
        """
        return await read_choice_playlist(
            SpotifyHistoryPages(self.spotify, playlist_id, self.retry, None)
        )
