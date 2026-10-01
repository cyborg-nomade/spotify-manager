"""Direct album evidence codecs without SDK clients or routine helpers."""

from dataclasses import replace

from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.infrastructure.album_recommendations import parse_album_search
from tests.support.album_evidence import read_case


def _observed_option(
    raw: object, candidate: FoundArtCandidate, rank: int
) -> SpotifyAlbumOption | None:
    return raw if isinstance(raw, SpotifyAlbumOption) else None


def test_search_decoding_skips_unqualified_rows_and_replaces_weaker_editions() -> None:
    """Keep parser order, strongest per-ID evidence and identity tie-breaking."""
    case = read_case("duplicates")
    first = case.observations["Same"][0]
    stronger = replace(first, track_popularity=90)
    other = replace(stronger, spotify_id="a")
    response = {"tracks": {"items": [None, first, stronger, other, first]}}
    options = parse_album_search(response, case.candidates[0], _observed_option)
    assert options == (other, stronger)
