"""Cohesive read resources for indexed published listening history."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import EntityKind
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import EntitySelection
from spotify_manager.domain.listening_values import ListeningCounts
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningRanking
from spotify_manager.domain.listening_values import ListeningRecords
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RecordOptions


@dataclass(frozen=True)
class ListeningMetadata:
    """Identify one complete derived index and its verified source publication."""

    snapshot: str
    source_sha256: str
    published_at: str
    indexed_at: str
    first_ms: int | None
    last_ms: int | None
    scrobbles: int
    missing_album: int
    source_bytes: int
    build_seconds: float


@dataclass(frozen=True)
class ListeningStatus:
    """Report source/index readiness without exposing any unverified partial build."""

    state: Literal["ready", "building", "stale", "missing", "error"]
    metadata: ListeningMetadata | None
    message: str
    checking: bool
    retry_after: int = 2


class ListeningNotReadyError(RuntimeError):
    """No complete listening generation is available yet."""


class ListeningVersionError(RuntimeError):
    """The requested generation expired; reload every widget on one new version."""


class ListeningEntityError(LookupError):
    """The selected entity has no history before the analysis cutoff."""


class ListeningReads(Protocol):
    """Read one complete, immutable history generation through named operations."""

    @property
    def metadata(self) -> ListeningMetadata:
        """Return the verified source and index identity."""
        ...

    def counts(
        self, query: ListeningQuery, selection: EntitySelection | None = None
    ) -> ListeningCounts:
        """Read exact filtered counts and UTC observation bounds."""
        ...

    def timestamps(
        self, query: ListeningQuery, selection: EntitySelection | None = None
    ) -> tuple[int, ...]:
        """Read selected recorded instants, retaining repeated rows."""
        ...

    def rankings(
        self,
        query: ListeningQuery,
        options: RankingOptions,
        selection: EntitySelection | None = None,
    ) -> ListeningRanking:
        """Read one searchable, bounded entity ranking."""
        ...

    def artist_plays(
        self, query: ListeningQuery, *, full_history: bool = False
    ) -> tuple[ArtistPlay, ...]:
        """Read artist observations for evolution or pre-cutoff discovery history."""
        ...

    def lifetimes(
        self, query: ListeningQuery, kind: EntityKind, *, full_history: bool = False
    ) -> tuple[EntityLifetime, ...]:
        """Read entity counts and first/last observations through the cutoff."""
        ...

    def records(
        self,
        query: ListeningQuery,
        options: RecordOptions,
    ) -> ListeningRecords:
        """Read at most one bounded, newest-first page of source observations."""
        ...

    def entity_lifetime(
        self, query: ListeningQuery, selection: EntitySelection
    ) -> EntityLifetime:
        """Read an entity's full pre-cutoff facts or raise ListeningEntityError."""
        ...
