"""Independent automatic edition selection and original interaction boundaries."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.album_recommendations import choose_album
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from tests.support.album_evidence import read_case


@dataclass
class ChoiceMemory:
    """Read original operator responses without UI or runtime configuration.

    Args:
        response: Original operator response.
        failure: Whether the injected interaction fails.
        calls: Observed recommendation and ordered preferred editions.
    """

    response: str = "second"
    failure: bool = False
    calls: list[tuple[AlbumRecommendation, tuple[SpotifyAlbumOption, ...]]] = field(
        default_factory=list
    )

    def read(
        self,
        recommendation: AlbumRecommendation,
        options: tuple[SpotifyAlbumOption, ...],
    ) -> str:
        """Observe one original ambiguous-edition interaction.

        Args:
            recommendation: Original ranked evidence.
            options: Original ordered preferred editions.

        Returns:
            Original configured response.

        Raises:
            OSError: The injected interaction fails.
        """
        self.calls.append((recommendation, options))
        if self.failure:
            raise OSError("choice interrupted")
        return self.response


def _recommendation(ambiguous: bool = True) -> AlbumRecommendation:
    option = read_case("duplicates").observations["Same"][0]
    second = replace(
        option,
        spotify_id="second",
        release_date="2025" if ambiguous else option.release_date,
    )
    return AlbumRecommendation(
        option.artist, option.album, ("artist", "album"), 1, 1, (), (option, second)
    )


def _choose(
    item: AlbumRecommendation, memory: ChoiceMemory | None
) -> SpotifyAlbumOption | str:
    return choose_album(
        item, memory.read if memory is not None else None, "skip-marker", "quit-marker"
    )


@pytest.mark.parametrize(
    "response,expected",
    [
        ("second", "second"),
        ("unknown", "skip"),
        ("skip-marker", "skip"),
        ("quit-marker", "quit"),
    ],
)
def test_ambiguous_choice_preserves_selected_identity_and_response_markers(
    response: str, expected: str
) -> None:
    """Observe one interaction and retain original selected or skipped outcomes.

    Args:
        response: Original operator response.
        expected: Original selected identity or action.
    """
    memory = ChoiceMemory(response)
    item = _recommendation()
    result = _choose(item, memory)
    assert (
        result.spotify_id if isinstance(result, SpotifyAlbumOption) else result
    ) == expected
    assert memory.calls == [(item, item.options)]


def test_empty_equivalent_and_noninteractive_cases_preserve_original_guards() -> None:
    """Do not invoke an interaction for empty or equivalent visible editions."""
    memory = ChoiceMemory(failure=True)
    item = _recommendation(False)
    assert _choose(item, memory) is item.options[0]
    assert _choose(replace(item, options=()), memory) == "skip"
    assert _choose(_recommendation(), None) == "skip"
    assert memory.calls == []


def test_duplicate_selected_identity_retains_first_option() -> None:
    """Do not reorder ambiguous editions that share the selected original identity."""
    item = _recommendation()
    options = tuple(replace(option, spotify_id="same") for option in item.options)
    item = replace(item, options=options)
    assert _choose(item, ChoiceMemory("same")) is options[0]


def test_response_markers_precede_matching_option_identities() -> None:
    """Preserve original marker precedence for permissive constructed identities."""
    item = _recommendation()
    option = replace(item.options[0], spotify_id="skip-marker")
    item = replace(item, options=(option, item.options[1]))
    assert _choose(item, ChoiceMemory("skip-marker")) == "skip"


def test_interaction_failure_propagates_after_one_observation() -> None:
    """Keep the injected interaction's original exception and single-call boundary."""
    memory = ChoiceMemory(failure=True)
    with pytest.raises(OSError, match="choice interrupted"):
        _choose(_recommendation(), memory)
    assert len(memory.calls) == 1
