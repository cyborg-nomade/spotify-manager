"""Protect the original direct callback result and unmodified failure propagation."""

from typing import Never

import pytest

from spotify_manager.application.historical_resolution import direct_call


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
    assert direct_call(observation, "reading") == "observed"
    with pytest.raises(RuntimeError, match="interrupted"):
        direct_call(interrupted, "reading")
