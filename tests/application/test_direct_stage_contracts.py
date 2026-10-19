"""Protect real stage composition, operator context and preview persistence."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.checkpoints import NamespaceCheckpoint
from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.new_year_discoveries import AnnualDiscoveryInputs
from spotify_manager.application.queue_3_import import AnnualDiscoveryImport
from spotify_manager.application.queue_artist_mapping import QueueArtistMapping
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.release_check_values import RankedArtist
from tests.application.test_queue_3_annual_import import ImportMemory
from tests.support.artist_mapping import EXACT
from tests.support.artist_mapping import OTHER


RECOMMENDATION = ArtistRecommendation("Artist", "artist", 2.0, 0.9, ("Seed",), 3, 1)


@dataclass
class MappingMemory:
    """Observe external mapping queries and the original Queue prompt context.

    Args:
        responses: Original ordered catalog observations.
        choices: Original one-shot operator responses.
        events: Accepted query and prompt observations.
    """

    responses: list[tuple[SpotifyArtistCandidate, ...]]
    choices: list[str] = field(default_factory=list)
    events: list[tuple[str, object]] = field(default_factory=list)

    def search(
        self, artist: RankedArtist, text: str | None
    ) -> tuple[SpotifyArtistCandidate, ...]:
        """Observe a query using the original recommendation's rank and identity.

        Args:
            artist: Application mapping input built from Queue evidence.
            text: Original optional custom query.

        Returns:
            Next scripted catalog observation.
        """
        assert artist == RankedArtist("artist", "Artist", 0, 3)
        self.events.append(("search", text))
        return self.responses.pop(0)

    def choose(
        self,
        recommendation: ArtistRecommendation,
        candidates: tuple[SpotifyArtistCandidate, ...],
    ) -> str:
        """Observe the unchanged Queue context after custom searches.

        Args:
            recommendation: Original recommendation object.
            candidates: Original eligible choices in encounter order.

        Returns:
            Next original operator response.
        """
        assert recommendation is RECOMMENDATION
        self.events.append(("choice", tuple(item.spotify_id for item in candidates)))
        return self.choices.pop(0)


def test_queue_mapping_automatic_exact_match_requires_no_operator() -> None:
    """Preserve automatic selection and original rank metadata without a prompt."""
    memory = MappingMemory([(EXACT,)])
    assert QueueArtistMapping(memory, None).resolve(RECOMMENDATION) is EXACT
    assert memory.events == [("search", None)]


def test_queue_mapping_custom_search_retains_original_prompt_context() -> None:
    """Keep the Queue recommendation while asking the shared mapping use case."""
    memory = MappingMemory([(OTHER,), (EXACT,)], ["search: custom", "exact"])
    assert QueueArtistMapping(memory, memory.choose).resolve(RECOMMENDATION) is EXACT
    assert memory.events == [
        ("search", None),
        ("choice", ("other",)),
        ("search", "custom"),
        ("choice", ("exact",)),
    ]


@dataclass
class CheckpointMemory:
    """Observe complete namespace writes independently of the application.

    Args:
        saved: Original namespaces accepted by storage.
    """

    saved: list[dict[str, object]] = field(default_factory=list)

    def save(self, state: dict[str, object]) -> None:
        """Accept a complete namespace at its original checkpoint boundary.

        Args:
            state: Original mutable namespace.
        """
        self.saved.append(state)


@pytest.mark.parametrize("preview", [False, True])
def test_preference_checkpoint_retains_namespace_identity_and_preview_rule(
    preview: bool,
) -> None:
    """A preview cannot persist ordering or skip preferences.

    Args:
        preview: Original durable write suppression.
    """
    memory = CheckpointMemory()
    state: dict[str, object] = {"unknown": "retained"}
    NamespaceCheckpoint(memory, state, preview).save()
    assert memory.saved == ([] if preview else [state])
    if not preview:
        assert memory.saved[0] is state


@dataclass
class AnnualMemory:
    """Observe annual source acquisition and standalone import presentation.

    Args:
        inputs: Original already-completed import authority.
        events: Ordered external observations.
    """

    inputs: AnnualDiscoveryInputs
    events: list[tuple[str, object]] = field(default_factory=list)

    def discovery_inputs(self, preview: bool) -> AnnualDiscoveryInputs:
        """Observe the original import inputs after loading presentation.

        Args:
            preview: Original namespace clone behavior.

        Returns:
            Original completed import authority and resources.
        """
        self.events.append(("inputs", preview))
        return self.inputs

    def loading(self, year: int) -> None:
        """Present the original source year before observations.

        Args:
            year: Original previous-year source.
        """
        self.events.append(("loading", year))

    def already_imported(self, year: int) -> None:
        """Present original accepted completion authority.

        Args:
            year: Original previous-year source.
        """
        self.events.append(("already", year))

    def checked(self, year: int, already_completed: bool) -> None:
        """Present the original final standalone import progress.

        Args:
            year: Original source year.
            already_completed: Original completion acknowledgment.
        """
        self.events.append(("checked", (year, already_completed)))


@pytest.mark.parametrize("preview", [False, True])
def test_retrospective_import_honors_completed_authority_without_more_effects(
    preview: bool,
) -> None:
    """Retain standalone import progress and avoid duplicate imports or checkpoints.

    Args:
        preview: Original preview acquisition behavior.
    """
    imports = ImportMemory()
    importer = AnnualDiscoveryImport(imports, imports, imports.present, imports.now)
    state: dict[str, object] = {"annual_imports": {"2026": {"completed": True}}}
    inputs = AnnualDiscoveryInputs("queue", [], state, (), importer)
    memory = AnnualMemory(inputs)
    AnnualDiscoveries(memory, memory).run(2026, preview)
    assert memory.events == [
        ("loading", 2025),
        ("inputs", preview),
        ("already", 2025),
        ("checked", (2025, True)),
    ]
    assert imports.events == []
    assert inputs.state is state
