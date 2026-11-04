"""The reported omitted article is resolved through the generic manual fallback."""

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.ports.runtime import NO_RETRY
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.history_matching import name_similarity
from spotify_manager.infrastructure.legacy.annual_catalog import LegacyAnnualSpotify
from spotify_manager.infrastructure.manual_track_catalog import SpotifyManualTracks
from tests.support.manual_matching import CatalogChoices


async def test_actual_chevelle_results_bypass_the_unchanged_automatic_threshold() -> (
    None
):
    """Offer the observed correct catalog record without introducing a title rule."""
    path = Path(__file__).parents[1] / "fixtures/catalog_matching/chevelle.json"
    searches = json.loads(path.read_text())["searches"]
    client = AsyncMock()
    client.search.side_effect = [searches[0]["response"], searches[1]["response"]]
    identity = "3EYoNZwkuyJN7JTqt2djEM"
    choices = CatalogChoices([identity])
    spotify = cast(SpotifyClient, client)
    manual = ManualTrackMatching(
        SpotifyManualTracks(spotify, NO_RETRY, choices), choices, choices
    )
    resolution = AnnualResolution(LegacyAnnualSpotify(spotify, NO_RETRY), manual)
    result = await resolution.track(
        {"artist": "Chevelle", "name": "In Debt to Earth", "scrobbles": 10}
    )
    assert result == f"spotify:track:{identity}"
    assert name_similarity("In Debt to Earth", "In Debt to the Earth") < 0.9
    assert choices.offered[0][1][:2] == (identity, "5Ivq9qmFUfbs13kv3BvvVV")
    assert client.search.await_args_list[0].kwargs["q"] == searches[0]["query"]
    assert client.search.await_args_list[1].kwargs["q"] == searches[1]["query"]
