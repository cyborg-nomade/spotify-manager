"""Existing serialized catalog field shapes shared by durable routine records."""

from typing import TypedDict

from spotify_manager.domain.discovery import ReleaseTier


class ReleaseRecord(TypedDict):
    """Existing serialized release fields used at the durable state boundary."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str


class DiscographyRecord(ReleaseRecord):
    """Selected-edition fields retained alongside the original release fields."""

    chronology_date: str
    identity: str
    saved: bool
    plain: bool
    edition_rank: int


class TrackRecord(TypedDict):
    """Existing ordered-track fields stored in a durable transition plan."""

    spotify_id: str
    uri: str
    name: str
    disc_number: int
    track_number: int


class RankedReleaseRecord(ReleaseRecord):
    """Original discovery metadata stored beside a release's catalog fields."""

    popularity: int | None
    top_track_rank: int | None
    tier: ReleaseTier
    identity: str
    saved: bool
    plain: bool


class CatalogTrackRecord(TrackRecord):
    """Original primary-credit and popularity fields stored in discovery plans."""

    primary_artist_id: str
    primary_artist_name: str
    popularity: int | None
