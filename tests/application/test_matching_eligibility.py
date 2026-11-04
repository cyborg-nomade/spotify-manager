"""Manual matching retains the distinct policies of each Last.fm consumer."""

from dataclasses import dataclass
from dataclasses import replace
from datetime import date

import pytest

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.application.golden_selection import GoldenLastfmSelection
from spotify_manager.application.manual_album_matching import ManualAlbumMatching
from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.application.palace_planning import PalacePlanning
from spotify_manager.application.recommendation_resolution import (
    RecommendationResolution,
)
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_oldies import LastFmTrackStat
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from tests.application.test_golden_selection_recipes import MarkerReads
from tests.application.test_palace_workflow import MemoryPalace
from tests.application.test_recommendation_batch_resolution import BatchMemory
from tests.application.test_recommendation_batch_resolution import _candidate
from tests.application.test_recommendation_batch_resolution import _match
from tests.support.manual_matching import AlbumSearch
from tests.support.manual_matching import CatalogChoices
from tests.support.manual_matching import TrackSearch
from tests.support.manual_matching import album_candidate
from tests.support.palace_run import PalaceObservations
from tests.support.palace_run import albums
from tests.support.palace_run import history
from tests.support.runtime_resources import MessageList


@pytest.mark.parametrize(
    "liked,answer,action",
    [
        (True, "chosen", "liked"),
        (False, "chosen", "would add"),
        (False, "", "no Spotify match"),
    ],
)
async def test_found_art_keeps_liked_exclusion_after_manual_resolution(
    liked: bool, answer: str, action: str
) -> None:
    """Apply the existing unheard-track rule to an explicit low-similarity choice.

    Args:
        liked: Live saved-track status for the manually selected identity.
        answer: Offered ID or explicit rejection.
        action: Expected routine-specific outcome.
    """
    memory = BatchMemory(liked_ids={"chosen"} if liked else set())
    choices = CatalogChoices([answer])
    candidate = replace(_match("chosen"), track_similarity=0.01)
    manual = ManualTrackMatching(TrackSearch((candidate,)), choices, choices)
    results, pending = await RecommendationResolution(
        memory, MessageList([]), manual=manual
    ).run((_candidate("Artist", "Song"),), PlaylistState(0, frozenset()), 1, True)
    assert results[0].action == action
    assert len(pending) == int(action == "would add")
    assert len(choices.offered) == 1


async def test_found_art_keeps_artist_diversity_duplicates_and_capacity() -> None:
    """Avoid prompting excluded candidates and do not append duplicate identities."""
    memory = BatchMemory()
    choices = CatalogChoices(["same", "same", "next"])
    manual = ManualTrackMatching(
        TrackSearch((_match("same"), _match("next"))), choices, choices
    )
    candidates = (
        _candidate("a", "first"),
        _candidate("a", "second"),
        _candidate("b", "third"),
        _candidate("c", "fourth"),
    )
    results, pending = await RecommendationResolution(
        memory, MessageList([]), manual=manual
    ).run(candidates, PlaylistState(0, frozenset()), 2, False)
    assert [result.action for result in results] == [
        "added",
        "artist already selected",
        "duplicate",
        "added",
    ]
    assert [item.spotify_id for item in pending] == ["same", "next"]
    assert [reference.track for reference, _offered in choices.offered] == [
        "first",
        "third",
        "fourth",
    ]


@dataclass(frozen=True)
class EmptyAlbumReads:
    """Return no automatically eligible album editions."""

    async def search(
        self, candidate: FoundArtCandidate
    ) -> tuple[SpotifyAlbumOption, ...]:
        """Observe an automatic miss before the manual album fallback.

        Args:
            candidate: Ranked historical recommendation.

        Returns:
            An empty candidate tuple.
        """
        return ()


@pytest.mark.parametrize(
    "exclusion", ["none", "heard", "represented", "compilation", "rejected"]
)
async def test_sauvignon_keeps_album_history_membership_and_release_eligibility(
    exclusion: str,
) -> None:
    """Show unfiltered choices while retaining Sauvignon's album/EP acceptance policy.

    Args:
        exclusion: Routine-specific reason to exclude the selected release.
    """
    album = album_candidate(
        "chosen", "compilation" if exclusion == "compilation" else "album"
    )
    choices = CatalogChoices(["" if exclusion == "rejected" else "chosen"])
    manual = ManualAlbumMatching(AlbumSearch((album,)), choices, choices)
    excluded = {("new", "different album")} if exclusion == "heard" else set()
    existing = {"chosen"} if exclusion == "represented" else set()
    result = await AlbumGathering(EmptyAlbumReads(), MessageList([]), manual).run(
        (_candidate("New", "Song"),), excluded, existing, 10, date(2026, 11, 4)
    )
    assert len(result) == int(exclusion == "none")
    assert len(choices.offered) == 1
    if result:
        assert result[0].options[0].spotify_id == "chosen"


@pytest.mark.parametrize("reject", [False, True])
async def test_golden_lastfm_selection_keeps_title_order_stats_and_distinct_ids(
    reject: bool,
) -> None:
    """Retain historical order and allow explicit rejection of all top tracks.

    Args:
        reject: Reject every unresolved title when true.
    """
    artist = GoldenOldieArtist(
        "Artist",
        50,
        100,
        0,
        200,
        (LastFmTrackStat("One", 30, 200), LastFmTrackStat("Two", 20, 100)),
    )
    choices = CatalogChoices(["" if reject else "same"] * 2)
    manual = ManualTrackMatching(TrackSearch((_match("same"),)), choices, choices)
    result = await GoldenLastfmSelection(
        MarkerReads(((), ()), set()), manual=manual
    ).run(artist)
    assert len(result) == int(not reject)
    if result:
        assert result[0].lastfm_scrobbles == 30
        assert result[0].source == "Last.fm top tracks"


async def test_palace_saved_album_priority_and_manual_first_track_cache() -> None:
    """Keep saved editions automatic and reuse the marker of a repeated manual album."""
    edge = PalaceObservations("missing")
    choices = CatalogChoices(["chosen", "chosen"])
    manual = ManualAlbumMatching(
        AlbumSearch((album_candidate("chosen"),)), choices, choices
    )
    result = await PalacePlanning(
        MemoryPalace(edge), albums(), manual=manual
    ).historical(history())
    assert len(choices.offered) == 2
    assert result[0].spotify_album is not None and result[0].spotify_album.saved
    assert (
        result[1].spotify_album is not None
        and result[1].spotify_album.spotify_id == "chosen"
    )
    assert result[1].first_track is result[2].first_track
    assert len([event for event in edge.trace if event[0] == "track"]) == 2
