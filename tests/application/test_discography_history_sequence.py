"""Retain original history, calendar, random and seconds selection traces."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.discography_history import DiscographyArtistMapping
from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.discography_values import DiscographyCancelledError
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from tests.support.discography_boundaries import history_outcome
from tests.support.discography_run import HISTORY_INPUT_PATH
from tests.support.discography_run import cases
from tests.support.discography_run import historical
from tests.support.palace_history import HistoryInputs
from tests.support.palace_history import HistoryReads


def _cutoff() -> date:
    return date(2025, 12, 31)


async def test_history_reader_receives_the_supplied_path(tmp_path: Path) -> None:
    """Keep path forwarding covered independently of the fixed historical input.

    Args:
        tmp_path: Arbitrary fake history input, never read from disk.
    """
    path = tmp_path / "custom-history"
    outcome = await _outcome("normal", 1, path)
    assert isinstance(outcome, dict)
    assert ["history", str(path)] in outcome["trace"]


async def _outcome(
    profile: str, second: int, path: Path = HISTORY_INPUT_PATH
) -> object:
    edge = HistoryReads(profile, second)
    owner = DiscographyHistory(
        HistoryInputs(edge, path, _cutoff()),
        edge,
        date(2007, 11, 27),
    )
    result: dict[str, object] = {}
    try:
        result["result"] = asdict(await owner.run())
    except (RuntimeError, IndexError) as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("case", cases("discography_history.json"))
async def test_discography_history_matches_original_complete_observations(
    case: dict[str, object],
) -> None:
    """Compare complete selections and original malformed-reader error prefixes.

    Args:
        case: Original immutable history and random input.
    """
    profile, second = cast(str, case["profile"]), cast(int, case["second"])
    assert (await _outcome(profile, second)) == case["outcome"]
    assert (await history_outcome(profile, second)) == case["outcome"]


def _mapping(profile: str, name: str) -> SpotifyArtistCandidate | None:
    assert name == "Past"
    if profile == "error":
        raise SomethingOldError("mapping failed")
    if profile == "cancel":
        return None
    return SpotifyArtistCandidate("past", "Past", "uri", 9, 4, 2)


@dataclass(frozen=True)
class MappingCase:
    """Supply one original scripted external artist mapping.

    Args:
        profile: Original success, failure or cancellation case.
    """

    profile: str

    async def resolve(self, name: str) -> SpotifyArtistCandidate | None:
        """Return the original external mapping outcome.

        Args:
            name: Original historical artist name.

        Returns:
            Original accepted identity or cancellation.
        """
        return _mapping(self.profile, name)


@pytest.mark.parametrize("profile", ["normal", "error", "cancel"])
async def test_discography_mapping_keeps_original_translation_and_cancellation(
    profile: str,
) -> None:
    """Retain exact mapped facts and original error identity/message.

    Args:
        profile: Original successful, failed or cancelled mapping.
    """
    catalog = MappingCase(profile)
    if profile == "normal":
        candidate = await DiscographyArtistMapping(catalog).resolve(historical())
        assert (candidate.spotify_id, candidate.name, candidate.queue) == (
            "past",
            "Past",
            "memory_lane",
        )
        return
    error = DiscographyCancelledError if profile == "cancel" else DiscographyError
    with pytest.raises(error):
        (await DiscographyArtistMapping(catalog).resolve(historical()))
