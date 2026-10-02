"""Replace editable genre progress while preserving identical-state idempotency."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class GenreProgress:
    """Validated original genre progress and its server metadata.

    Args:
        completed: Original ordered completed identities.
        hide_done: Original visibility setting.
        version: Original persisted schema version.
        updated_at: Original last accepted progress timestamp.
    """

    completed: tuple[str, ...]
    hide_done: bool
    version: int = 1
    updated_at: datetime | None = None


class GenreProgressEffects(Protocol):
    """Observe authoritative progress and accept timestamped changes."""

    def read(self) -> GenreProgress:
        """Read and validate the latest original progress.

        Returns:
            Current original progress and metadata.
        """

    def clock(self) -> datetime:
        """Read the original update clock only when editable fields change.

        Returns:
            Original current UTC timestamp.
        """

    def save(self, state: GenreProgress) -> None:
        """Present and accept changed progress through the original state handle.

        Args:
            state: Original complete timestamped replacement.
        """


@dataclass(frozen=True)
class UpdateGenreProgress:
    """Keep identical updates free of new timestamps, backups and state writes.

    Args:
        effects: Original latest-state, clock and accepted-save boundaries.
    """

    effects: GenreProgressEffects

    def run(self, completed: tuple[str, ...], hide_done: bool) -> GenreProgress:
        """Replace editable fields only when they differ from current progress.

        Args:
            completed: Original validated ordered completed identities.
            hide_done: Original desired visibility setting.

        Returns:
            Original current metadata or the accepted timestamped replacement.
        """
        previous = self.effects.read()
        if previous.completed == completed and previous.hide_done == hide_done:
            return previous
        state = GenreProgress(completed, hide_done, updated_at=self.effects.clock())
        self.effects.save(state)
        return state
