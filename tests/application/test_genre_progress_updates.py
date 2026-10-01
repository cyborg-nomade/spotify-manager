"""Protect original genre update idempotency and accepted-save failure ordering."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

import pytest

from spotify_manager.application.genre_progress import GenreProgress
from spotify_manager.application.genre_progress import UpdateGenreProgress


STAMP = datetime(2026, 9, 25, tzinfo=UTC)


@dataclass
class Effects:
    """Observe current metadata and record accepted replacement state.

    Args:
        current: Original authoritative progress.
        fail: Fail after accepting a changed state.
    """

    current: GenreProgress
    fail: bool = False
    events: list[str] = field(default_factory=list)
    accepted: GenreProgress | None = None

    def read(self) -> GenreProgress:
        """Read current original metadata.

        Returns:
            Configured original state.
        """
        self.events.append("read")
        return self.current

    def clock(self) -> datetime:
        """Observe the original changed-state clock.

        Returns:
            Fixed timestamp.
        """
        self.events.append("clock")
        return STAMP

    def save(self, state: GenreProgress) -> None:
        """Accept changed state before a possible later failure.

        Args:
            state: Original complete replacement.

        Raises:
            OSError: The configured accepted-save failure occurs.
        """
        self.accepted = state
        self.events.append("save")
        if self.fail:
            raise OSError("accepted save")


def test_identical_genre_update_keeps_metadata_and_performs_no_write() -> None:
    """Preserve original metadata and result identity for identical editable fields."""
    state = GenreProgress(("first",), True, updated_at=STAMP)
    effects = Effects(state)
    assert UpdateGenreProgress(effects).run(state.completed, state.hide_done) is state
    assert effects.events == ["read"] and effects.accepted is None


@pytest.mark.parametrize(
    "completed,hidden", [(("second", "first"), True), (("first",), False)]
)
def test_changed_genre_update_accepts_original_order_and_new_timestamp(
    completed: tuple[str, ...], hidden: bool
) -> None:
    """Either changed field produces one timestamped replacement after the current read.

    Args:
        completed: Desired original route identities.
        hidden: Desired original visibility setting.
    """
    effects = Effects(GenreProgress(("first",), True))
    result = UpdateGenreProgress(effects).run(completed, hidden)
    assert result == GenreProgress(completed, hidden, updated_at=STAMP)
    assert effects.events == ["read", "clock", "save"] and effects.accepted is result


def test_genre_update_failure_keeps_the_accepted_replacement() -> None:
    """An accepted-save failure preserves the replacement and propagates its error."""
    effects = Effects(GenreProgress((), False), fail=True)
    with pytest.raises(OSError, match="accepted save"):
        UpdateGenreProgress(effects).run(("first",), True)
    assert effects.events == ["read", "clock", "save"]
    assert effects.accepted == GenreProgress(("first",), True, updated_at=STAMP)
