"""Original Sauvignon choice ordering and first matching edition identity."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.routines import sauvignon
from tests.routines.test_sauvignon import album_option
from tests.routines.test_sauvignon import recommendation


@dataclass
class ChoiceSteps:
    """Observe the original edition interaction once for ambiguous metadata.

    Args:
        response: Original operator choice.
        failure: Whether the original interaction raises.
        calls: Original recommendation and ordered option observations.
    """

    response: str = "second"
    failure: bool = False
    calls: list[
        tuple[sauvignon.AlbumRecommendation, tuple[sauvignon.SpotifyAlbumOption, ...]]
    ] = field(default_factory=list)

    def choose(
        self,
        item: sauvignon.AlbumRecommendation,
        options: tuple[sauvignon.SpotifyAlbumOption, ...],
    ) -> str:
        """Read the original choice after observing all ambiguous editions.

        Args:
            item: Original ranked recommendation.
            options: Original ordered preferred editions.

        Returns:
            Configured original choice.

        Raises:
            OSError: The original interaction fails.
        """
        self.calls.append((item, options))
        if self.failure:
            raise OSError("choice failed")
        return self.response


def _ambiguous() -> sauvignon.AlbumRecommendation:
    options = (
        album_option(spotify_id="first"),
        album_option(spotify_id="second", release_date="2025"),
    )
    return recommendation(options=options)


@pytest.mark.parametrize(
    "response,expected",
    [
        ("second", "second"),
        ("unknown", "skip"),
        (sauvignon.CHOICE_SKIP, "skip"),
        (sauvignon.CHOICE_QUIT, "quit"),
    ],
)
def test_original_ambiguous_choice_results(response: str, expected: str) -> None:
    """Keep exact skip, quit, selected identity and invalid-choice tolerance.

    Args:
        response: Original operator response.
        expected: Original selected identity or action.
    """
    item = _ambiguous()
    steps = ChoiceSteps(response)
    result = sauvignon.choose_album_option(item, steps.choose)
    assert (
        result.spotify_id
        if isinstance(result, sauvignon.SpotifyAlbumOption)
        else result
    ) == expected
    assert steps.calls == [(item, item.options)]


def test_original_empty_and_equivalent_options_never_prompt() -> None:
    """Empty options skip and equivalent editions choose the first observation."""
    steps = ChoiceSteps(failure=True)
    first = album_option(spotify_id="first")
    item = recommendation(options=(first, replace(first, spotify_id="second")))
    assert sauvignon.choose_album_option(item, steps.choose) is first
    assert (
        sauvignon.choose_album_option(replace(item, options=()), steps.choose) == "skip"
    )
    assert steps.calls == []


def test_original_missing_reader_skips_ambiguous_options() -> None:
    """Preserve noninteractive ambiguity without guessing a preferred edition."""
    assert sauvignon.choose_album_option(_ambiguous(), None) == "skip"


def test_original_duplicate_edition_identity_selects_first_matching_option() -> None:
    """A selected identity keeps its first ambiguous observation."""
    item = _ambiguous()
    options = tuple(replace(option, spotify_id="same") for option in item.options)
    item = replace(item, options=options)
    assert sauvignon.choose_album_option(item, ChoiceSteps("same").choose) is options[0]


def test_original_choice_exception_propagates_without_retry_or_translation() -> None:
    """An interrupted interaction is observed once and keeps its original exception."""
    steps = ChoiceSteps(failure=True)
    with pytest.raises(OSError, match="choice failed"):
        sauvignon.choose_album_option(_ambiguous(), steps.choose)
    assert len(steps.calls) == 1
