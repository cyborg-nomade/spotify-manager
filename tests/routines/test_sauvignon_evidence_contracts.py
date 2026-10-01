"""Original Sauvignon album grouping, ranking and sequential observations."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import found_art
from spotify_manager.routines import sauvignon
from tests.routines.test_sauvignon import album_option
from tests.routines.test_sauvignon import immediate
from tests.routines.test_sauvignon import track_candidate


WEEK = date(2026, 8, 7)
FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/sauvignon_evidence.json"
)


@dataclass(frozen=True)
class EvidenceCase:
    """Original ordered track observations and album exclusions for one snapshot.

    Args:
        candidates: Original ranked track pool.
        observations: Original ordered eligible Spotify album observations.
        excluded: Original heard or previously added album keys.
        existing: Original represented destination album identities.
        maximum: Original Python-slice limit on considered tracks.
    """

    candidates: tuple[found_art.FoundArtCandidate, ...]
    observations: dict[str, tuple[sauvignon.SpotifyAlbumOption, ...]]
    excluded: set[sauvignon.AlbumKey] = field(default_factory=set)
    existing: set[str] = field(default_factory=set)
    maximum: int = 10


def _grouped_case() -> EvidenceCase:
    first = replace(album_option(spotify_id="plain"), track_similarity=0.8)
    edition = replace(
        album_option(spotify_id="edition", album="New Album (Deluxe)"),
        track_similarity=0.7,
    )
    better = replace(first, track_similarity=0.9, search_rank=2)
    second = album_option(spotify_id="second", album="Second Album")
    candidates = (
        track_candidate(track="First", score=2),
        track_candidate(track="Second", score=1),
    )
    return EvidenceCase(
        candidates, {"First": (edition, first), "Second": (better, second)}
    )


def _duplicate_case() -> EvidenceCase:
    option = album_option()
    weaker = replace(option, track_popularity=None, search_rank=2)
    better = replace(option, track_popularity=90, search_rank=3)
    candidates = (
        track_candidate(track="Same", score=2),
        track_candidate(track="Same", score=1),
        track_candidate(track="Other", score=0.5),
    )
    return EvidenceCase(candidates, {"Same": (option, weaker), "Other": (better,)})


def _exclusion_case() -> EvidenceCase:
    heard = album_option(spotify_id="heard", album="Heard")
    existing = album_option(spotify_id="existing", album="Existing")
    eligible = album_option(spotify_id="eligible", album="Eligible")
    return EvidenceCase(
        (track_candidate(),),
        {"New Track": (heard, existing, eligible)},
        {sauvignon.canonical_album_key(heard.artist, heard.album)},
        {"existing"},
    )


def evidence_case(name: str) -> EvidenceCase:
    """Return one original snapshot scenario.

    Args:
        name: Stable original case name.

    Returns:
        Original candidates, ordered observations and exclusions.

    Raises:
        ValueError: The requested scenario is unknown.
    """
    if name == "grouped":
        return _grouped_case()
    if name == "duplicates":
        return _duplicate_case()
    if name == "exclusions":
        return _exclusion_case()
    if name == "negative-limit":
        return replace(_grouped_case(), maximum=-1)
    if name == "empty":
        return replace(_grouped_case(), maximum=0)
    raise ValueError(name)


@dataclass
class EvidenceSteps:
    """Observe searches and progress before projection, without network requests.

    Args:
        case: Original scenario observations.
        failure: Optional event to fail after observation.
        events: Ordered original observation boundaries.
    """

    case: EvidenceCase
    failure: str = ""
    events: list[str] = field(default_factory=list)

    def _step(self, message: str) -> None:
        self.events.append(message)
        if message == self.failure:
            raise OSError(message)

    def search(
        self,
        spotify: Spotify,
        candidate: found_art.FoundArtCandidate,
        retry_call: sauvignon.RetryCall,
    ) -> tuple[sauvignon.SpotifyAlbumOption, ...]:
        """Read the configured original album observations for one candidate.

        Args:
            spotify: Unused caller-owned Spotify client.
            candidate: Original ranked track candidate.
            retry_call: Original retry boundary.

        Returns:
            Original ordered album options.
        """
        self._step(f"search:{candidate.track}")
        return self.case.observations[candidate.track]

    def progress(self, message: str) -> None:
        """Observe the original candidate progress before its search.

        Args:
            message: Original progress text.
        """
        self._step(message)


def gather_evidence(
    case: EvidenceCase, steps: EvidenceSteps
) -> tuple[sauvignon.AlbumRecommendation, ...]:
    """Execute the original public gatherer for a frozen scenario.

    Args:
        case: Original ordered observations and exclusions.
        steps: Original search/progress observers.

    Returns:
        Original ranked album recommendations.
    """
    return sauvignon.gather_album_recommendations(
        cast(Spotify, object()),
        case.candidates,
        case.excluded,
        case.existing,
        maximum_candidates=case.maximum,
        week_start=WEEK,
        retry_call=immediate,
        progress_callback=steps.progress,
    )


@pytest.mark.parametrize(
    "name", ["grouped", "duplicates", "exclusions", "negative-limit", "empty"]
)
def test_original_album_evidence_snapshots(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Retain exact scores, displays, edition choices, ties and weekly hash ranks.

    Args:
        monkeypatch: Scoped original search boundary.
        name: Original frozen scenario name.
    """
    case = evidence_case(name)
    steps = EvidenceSteps(case)
    monkeypatch.setattr(sauvignon, "search_candidate_albums", steps.search)
    recommendations = gather_evidence(case, steps)
    result = json.loads(json.dumps([asdict(item) for item in recommendations]))
    fixture = json.loads(FIXTURE.read_text())
    assert result == fixture["cases"][name]["recommendations"]
    assert steps.events == fixture["cases"][name]["events"]


@pytest.mark.parametrize(
    "failure",
    [
        "Resolving album evidence 1/2: New Artist - First",
        "search:First",
        "Resolving album evidence 2/2: New Artist - Second",
        "search:Second",
    ],
)
def test_original_failed_observation_prefix(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Stop before later searches when original progress or evidence reads fail.

    Args:
        monkeypatch: Scoped original search boundary.
        failure: Original observation to fail.
    """
    case = evidence_case("grouped")
    steps = EvidenceSteps(case, failure=failure)
    monkeypatch.setattr(sauvignon, "search_candidate_albums", steps.search)
    with pytest.raises(OSError, match=failure):
        gather_evidence(case, steps)
    order = [
        "Resolving album evidence 1/2: New Artist - First",
        "search:First",
        "Resolving album evidence 2/2: New Artist - Second",
        "search:Second",
    ]
    assert steps.events == order[: order.index(failure) + 1]
