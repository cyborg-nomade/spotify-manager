"""Run artist mapping independently with original controls and custom-search order."""

import pytest

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from tests.support.artist_mapping import ARTIST
from tests.support.artist_mapping import EXACT
from tests.support.artist_mapping import OTHER
from tests.support.artist_mapping import MappingObservations


def _run(
    observed: MappingObservations, interactive: bool = True
) -> SpotifyArtistCandidate | str | None:
    return ArtistMapping(observed.search, observed.choose if interactive else None).run(
        ARTIST
    )


def test_mapping_unique_exact_is_automatic() -> None:
    """Retain initial exact-only automatic selection before interaction."""
    observed = MappingObservations([(OTHER, EXACT)])
    assert _run(observed) is EXACT
    assert observed.searches == [None] and observed.prompts == []


def test_mapping_noninteractive_empty_is_unmapped() -> None:
    """Retain the original empty initial search result without a prompt."""
    observed = MappingObservations([()])
    assert _run(observed, False) is None
    assert observed.searches == [None]


@pytest.mark.parametrize("choices", [(OTHER,), (EXACT, EXACT)])
def test_mapping_noninteractive_ambiguity(
    choices: tuple[SpotifyArtistCandidate, ...],
) -> None:
    """Retain ambiguity even for a single nonexact candidate or repeated exact identity.

    Args:
        choices: Original ambiguous search observations.
    """
    observed = MappingObservations([choices])
    with pytest.raises(
        ReleaseCheckSpotifyError, match="mapping is ambiguous for Artist"
    ):
        _run(observed, False)
    assert observed.searches == [None] and observed.prompts == []


@pytest.mark.parametrize("choice", ["skip", "skip-artist", "quit"])
def test_mapping_mapping_controls(choice: str) -> None:
    """Retain all original controls on an empty interactive prompt.

    Args:
        choice: Original mapping control.
    """
    observed = MappingObservations([()], [choice])
    assert _run(observed) == choice
    assert observed.prompts == [()]


def test_mapping_custom_search_is_trimmed_and_still_prompts_exact() -> None:
    """Retain custom searches and require an explicit choice after a custom query."""
    observed = MappingObservations(
        [(), (OTHER, EXACT)], ["search:  custom text  ", "exact"]
    )
    assert _run(observed) is EXACT
    assert observed.searches == [None, "custom text"]
    assert observed.prompts == [(), ("other", "exact")]


def test_mapping_exact_prompt_excludes_nonexact_and_selects_first_duplicate() -> None:
    """Retain initial exact-only prompts and first matching identity."""
    observed = MappingObservations([(OTHER, EXACT, EXACT)], ["exact"])
    assert _run(observed) is EXACT
    assert observed.prompts == [("exact", "exact")]


@pytest.mark.parametrize(
    "choice,message",
    [
        ("search: ", "custom Spotify artist search cannot be empty"),
        ("missing", "selected Spotify artist is invalid"),
    ],
)
def test_mapping_mapping_errors(choice: str, message: str) -> None:
    """Retain one-shot response validation before any subsequent search.

    Args:
        choice: Original invalid response.
        message: Original narrowed error message.
    """
    observed = MappingObservations([(OTHER,)], [choice])
    with pytest.raises(ReleaseCheckSpotifyError, match=message):
        _run(observed)
    assert observed.searches == [None] and observed.prompts == [("other",)]


def test_release_summary_counts_original_preview_and_real_actions() -> None:
    """Count original planned/accepted additions and exclude other outcomes."""
    from dataclasses import replace
    from datetime import date

    from spotify_manager.application.release_check_values import ReleaseCheckSummary
    from spotify_manager.domain.release_check_values import ReleaseCheckResult

    selected = ReleaseCheckResult(
        "Artist",
        1,
        100,
        "artist",
        "release",
        "Album",
        "Album",
        "2026",
        None,
        None,
        None,
        "would add",
        "added",
        None,
        True,
    )
    skipped = replace(
        selected,
        wine_cellar_action="already present",
        new_vintage_action="not applicable",
    )
    summary = ReleaseCheckSummary(
        "run",
        date(2026, 1, 1),
        date(2026, 9, 25),
        1,
        1,
        True,
        False,
        False,
        0,
        None,
        (selected, skipped),
    )
    assert summary.wine_cellar_added == summary.new_vintage_added == 1
