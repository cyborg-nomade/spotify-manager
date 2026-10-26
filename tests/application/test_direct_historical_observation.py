"""Protect the original direct callback result and unmodified failure propagation."""

from typing import Never

import pytest

from spotify_manager.application.ports.runtime import NoRetry


def observation() -> object:
    """Return the independently supplied original observation.

    Returns:
        Original callback value.
    """
    return "observed"


def interrupted() -> Never:
    """Raise the original callback failure.

    Raises:
        RuntimeError: The selected observation is interrupted.
    """
    raise RuntimeError("interrupted")


def test_direct_observation_retains_result_and_failure() -> None:
    """Keep the description passive and propagate the original observation failure."""
    for attempt in NoRetry().attempts("reading"):
        with attempt:
            assert observation() == "observed"
    with pytest.raises(RuntimeError, match="interrupted"):
        _interrupted_without_retry()


def _interrupted_without_retry() -> None:
    for attempt in NoRetry().attempts("reading"):
        with attempt:
            interrupted()
