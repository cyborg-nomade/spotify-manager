"""Durable selection evidence and history-aware mode interaction boundaries."""

from typing import Protocol

from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import PreviousMode


class ChoiceHistoryAccess(Protocol):
    """Read evidence and persist one conflict-aware shared history namespace."""

    async def load(self) -> ChoiceLedger:
        """Read validated history.

        Returns:
            Detached completed selections and pending intents.
        """
        ...

    async def save(self, ledger: ChoiceLedger) -> None:
        """Checkpoint evidence before or after an accepted playlist effect.

        Args:
            ledger: Complete current namespace.
        """
        ...

    async def audit_choices(self) -> tuple[ArtistChoice, ...]:
        """Read usable completed legacy audits without guessing artist mappings.

        Returns:
            Verified-shape audit records with their original artist identities.
        """
        ...

    async def playlist(self, playlist_id: str) -> tuple[str | None, ...]:
        """Read complete fresh membership to reconcile an interrupted append.

        Args:
            playlist_id: Destination named by a persisted intent.

        Returns:
            Complete raw item identities, retaining duplicates and unreadable items.
        """
        ...


class HistoryModeReader(Protocol):
    """Present recorded use alongside the existing explicit mode options."""

    async def choose_mode_with_history(
        self,
        artist: GoldenOldieArtist,
        mapped: SpotifyArtistCandidate,
        previous: tuple[PreviousMode, ...],
    ) -> str:
        """Choose the current mode with prior completed selections visible.

        Args:
            artist: Current Golden Oldies artist.
            mapped: Accepted Spotify identity.
            previous: Recorded use of all three options for that identity.

        Returns:
            Explicit selection or quit; history never chooses automatically.
        """
        ...
