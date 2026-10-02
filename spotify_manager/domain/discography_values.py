"""Original complete Discography planning and selection values."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Literal


type QueueName = Literal["newfoundland", "memory_lane", "requeue"]
type MarkerQueueName = Literal["newfoundland", "memory_lane", "requeue", "queue_3"]

QUEUE_ORDER: tuple[QueueName, ...] = ("newfoundland", "memory_lane", "requeue")
START_QUEUE_ROTATION: tuple[QueueName, ...] = ("newfoundland", "requeue", "memory_lane")


@dataclass(frozen=True)
class CatalogRelease:
    """One canonical album or EP available for an artist's batch.

    Args:
        spotify_id: Original spotify id facts.
        uri: Original uri facts.
        name: Original name facts.
        release_type: Original release type facts.
        release_date: Original release date facts.
        chronology_date: Original chronology date facts.
        total_tracks: Original total tracks facts.
        identity: Original identity facts.
        saved: Original saved facts.
        plain: Original plain facts.
        edition_rank: Original edition rank facts.
        default: Original default facts.
    """

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    chronology_date: str
    total_tracks: int
    identity: str
    saved: bool
    plain: bool
    edition_rank: int
    default: bool


@dataclass(frozen=True)
class QueueArtist:
    """One primary artist represented in an ordered source playlist.

    Args:
        spotify_id: Original spotify id facts.
        name: Original name facts.
        queue: Original queue facts.
    """

    spotify_id: str
    name: str
    queue: QueueName


@dataclass(frozen=True)
class HistoricalArtist:
    """One artist in a date's Last.fm ranking.

    Args:
        name: Original name facts.
        scrobbles: Original scrobbles facts.
    """

    name: str
    scrobbles: int


@dataclass(frozen=True)
class HistoricalArtistSelection:
    """One Random.org date and timestamp mapped to a Last.fm artist.

    Args:
        generated_at: Original generated at facts.
        cutoff_date: Original cutoff date facts.
        available_dates: Original available dates facts.
        selected_date: Original selected date facts.
        date_index: Original date index facts.
        artists_on_date: Original artists on date facts.
        position: Original position facts.
        artist: Original artist facts.
    """

    generated_at: datetime
    cutoff_date: date
    available_dates: int
    selected_date: date
    date_index: int
    artists_on_date: int
    position: int
    artist: HistoricalArtist


@dataclass(frozen=True)
class ArtistMarkers:
    """Playlist marker URIs belonging to one selected artist.

    Args:
        queue: Original queue facts.
        playlist_id: Original playlist id facts.
        uris: Original uris facts.
    """

    queue: MarkerQueueName
    playlist_id: str
    uris: tuple[str, ...]


@dataclass(frozen=True)
class ArtistSelection:
    """One artist and the exact releases chosen for the listening batch.

    Args:
        spotify_id: Original spotify id facts.
        name: Original name facts.
        source_queue: Original source queue facts.
        releases: Original releases facts.
        markers: Original markers facts.
    """

    spotify_id: str
    name: str
    source_queue: QueueName
    releases: tuple[CatalogRelease, ...]
    markers: tuple[ArtistMarkers, ...]

    @property
    def release_count(self) -> int:
        """Return the selected canonical release count.

        Returns:
            Original number of selected editions.
        """
        return len(self.releases)

    @property
    def days(self) -> float:
        """Return listening days at two releases per day.

        Returns:
            Original estimated listening duration.
        """
        return self.release_count / 2


@dataclass(frozen=True)
class DiscographyPlan:
    """The next batch selected according to queue order and week packing.

    Args:
        start_queue: Original start queue facts.
        next_queue: Original next queue facts.
        artists: Original artists facts.
        total_releases: Original total releases facts.
        open_slots: Original open slots facts.
    """

    start_queue: QueueName
    next_queue: QueueName
    artists: tuple[ArtistSelection, ...]
    total_releases: int
    open_slots: int

    @property
    def days(self) -> float:
        """Return total listening days at two releases per day.

        Returns:
            Original estimated batch duration.
        """
        return self.total_releases / 2
