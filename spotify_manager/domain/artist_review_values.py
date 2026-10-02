"""Original artist-review errors, catalog facts and queue membership."""

import re
from dataclasses import dataclass
from typing import Self


class ArtistReviewError(RuntimeError):
    """Base exception for a review that cannot continue safely."""


class ArtistReviewConfigError(ArtistReviewError):
    """Raised when queue playlist configuration is missing or invalid."""


class InvalidReviewChoiceError(ArtistReviewError):
    """Raised when an interactive callback returns an unknown choice."""


def parse_playlist_id(reference: str) -> str:
    """Extract a Spotify playlist id from a URL, URI, or bare id.

    Args:
        reference: Original playlist setting.

    Returns:
        Original parsed identity.

    Raises:
        ArtistReviewConfigError: The reference has no accepted playlist identity.
    """
    value = reference.strip()
    patterns = (
        r"^spotify:playlist:(?P<id>[A-Za-z0-9]+)$",
        r"open\.spotify\.com/playlist/(?P<id>[A-Za-z0-9]+)",
        r"^(?P<id>[A-Za-z0-9]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group("id")
    raise ArtistReviewConfigError(f"Invalid Spotify playlist reference: {reference}")


@dataclass(frozen=True)
class QueuePlaylists:
    """Playlist ids for the three liked-track tiers.

    Args:
        queue_1: Original queue 1 observation.
        queue_2: Original queue 2 observation.
        queue_3: Original queue 3 observation.
    """

    queue_1: str
    queue_2: str
    queue_3: str

    @classmethod
    def from_references(
        cls: type[Self],
        queue_1: str | None,
        queue_2: str | None,
        queue_3: str | None,
    ) -> Self:
        """Parse playlist URLs, URIs, or bare ids from configuration.

        Args:
            queue_1: Original lowest-tier reference.
            queue_2: Original middle-tier reference.
            queue_3: Original highest-tier reference.

        Returns:
            Original complete queue identities.

        Raises:
            ArtistReviewConfigError: Settings are missing or invalid.
        """
        missing = _missing_settings(queue_1, queue_2, queue_3)
        if missing:
            raise ArtistReviewConfigError(
                "Missing queue playlist setting(s): " + ", ".join(missing)
            )
        assert queue_1 is not None
        assert queue_2 is not None
        assert queue_3 is not None
        return cls(
            queue_1=parse_playlist_id(queue_1),
            queue_2=parse_playlist_id(queue_2),
            queue_3=parse_playlist_id(queue_3),
        )

    def for_liked_count(self, liked_count: int) -> str:
        """Return the queue matching the original inclusive five/seventeen tiers.

        Args:
            liked_count: Original liked count, including zero and negative values.

        Returns:
            Original selected destination.
        """
        if liked_count <= 5:
            return self.queue_1
        if liked_count <= 17:
            return self.queue_2
        return self.queue_3


@dataclass(frozen=True)
class TrackCandidate:
    """A Spotify-ranked track associated with the reviewed artist.

    Args:
        spotify_id: Original spotify id observation.
        name: Original name observation.
        uri: Original uri observation.
        album: Original album observation.
        rank: Original rank observation.
        primary_artist_id: Original primary artist id observation.
        primary_artist_name: Original primary artist name observation.
        artist_ids: Original artist ids observation.
        popularity: Original popularity observation.
    """

    spotify_id: str
    name: str
    uri: str
    album: str
    rank: int
    primary_artist_id: str
    primary_artist_name: str
    artist_ids: tuple[str, ...]
    popularity: int | None = None


@dataclass
class ReleaseCandidate:
    """A release and its first-track primary credit.

    Args:
        spotify_id: Original spotify id observation.
        name: Original name observation.
        uri: Original uri observation.
        release_type: Original release type observation.
        release_date: Original release date observation.
        total_tracks: Original total tracks observation.
        rank: Original rank observation.
        primary_artist_id: Original primary artist id observation.
        primary_artist_name: Original primary artist name observation.
        artist_ids: Original artist ids observation.
        first_track_checked: Original first track checked observation.
        first_track_id: Original first track id observation.
        first_track_name: Original first track name observation.
        first_track_uri: Original first track uri observation.
        first_track_primary_artist_id: Original first track primary credit identity.
        first_track_primary_artist_name: Original first track primary display name.
    """

    spotify_id: str
    name: str
    uri: str
    release_type: str
    release_date: str
    total_tracks: int
    rank: int
    primary_artist_id: str
    primary_artist_name: str
    artist_ids: tuple[str, ...]
    first_track_checked: bool = False
    first_track_id: str | None = None
    first_track_name: str | None = None
    first_track_uri: str | None = None
    first_track_primary_artist_id: str | None = None
    first_track_primary_artist_name: str | None = None

    def is_eligible_for(self, artist_id: str) -> bool:
        """Return whether the release's first track credits the target first.

        Args:
            artist_id: Original exact target identity.

        Returns:
            Whether a non-None first identity and the primary credit qualify.
        """
        return (
            self.first_track_id is not None
            and self.first_track_primary_artist_id == artist_id
        )


@dataclass
class PlaylistMembership:
    """Primary artists and tracks already represented in one queue.

    Args:
        primary_artist_ids: Original primary artist ids observation.
        track_ids: Original track ids observation.
        track_uris_by_primary_artist: Original track uris by primary artist observation.
    """

    primary_artist_ids: set[str]
    track_ids: set[str]
    track_uris_by_primary_artist: dict[str, list[str]]


def _missing_settings(
    queue_1: str | None, queue_2: str | None, queue_3: str | None
) -> list[str]:
    settings = (
        ("the_queue_playlist", queue_1),
        ("the_queue_2_playlist", queue_2),
        ("the_queue_3_playlist", queue_3),
    )
    missing = []
    for name, value in settings:
        if not value:
            missing.append(name)
    return missing
