"""Protect original artist mapping controls and custom-search interaction order."""

from collections.abc import Callable
from functools import partial
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import release_check as legacy
from tests.support.artist_mapping import ARTIST
from tests.support.artist_mapping import EXACT
from tests.support.artist_mapping import OTHER
from tests.support.artist_mapping import MappingObservations


def _search(
    observed: MappingObservations,
    sp: object,
    artist: legacy.RankedArtist,
    retry: object,
    text: str | None = None,
) -> tuple[legacy.SpotifyArtistCandidate, ...]:
    return observed.search(artist, text)


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


def _run(
    monkeypatch: pytest.MonkeyPatch,
    observed: MappingObservations,
    interactive: bool = True,
) -> legacy.SpotifyArtistCandidate | str | None:
    monkeypatch.setattr(legacy, "search_spotify_artists", partial(_search, observed))
    return legacy.resolve_spotify_artist(
        cast(Spotify, object()),
        ARTIST,
        observed.choose if interactive else None,
        _immediate,
    )


def test_original_unique_exact_is_automatic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain initial exact-only automatic selection before interaction.

    Args:
        monkeypatch: Scoped original search substitution.
    """
    observed = MappingObservations([(OTHER, EXACT)])
    assert _run(monkeypatch, observed) is EXACT
    assert observed.searches == [None] and observed.prompts == []


def test_original_noninteractive_empty_is_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the original empty initial search result without a prompt.

    Args:
        monkeypatch: Scoped original search substitution.
    """
    observed = MappingObservations([()])
    assert _run(monkeypatch, observed, False) is None
    assert observed.searches == [None]


@pytest.mark.parametrize("choices", [(OTHER,), (EXACT, EXACT)])
def test_original_noninteractive_ambiguity(
    monkeypatch: pytest.MonkeyPatch, choices: tuple[legacy.SpotifyArtistCandidate, ...]
) -> None:
    """Retain ambiguity even for a single nonexact candidate or repeated exact identity.

    Args:
        monkeypatch: Scoped original search substitution.
        choices: Original ambiguous search observations.
    """
    observed = MappingObservations([choices])
    with pytest.raises(
        legacy.ReleaseCheckSpotifyError, match="mapping is ambiguous for Artist"
    ):
        _run(monkeypatch, observed, False)
    assert observed.searches == [None] and observed.prompts == []


@pytest.mark.parametrize("choice", ["skip", "skip-artist", "quit"])
def test_original_mapping_controls(
    monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    """Retain all original controls on an empty interactive prompt.

    Args:
        monkeypatch: Scoped original search substitution.
        choice: Original mapping control.
    """
    observed = MappingObservations([()], [choice])
    assert _run(monkeypatch, observed) == choice
    assert observed.prompts == [()]


def test_original_custom_search_is_trimmed_and_still_prompts_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain custom searches and require an explicit choice after a custom query.

    Args:
        monkeypatch: Scoped original search substitution.
    """
    observed = MappingObservations(
        [(), (OTHER, EXACT)], ["search:  custom text  ", "exact"]
    )
    assert _run(monkeypatch, observed) is EXACT
    assert observed.searches == [None, "custom text"]
    assert observed.prompts == [(), ("other", "exact")]


def test_original_exact_prompt_excludes_nonexact_and_selects_first_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain initial exact-only prompts and first matching identity.

    Args:
        monkeypatch: Scoped original search substitution.
    """
    observed = MappingObservations([(OTHER, EXACT, EXACT)], ["exact"])
    assert _run(monkeypatch, observed) is EXACT
    assert observed.prompts == [("exact", "exact")]


@pytest.mark.parametrize(
    "choice,message",
    [
        ("search: ", "custom Spotify artist search cannot be empty"),
        ("missing", "selected Spotify artist is invalid"),
    ],
)
def test_original_mapping_errors(
    monkeypatch: pytest.MonkeyPatch, choice: str, message: str
) -> None:
    """Retain one-shot response validation before any subsequent search.

    Args:
        monkeypatch: Scoped original search substitution.
        choice: Original invalid response.
        message: Original narrowed error message.
    """
    observed = MappingObservations([(OTHER,)], [choice])
    with pytest.raises(legacy.ReleaseCheckSpotifyError, match=message):
        _run(monkeypatch, observed)
    assert observed.searches == [None] and observed.prompts == [("other",)]
