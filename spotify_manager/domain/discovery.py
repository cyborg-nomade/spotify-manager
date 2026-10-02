"""Parsed catalog values used by artist discovery and release review policies."""

from dataclasses import dataclass
from typing import Literal


type ReleaseTier = Literal[0, 1, 2, 3]


@dataclass(frozen=True)
class RankedRelease:
    """One canonical primary-artist release ranked for discovery.

    Args:
        spotify_id: Original Spotify identifier.
        uri: Original Spotify URI.
        name: Display title.
        release_type: Existing release classification.
        release_date: Original partial or full date.
        total_tracks: Observed release track count.
        primary_artist_id: First credited artist identifier.
        primary_artist_name: First credited artist name.
        popularity: Observed popularity, when available.
        top_track_rank: Position of the release in artist top-track observations.
        tier: Existing discovery preference tier.
        identity: Edition-neutral release identity.
        saved: Observed saved-album membership.
        plain: Whether the title lacks edition decorations.
    """

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str
    popularity: int | None
    top_track_rank: int | None
    tier: ReleaseTier
    identity: str
    saved: bool
    plain: bool


@dataclass(frozen=True)
class CatalogTrack:
    """One ordered release track with its primary credit.

    Args:
        spotify_id: Original Spotify identifier.
        uri: Original Spotify URI.
        name: Display title.
        disc_number: Original one-based disc position.
        track_number: Original one-based track position.
        primary_artist_id: First credited artist identifier.
        primary_artist_name: First credited artist name.
        popularity: Observed popularity, when available.
    """

    spotify_id: str
    uri: str
    name: str
    disc_number: int
    track_number: int
    primary_artist_id: str
    primary_artist_name: str
    popularity: int | None = None
