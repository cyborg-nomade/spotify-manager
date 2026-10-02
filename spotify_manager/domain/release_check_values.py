"""Original ranked artists, observed releases and mutable destination membership."""

from dataclasses import dataclass
from typing import Literal


NEW_VINTAGE_ARTIST_LIMIT = 50
ALL_SINGLES_ARTIST_LIMIT = 20

PlaylistAction = Literal[
    "added",
    "would add",
    "already present",
    "artist already present",
    "duplicate selection",
    "not applicable",
]


@dataclass(frozen=True)
class RankedArtist:
    """One Last.fm artist ranked by all-time scrobble count.

    Args:
        key: Normalized Last.fm artist identity.
        name: Original majority display spelling.
        scrobbles: All-time original play count.
        rank: Original global count rank before the minimum filter.
    """

    key: str
    name: str
    scrobbles: int
    rank: int

    @property
    def is_new_vintage(self) -> bool:
        """Check original top-fifty New Vintage eligibility.

        Returns:
            Whether the original global artist rank is at most fifty.
        """
        return self.rank <= NEW_VINTAGE_ARTIST_LIMIT

    @property
    def accepts_all_singles(self) -> bool:
        """Check original top-twenty standalone-single eligibility.

        Returns:
            Whether the original global artist rank is at most twenty.
        """
        return self.rank <= ALL_SINGLES_ARTIST_LIMIT


@dataclass(frozen=True)
class ReleaseCandidate:
    """One primary-artist release returned by Spotify.

    Args:
        spotify_id: Original release identity.
        uri: Original release URI.
        name: Original display title.
        release_type: Original inferred release kind.
        release_date: Original partial or complete date.
        release_date_precision: Original precision label.
        total_tracks: Observed original track count.
        primary_artist_id: First credited artist identity.
        primary_artist_name: First credited artist display name.
    """

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    release_date_precision: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str


@dataclass(frozen=True)
class ReleaseTrack:
    """One Spotify track with its credit and release positions.

    Args:
        spotify_id: Original track identity.
        uri: Original track URI.
        name: Original display title.
        primary_artist_id: First credited artist identity.
        primary_artist_name: First credited display name.
        disc_number: Original disc position.
        track_number: Original track position.
    """

    spotify_id: str
    uri: str
    name: str
    primary_artist_id: str
    primary_artist_name: str
    disc_number: int
    track_number: int


@dataclass(frozen=True)
class PendingSingle:
    """A single retained until an announced future record can confirm it.

    Args:
        artist_key: Original ranked Last.fm artist identity.
        release: Original retained single metadata.
        first_track: Original playable single marker.
    """

    artist_key: str
    release: ReleaseCandidate
    first_track: ReleaseTrack


@dataclass(frozen=True)
class ReleaseCheckResult:
    """One release decision and any resulting playlist actions.

    Args:
        artist: Original Last.fm display name.
        artist_rank: Original global artist rank.
        artist_scrobbles: Original all-time play count.
        spotify_artist_id: Original resolved artist identity.
        release_id: Original release identity.
        release: Original display title.
        release_type: Original inferred kind.
        release_date: Original precision-preserving date.
        first_track_id: Original chosen marker identity, when loaded.
        first_track: Original chosen marker title, when loaded.
        linked_future_release: Original announced record containing the single.
        wine_cellar_action: Original Wine Cellar outcome.
        new_vintage_action: Original New Vintage outcome.
        reason: Original skipped or pending reason.
        dry_run: Original preview mode.
    """

    artist: str
    artist_rank: int
    artist_scrobbles: int
    spotify_artist_id: str
    release_id: str
    release: str
    release_type: str
    release_date: str
    first_track_id: str | None
    first_track: str | None
    linked_future_release: str | None
    wine_cellar_action: PlaylistAction
    new_vintage_action: PlaylistAction
    reason: str | None
    dry_run: bool


@dataclass
class PlaylistMembership:
    """Mutable playlist identities used to avoid duplicate additions.

    Args:
        track_ids: Original represented track identities.
        track_keys: Original represented normalized artist/title identities.
        primary_artist_ids: Original represented first-credit artist identities.
    """

    track_ids: set[str]
    track_keys: set[tuple[str, str]]
    primary_artist_ids: set[str]


@dataclass(frozen=True)
class PlaylistEntry:
    """One ordered playlist item retained during Wine Cellar cleanup.

    Args:
        uri: Original playlist item URI.
        spotify_id: Original track identity.
        name: Original title.
        primary_artist_id: Original first-credit identity, when known.
        primary_artist_name: Original first-credit name, when known.
    """

    uri: str
    spotify_id: str
    name: str
    primary_artist_id: str | None
    primary_artist_name: str | None


@dataclass(frozen=True)
class PlaylistSnapshot:
    """Ordered playlist entries and their lookup indexes.

    Args:
        entries: Original ordered items, preserving duplicate observations.
        membership: Original mutable membership indexes.
    """

    entries: tuple[PlaylistEntry, ...]
    membership: PlaylistMembership
