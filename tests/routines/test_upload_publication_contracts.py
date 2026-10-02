"""Replay original local/remote publication failures and subsequent retries."""

import json
from pathlib import Path

import pytest

from tests.support.upload_run import UploadScenario
from tests.support.upload_run import observe_upload
from tests.support.upload_run import upload_scenarios


ORIGINAL = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/refactor/upload_publication.json"
    ).read_text()
)


@pytest.mark.parametrize("index,scenario", list(enumerate(upload_scenarios())))
def test_upload_publication_contract(
    index: int, scenario: UploadScenario, tmp_path: Path
) -> None:
    """Retain accepted effects, original failures and retry cleanup.

    Args:
        index: Original immutable scenario index.
        scenario: Selected publication boundary.
        tmp_path: Isolated managed directory.
    """
    assert observe_upload(scenario, tmp_path) == ORIGINAL[index]
