"""Operator decisions at the Wine Cellar transfer boundary."""

from typing import Literal
from typing import Protocol

from spotify_manager.domain.catalog import PlaylistTrack


type TransferChoice = Literal["accept", "skip", "quit"]


class TransferChoiceReader(Protocol):
    """Present an eligible transfer and observe cancellation around its checkpoint."""

    async def choose_transfer(
        self, source: PlaylistTrack, liked: int | None, albums: int | None
    ) -> TransferChoice:
        """Read an explicit decision for one eligible cellar marker.

        Args:
            source: Candidate marker, including its release and artist.
            liked: Observed liked-track count, if counted.
            albums: Observed saved-album count, if counted.

        Returns:
            Acceptance, skip for this run, or pause the refill.
        """
        ...

    def check(self) -> None:
        """Stop when this interaction's owning invocation has been cancelled.

        Raises:
            RuntimeError: The owning interface reports cancellation.
        """
        ...
