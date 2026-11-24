"""Synthetic country evidence and a public-read fixture with no network access."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from uuid import NAMESPACE_URL
from uuid import uuid5

from spotify_manager.application.listening_origin_ports import OriginSourceError
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_origin_values import OriginCandidate
from spotify_manager.domain.listening_origin_values import OriginState
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity


def origin_metadata(
    name: str = "Alpha",
    countries: tuple[str, ...] = ("BR",),
    state: OriginState = "matched",
    count: int = 1,
    fetched_at: str = "2026-11-21T10:00:00+00:00",
) -> ArtistOriginMetadata:
    """Build valid bounded metadata while leaving ambiguous candidates explicit.

    Args:
        name: Requested original history name.
        countries: Reported codes for each synthetic candidate.
        state: Deliberate search outcome.
        count: Exact-name candidates found before the five-row cap.
        fetched_at: Aware current metadata retrieval date.

    Returns:
        Credential-free deterministic geographic evidence.
    """
    candidates = []
    for index in range(min(count, 5)):
        candidates.append(
            OriginCandidate(
                str(uuid5(NAMESPACE_URL, name + str(index))),
                name,
                f"Synthetic candidate {index}",
                "Group",
                "Associated area",
                "Formation place",
                tuple(sorted(countries)),
            )
        )
    return ArtistOriginMetadata(
        listening_identity((name,)), name, state, tuple(candidates), count, fetched_at
    )


@dataclass
class FixtureOriginSource:
    """Record only requested names while returning independent fixture evidence.

    Args:
        configured: Public lookup configuration availability.
        fail: Controlled provider failure.
        names: Names observed by this fixture resource.
    """

    configured: bool = True
    fail: bool = False
    names: list[str] = field(default_factory=list)

    async def fetch(self, artist: RankedEntity) -> ArtistOriginMetadata:
        """Return one current country observation without making a network call.

        Args:
            artist: Captured selected artist name and normalized identity.

        Returns:
            Dated fixture country evidence.

        Raises:
            OriginSourceError: Deliberately configured provider outage.
        """
        self.names.append(artist.name)
        if self.fail:
            raise OriginSourceError("Fixture provider unavailable.")
        return origin_metadata(artist.name, fetched_at=datetime.now(UTC).isoformat())


@dataclass
class FixtureOriginArchive:
    """Keep immutable synthetic checkpoints for offline loader tests."""

    entries: tuple[ArtistOriginMetadata, ...] = ()
    checkpoints: list[tuple[str, ...]] = field(default_factory=list)

    async def restore(self) -> tuple[ArtistOriginMetadata, ...]:
        """Return the committed synthetic data."""
        return self.entries

    async def checkpoint(
        self, entries: tuple[ArtistOriginMetadata, ...]
    ) -> tuple[ArtistOriginMetadata, ...]:
        """Merge synthetic outcomes and record each successful checkpoint."""
        stored = {item.artist_key: item for item in self.entries}
        stored.update((item.artist_key, item) for item in entries)
        self.entries = tuple(stored[key] for key in sorted(stored))
        self.checkpoints.append(tuple(item.artist_name for item in entries))
        return self.entries
