"""Retain original genre state presentation, timestamp and accepted-save seams."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

from spotify_manager.application.genre_progress import GenreProgress
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.routines import genre_reveal as legacy


@dataclass
class LegacyGenreProgress:
    """Bind authoritative state and retain the original presented result instance.

    Args:
        state: Original acquired state handle.
    """

    state: RoutineState
    result: legacy.GenreRevealState = field(init=False)

    def read(self) -> GenreProgress:
        """Validate the latest original progress before comparing editable fields.

        Returns:
            Typed original ordered identities, setting and server metadata.
        """
        self.result = legacy.GenreRevealState.model_validate(self.state.load())
        return GenreProgress(
            tuple(self.result.completed),
            self.result.hide_done,
            self.result.version,
            self.result.updated_at,
        )

    def clock(self) -> datetime:
        """Retain the original clock after detecting changed editable fields.

        Returns:
            Original current UTC time.
        """
        return legacy.datetime.now(UTC)

    def save(self, state: GenreProgress) -> None:
        """Construct original presented state before accepting its serialized write.

        Args:
            state: Original timestamped replacement.
        """
        self.result = legacy.GenreRevealState(
            completed=list(state.completed),
            hide_done=state.hide_done,
            updated_at=state.updated_at,
        )
        self.state.save(self.result.model_dump(mode="json"))
