"""Shared parsed catalog values; legacy routine imports remain aliases."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscographyRelease:
    """One selected studio album or EP edition.

    Args:
        spotify_id: Original Spotify identifier.
        uri: Original Spotify URI.
        name: Display title.
        release_type: Existing release classification.
        release_date: Original partial or full release date.
        chronology_date: Earliest edition date used for ordering.
        total_tracks: Observed track count.
        primary_artist_id: First credited artist identifier.
        primary_artist_name: First credited artist display name.
        identity: Edition-neutral release identity.
        saved: Observed Saved Albums membership.
        plain: Whether the title has no edition decorations.
        edition_rank: Number of recognized edition decorations.
    """

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    chronology_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str
    identity: str
    saved: bool
    plain: bool
    edition_rank: int


@dataclass(frozen=True)
class ReleaseTrack:
    """One ordered track in a Spotify release.

    Args:
        spotify_id: Original Spotify identifier.
        uri: Original Spotify URI.
        name: Display title.
        disc_number: Parsed disc ordering position.
        track_number: Parsed track ordering position.
    """

    spotify_id: str
    uri: str
    name: str
    disc_number: int
    track_number: int


@dataclass(frozen=True)
class ReleaseCandidate:
    """Parsed release facts attached to a playlist marker or selection candidate.

    Args:
        spotify_id: Original Spotify identifier.
        uri: Original Spotify URI.
        name: Display title.
        release_type: Existing release classification.
        release_date: Original partial or full release date.
        total_tracks: Observed track count.
        primary_artist_id: First credited artist identifier.
        primary_artist_name: First credited artist display name.
    """

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str


@dataclass(frozen=True)
class PlaylistTrack:
    """One playable playlist marker with its primary artist and release facts.

    Args:
        spotify_id: Original Spotify identifier.
        uri: Original Spotify URI.
        name: Display title.
        primary_artist_id: First credited artist identifier.
        primary_artist_name: First credited artist display name.
        release: Original parsed release attached to the playlist marker.
    """

    spotify_id: str
    uri: str
    name: str
    primary_artist_id: str
    primary_artist_name: str
    release: ReleaseCandidate
