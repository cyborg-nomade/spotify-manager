"""Protect the original implicit error context when progress presentation fails."""

from dataclasses import dataclass
from dataclasses import field
from typing import Never

import pytest

from spotify_manager.application.legacy_library_effects import AlbumRefresh
from spotify_manager.application.legacy_library_effects import Page
from spotify_manager.application.legacy_library_refresh import Scan
from spotify_manager.application.legacy_library_refresh import advance
from spotify_manager.infrastructure.legacy_library_errors import LegacyFailure


@dataclass
class BrokenProgress:
    """Interrupt original progress presentation before the next URL is assigned.

    Args:
        error: Original presentation failure.
        output: Original subsequent failure reporting.
    """

    error: RuntimeError
    output: list[object] = field(default_factory=list)

    def __call__(self, *values: object) -> None:
        """Raise the original progress failure and accept its subsequent report.

        Args:
            values: Original progress or failure output.

        Raises:
            RuntimeError: The original progress observation is interrupted.
        """
        first = values[0]
        if isinstance(first, str) and "/" in first:
            raise self.error
        self.output.extend(values)


def unexpected_observation(*arguments: object) -> Never:
    """Reject reads after original progress presentation has already failed.

    Args:
        arguments: Unexpected request parameters.

    Raises:
        AssertionError: Execution crosses the original failed boundary.
    """
    raise AssertionError(arguments)


def test_failed_progress_retains_native_error_context() -> None:
    """Retain native class, text, implicit context and original failure-report order."""
    original = RuntimeError("progress failed")
    echo = BrokenProgress(original)
    deps = AlbumRefresh(
        unexpected_observation,
        unexpected_observation,
        unexpected_observation,
        unexpected_observation,
        unexpected_observation,
        unexpected_observation,
        unexpected_observation,
    )
    page: Page = {"items": [], "next": "more", "offset": 0, "total": 10}
    with pytest.raises(UnboundLocalError, match="last_next") as raised:
        advance(Scan(page, 1, 0), [], deps, echo, LegacyFailure)
    assert raised.value.__context__ is original and raised.value.__cause__ is None
    assert echo.output == [original]
