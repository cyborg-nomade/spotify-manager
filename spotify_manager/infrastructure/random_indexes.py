"""Original Random.org response validation and timestamp normalization."""

import re
from collections.abc import Callable
from datetime import UTC
from datetime import datetime

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.application.historical_values import RandomOrgError


def indexes(body: str, population: int, count: int) -> tuple[int, ...]:
    """Parse the original unique bounded integer set after textual service errors.

    Args:
        body: Original decoded service response.
        population: Original requested population.
        count: Original requested distinct count.

    Returns:
        Original ordered zero-based indexes.

    Raises:
        RandomOrgError: Original error, count, duplicate or bound validation fails.
    """
    if "Error:" in body:
        raise RandomOrgError(
            f"Random.org could not generate indexes: {_error_line(body)}"
        )
    values = tuple(int(value) for value in re.findall(r"-?\d+", body))
    if len(values) != count:
        raise RandomOrgError(
            f"Random.org returned {len(values)} indexes; expected {count}."
        )
    if len(set(values)) != count:
        raise RandomOrgError("Random.org returned duplicate date indexes.")
    if any(value < 0 or value >= population for value in values):
        raise RandomOrgError("Random.org returned an out-of-range date index.")
    return values


def _error_line(body: str) -> str:
    for line in body.splitlines():
        if "Error:" in line:
            return line.strip()
    return body


def result(
    body: str,
    header: str | None,
    population: int,
    count: int,
    parse_time: Callable[[str], datetime],
) -> RandomIndexSet:
    """Retain original index validation before the service timestamp observation.

    Args:
        body: Original decoded integer response.
        header: Original server Date header.
        population: Original population bound.
        count: Original requested count.
        parse_time: Original RFC timestamp codec seam.

    Returns:
        Original distinct indexes and shared UTC observation time.

    Raises:
        RandomOrgError: Original indexes or timestamp fail validation.
    """
    selected = indexes(body, population, count)
    if not header:
        raise RandomOrgError("Random.org response did not include a timestamp.")
    try:
        generated = parse_time(header)
    except (TypeError, ValueError) as error:
        raise RandomOrgError(
            f"Random.org returned an invalid timestamp: {header}"
        ) from error
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    return RandomIndexSet(selected, generated.astimezone(UTC))
