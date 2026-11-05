"""Persist completed choices and reconcile interrupted Something Old appends."""

from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.application.ports.something_old_history import ChoiceHistoryAccess
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import PreviousMode
from spotify_manager.domain.something_old_history import choice_identity
from spotify_manager.domain.something_old_history import previous_modes


def _selection(summary: SomethingOldSummary) -> ArtistChoice:
    assert summary.spotify_artist is not None and summary.artist is not None
    assert summary.mode is not None and summary.tracks
    return ArtistChoice(
        summary.spotify_artist.spotify_id,
        summary.spotify_artist.name,
        summary.artist.artist,
        summary.mode,
        summary.generated_at,
        summary.playlist_id,
        tuple(track.spotify_id for track in summary.tracks),
        summary.release.name if summary.release else None,
        summary.release.spotify_id if summary.release else None,
    )


def _complete_membership(
    choice: ArtistChoice, playlist: tuple[str | None, ...]
) -> bool:
    return Counter(choice.track_ids) == Counter(playlist)


@dataclass
class SomethingOldChoiceHistory:
    """Own durable evidence independently from the current listening decision.

    Args:
        access: Explicit history, audit and playlist resources.
        cancellation: Optional operator cancellation at the new pre-append checkpoint.

    Attributes:
        ledger: Detached current evidence, loaded at the invocation boundary.
    """

    access: ChoiceHistoryAccess
    cancellation: Cancellation | None = None
    ledger: ChoiceLedger = field(default_factory=ChoiceLedger, init=False)

    async def load(self, playlist_id: str, preview: bool) -> None:
        """Import available audits and reconcile only this destination's intent.

        Args:
            playlist_id: Current configured destination.
            preview: Keep reconciled/imported evidence detached without writes.
        """
        self.ledger = await self.access.load()
        changed = False
        for choice in await self.access.audit_choices():
            identity = choice_identity(choice)
            if identity not in self.ledger.choices:
                self.ledger.choices[identity] = choice
                changed = True
        recovered = await self._recover(playlist_id)
        if not preview and (changed or recovered):
            await self.access.save(self.ledger)

    def previous(self, artist_id: str) -> tuple[PreviousMode, ...]:
        """Return completed choices for one exact accepted artist identity.

        Args:
            artist_id: Spotify artist identifier.

        Returns:
            Three recorded mode summaries, excluding pending evidence.
        """
        return previous_modes(self.ledger, artist_id)

    async def begin(self, summary: SomethingOldSummary) -> None:
        """Persist an intent after the empty check and before the first append.

        Args:
            summary: Planned nonempty live selection.
        """
        self._check()
        choice = _selection(summary)
        self.ledger.pending[summary.playlist_id] = choice
        await self.access.save(self.ledger)
        self._check()

    async def complete(self, summary: SomethingOldSummary) -> None:
        """Record only a completely accepted append before the legacy audit write.

        Args:
            summary: Fully accepted live selection.
        """
        choice = _selection(summary)
        self.ledger.choices[choice_identity(choice)] = choice
        self.ledger.pending.pop(summary.playlist_id, None)
        await self.access.save(self.ledger)

    async def _recover(self, playlist_id: str) -> bool:
        pending = self.ledger.pending.get(playlist_id)
        if pending is None:
            return False
        identity = choice_identity(pending)
        if identity in self.ledger.choices:
            del self.ledger.pending[playlist_id]
            return True
        playlist = await self.access.playlist(playlist_id)
        if _complete_membership(pending, playlist):
            self.ledger.choices[identity] = replace(pending, provenance="recovered")
        elif playlist:
            return False
        del self.ledger.pending[playlist_id]
        return True

    def _check(self) -> None:
        if self.cancellation is not None:
            self.cancellation.check()
