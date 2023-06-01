"""Test Spotipy client."""

import spotipy

# UFI
from spotify_manager.client import get_spotipy_client


def test_get_spotipy_client() -> None:
    """Get spotipy client."""
    client = get_spotipy_client()
    assert isinstance(client, spotipy.Spotify)
