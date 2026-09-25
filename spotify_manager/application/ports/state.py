"""Storage port for the single shared state document."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol


if TYPE_CHECKING:
    from spotify_manager.core.state.models import StateSnapshot


class StateStore(Protocol):
    """Read and compare-and-swap one versioned JSON document."""

    def read(self) -> StateSnapshot:
        """Read a detached document and its immutable revision.

        Returns:
            The existing validated state snapshot.

        Raises:
            StateError: Storage or document validation fails.
        """

    def write(
        self,
        document: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> StateSnapshot:
        """Replace state only when the store still has the expected revision.

        Args:
            document: Complete validated shared-state document.
            expected_revision: Revision observed before this write.
            message: Existing audit or commit description.

        Returns:
            The committed snapshot with its new revision.

        Raises:
            StateConflictError: A peer committed since the document was read.
            StateError: Storage or validation fails.
        """


class RoutineState(Protocol):
    """Existing routine namespace contract, retaining its JSON boundary typing.

    Any remains here for compatibility with heterogeneous, versioned legacy JSON
    and its validators. New music ports exchange typed values instead.
    """

    def load(self) -> dict[str, Any]:
        """Load this routine's validated state.

        Returns:
            A detached namespace object with its existing schema.

        Raises:
            StateError: The namespace cannot be read or validated.
        """

    def save(
        self,
        value: dict[str, Any],
        *,
        message: str | None = None,
    ) -> object:
        """Persist this routine's complete state.

        Args:
            value: Complete namespace object validated by the existing routine.
            message: Optional commit description.

        Returns:
            The original store result, which callers need not inspect.

        Raises:
            StateError: Validation, persistence, or conflict handling fails.
        """
