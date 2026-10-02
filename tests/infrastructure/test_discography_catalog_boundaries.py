"""Compare original raw catalog, pagination and queue grouping contracts."""

from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.infrastructure.discography_records import catalog_release
from tests.support.discography_boundaries import catalog_outcome
from tests.support.discography_boundaries import queue_outcome
from tests.support.discography_run import cases


@pytest.mark.parametrize("case", cases("discography_records.json"))
def test_discography_raw_records_keep_original_tolerance(
    case: dict[str, object],
) -> None:
    """Preserve complete original primary-credit and optional-release parsing.

    Args:
        case: Original immutable raw record and parsed fields.
    """
    parsed = catalog_release(case["raw"], "artist")
    assert (asdict(parsed) if parsed else None) == case["result"]


@pytest.mark.parametrize("case", cases("discography_catalog.json"))
def test_discography_catalog_keeps_original_read_and_canonical_order(
    case: dict[str, object],
) -> None:
    """Preserve raw offsets, complete saved batches and preferred edition chronology.

    Args:
        case: Original immutable page and saved-response profile.
    """
    assert catalog_outcome(cast(str, case["profile"])) == case["outcome"]


@pytest.mark.parametrize("case", cases("discography_queues.json"))
def test_discography_queue_gathering_keeps_original_order(
    case: dict[str, object],
) -> None:
    """Preserve first display names, unique URI order and optional empty playlist IDs.

    Args:
        case: Original immutable auxiliary source and failure input.
    """
    assert (
        queue_outcome(
            cast(str | None, case["extra"]), cast(str | None, case["failure"])
        )
        == case["outcome"]
    )
