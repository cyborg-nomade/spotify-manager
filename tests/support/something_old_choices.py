"""Typed external observations for durable Something Old choice evidence."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Literal

from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import PreviousMode
from tests.application.test_something_old_workflow import MemoryOld
from tests.support.queue_neighbors import NOW
from tests.support.something_old_run import TRACK


type AppendOutcome = Literal["normal", "before", "partial", "after"]


@dataclass
class MemoryChoiceAccess:
    """Simulate independent durable bytes and current playlist membership.

    Args:
        stored: Last accepted namespace, independent of the stage's working copy.
        audits: Usable legacy audit records.
        tracks: Actual playlist identities, including partial or duplicate effects.
        fail_save: Checkpoint occurrence that loses its response.
        accepted: Whether that failing checkpoint was actually accepted.
        saves: Number of attempted checkpoints.
        events: Ordered external history/effect observations.
    """

    stored: ChoiceLedger = field(default_factory=ChoiceLedger)
    audits: tuple[ArtistChoice, ...] = ()
    tracks: tuple[str | None, ...] = ()
    fail_save: int | None = None
    accepted: bool = False
    saves: int = 0
    events: list[str] = field(default_factory=list)

    async def load(self) -> ChoiceLedger:
        """Read only accepted namespace bytes.

        Returns:
            Independent working evidence.
        """
        return deepcopy(self.stored)

    async def save(self, ledger: ChoiceLedger) -> None:
        """Simulate acceptance separately from the checkpoint response.

        Args:
            ledger: Proposed complete namespace.

        Raises:
            RuntimeError: The configured checkpoint fails before/after acceptance.
        """
        self.saves += 1
        self.events.append("save")
        failed = self.saves == self.fail_save
        if not failed or self.accepted:
            self.stored = deepcopy(ledger)
        if failed:
            raise RuntimeError("history save interrupted")

    async def audit_choices(self) -> tuple[ArtistChoice, ...]:
        """Read available audit evidence.

        Returns:
            Explicitly scripted completed records.
        """
        return self.audits

    async def playlist(self, playlist_id: str) -> tuple[str | None, ...]:
        """Read actual membership without replaying an append.

        Args:
            playlist_id: Destination retained in the pending evidence.

        Returns:
            Complete observed raw membership.
        """
        assert playlist_id == "destination"
        self.events.append("recover-read")
        return self.tracks


@dataclass(frozen=True)
class ChoiceEffects(MemoryOld):
    """Apply real simulated playlist effects over the original typed workflow fake.

    Args:
        storage: Independent accepted state and playlist facts.
        outcome: Scripted append failure boundary.
        timestamp: Effective invocation timestamp.
        selection: Complete ordered tracks selected by the scripted catalog.
    """

    storage: MemoryChoiceAccess
    outcome: AppendOutcome = "normal"
    timestamp: datetime = NOW
    selection: tuple[SelectedTrack, ...] = (TRACK,)

    def clock(self) -> datetime:
        """Read the fixed invocation time.

        Returns:
            Scripted effective timestamp.
        """
        return self.timestamp

    async def playlist_length(self, recheck: bool) -> int:
        """Read initial or changed membership without replacing the application guard.

        Args:
            recheck: Whether this is the last read before intent/append.

        Returns:
            Actual current length, or a concurrent nonempty observation.
        """
        if recheck and self.edge.scenario == "changed":
            return 1
        return len(self.storage.tracks)

    async def spotify_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[SelectedTrack, ...]:
        """Supply a complete catalog selection, including duplicates when scripted.

        Args:
            artist: Accepted Spotify identity.

        Returns:
            Scripted ordered track facts.
        """
        return self.selection

    async def append(self, tracks: tuple[SelectedTrack, ...]) -> None:
        """Separate accepted playlist effects from a failed response.

        Args:
            tracks: Complete ordered append.

        Raises:
            RuntimeError: Failure occurs before, during or after the append.
        """
        self.storage.events.append("append")
        if self.outcome == "before":
            raise RuntimeError("append interrupted")
        accepted = tracks[:1] if self.outcome == "partial" else tracks
        self.storage.tracks = tuple(track.spotify_id for track in accepted)
        if self.outcome != "normal":
            raise RuntimeError("append interrupted")


@dataclass
class ChoiceReader:
    """Retain exactly the history shown beside an explicit mode decision.

    Args:
        response: Current operator selection; never inferred from history.
        shown: Recorded per-mode evidence passed to the reader.
    """

    response: str = "spotify_top_tracks"
    shown: list[tuple[PreviousMode, ...]] = field(default_factory=list)

    async def choose_mode_with_history(
        self,
        artist: GoldenOldieArtist,
        mapped: SpotifyArtistCandidate,
        previous: tuple[PreviousMode, ...],
    ) -> str:
        """Observe completed evidence and return the explicitly scripted mode.

        Args:
            artist: Current historical artist.
            mapped: Current accepted Spotify identity.
            previous: Prior completed use for that identity.

        Returns:
            Explicit response, including cancellation or malformed test actions.
        """
        self.shown.append(previous)
        return self.response
