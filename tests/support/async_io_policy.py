"""Exact reviewed blocking I/O calls required by the standard thread bridge."""

import json
from pathlib import Path
from typing import cast


def async_io_reasons() -> dict[tuple[str, str], str]:
    """Read the explicit owner, method and resource reason for each worker call.

    Returns:
        Reviewed call sites; a new owner or method requires its own explanation.

    Raises:
        OSError: The reviewed ledger cannot be read.
        ValueError: The ledger is not valid JSON.
    """
    path = (
        Path(__file__).parents[1] / "async_execution/fixtures/async_io_boundaries.json"
    )
    rows = cast(list[dict[str, str]], json.loads(path.read_text()))
    reasons = {}
    for row in rows:
        reasons[(row["owner"], row["function"])] = row["reason"]
    return reasons


ASYNC_IO_REASONS = async_io_reasons()
