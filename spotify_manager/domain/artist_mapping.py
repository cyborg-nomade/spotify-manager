"""Shared observed artist mappings without catalog clients or UI dependencies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SpotifyArtistCandidate:
    """One observed Spotify artist mapping candidate.

    Args:
        spotify_id: Original artist identity.
        name: Original display spelling.
        uri: Original Spotify URI.
        popularity: Original observed popularity.
        followers: Original observed follower count.
        search_rank: Original search position.
        exact_name: Whether normalized names match exactly.
    """

    spotify_id: str
    name: str
    uri: str
    popularity: int | None
    followers: int | None
    search_rank: int
    exact_name: bool
