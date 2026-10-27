"""Retain pure SDK identifier normalization, including invalid reference errors."""

import pytest
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.infrastructure.spotify_async.identifiers import spotify_id
from spotify_manager.infrastructure.spotify_async.identifiers import spotify_uri


@pytest.mark.parametrize("kind", ["track", "artist", "album", "playlist"])
@pytest.mark.parametrize(
    "reference",
    [
        "abc123",
        "spotify:track:abc",
        "spotify:album:abc",
        "https://open.spotify.com/artist/abc?si=x",
        "open.spotify.com/intl-de/playlist/abc",
        "bad-id",
        "",
        "spotify:user:owner:playlist:abc",
    ],
)
def test_identifier_and_uri_results_match_sdk(kind: str, reference: str) -> None:
    """Retain exact successful values and original mismatch errors.

    Args:
        kind: Expected Spotify resource kind.
        reference: Original raw, URI or URL value.
    """
    baseline = Spotify(requests_session=False)
    _compare_id(baseline, kind, reference)
    _compare_uri(baseline, kind, reference)


def _compare_id(baseline: Spotify, kind: str, reference: str) -> None:
    try:
        expected = baseline._get_id(kind, reference)
    except SpotifyException as error:
        with pytest.raises(SpotifyException) as actual:
            spotify_id(kind, reference)
        assert str(actual.value) == str(error)
        return
    assert spotify_id(kind, reference) == expected


def _compare_uri(baseline: Spotify, kind: str, reference: str) -> None:
    try:
        expected = baseline._get_uri(kind, reference)
    except SpotifyException as error:
        with pytest.raises(SpotifyException) as actual:
            spotify_uri(kind, reference)
        assert str(actual.value) == str(error)
        return
    assert spotify_uri(kind, reference) == expected
