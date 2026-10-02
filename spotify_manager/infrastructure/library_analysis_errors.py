"""Preserve original public analysis error translation and audit classification."""

from dataclasses import dataclass
from types import TracebackType
from typing import Literal
from typing import Self

from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.domain.library_analysis_values import LibrarySyncError


@dataclass(frozen=True)
class AnalysisFailure:
    """Report original public-run failures after the checkpoint-opening boundary.

    The original public API translates arbitrary callback exceptions. This context
    retains that boundary without broad exception handlers in the business stages.

    Args:
        session: Original invocation and accepted audit authority.
        label: Original operation-specific failure prefix.
        paused: Original exception classes classified as a resumable pause.
    """

    session: AnalysisSession
    label: str
    paused: tuple[type[BaseException], ...]

    def __enter__(self) -> Self:
        """Open the original post-checkpoint error reporting boundary.

        Returns:
            The current reporting boundary.
        """
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Retain original pause/failure audits, causes and native propagation.

        Args:
            exception_type: Original escaping error class or none.
            exception: Original escaping failure or none.
            traceback: Original exception traceback.

        Returns:
            False to retain the original exception when no translation is needed.

        Raises:
            LibrarySyncError: Original public boundary translated a callback error.
        """
        if exception is None:
            return False
        if isinstance(exception, self.paused):
            self.session.event("run_paused")
            return False
        if isinstance(exception, LibrarySyncError):
            self.session.event("run_failed")
            return False
        if not isinstance(exception, Exception):
            return False
        self.session.event(
            "run_failed", error=type(exception).__name__, detail=str(exception)
        )
        raise LibrarySyncError(f"{self.label}: {exception}") from exception
