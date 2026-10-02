"""Original legacy ordinary-exception reporting at the execution boundary."""

from types import TracebackType
from typing import Self

from spotify_manager.application.legacy_library_effects import Echo


class LegacyFailure:
    """Report and suppress the original ordinary execution failures.

    Args:
        echo: Original presenter, including failures from presentation itself.
    """

    def __init__(self, echo: Echo) -> None:
        """Bind the original execution boundary.

        Args:
            echo: Original visible presenter.
        """
        self.echo = echo
        self.failed = False

    def __enter__(self) -> Self:
        """Enter the original failure scope.

        Returns:
            The attempt's accepted failure state.
        """
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Preserve ordinary failure reporting and process-control propagation.

        Args:
            kind: Original failure type.
            error: Original failure value.
            traceback: Original failure traceback.

        Returns:
            Whether the original ordinary failure is suppressed.
        """
        if not isinstance(error, Exception):
            return False
        self.echo(error)
        self.failed = True
        return True
