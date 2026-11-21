"""Synthetic tag observations and a provider that never calls the network."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from urllib.parse import quote

from spotify_manager.application.listening_tag_ports import TagSourceError
from spotify_manager.domain.listening_tag_values import ArtistTagMetadata
from spotify_manager.domain.listening_tag_values import CommunityTag
from spotify_manager.domain.listening_tag_values import TagState
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity


def tag_metadata(
    name: str = "Alpha",
    labels: tuple[str, ...] = ("Rock", "Pop", "Experimental"),
    state: TagState = "tagged",
    fetched_at: str = "2026-11-21T10:00:00+00:00",
) -> ArtistTagMetadata:
    """Construct one complete identity-checked local metadata fixture.

    Args:
        name: Requested artist name.
        labels: Ranked community labels.
        state: Deliberate completed lookup outcome.
        fetched_at: Explicit aware retrieval timestamp.

    Returns:
        Credential-free source metadata using the production identity rule.
    """
    tags = tuple(CommunityTag(listening_identity((label,)), label) for label in labels)
    url = "https://www.last.fm/music/" + quote(name, safe="") + "/+tags"
    return ArtistTagMetadata(
        listening_identity((name,)), name, name, state, tags, fetched_at, url
    )


@dataclass
class FixtureTagSource:
    """Record named fixture reads while keeping every test off the real provider.

    Args:
        configured: Explicit configuration availability.
        fail: Whether to report a safe provider outage.
        names: Observed artist names, without listening records.
    """

    configured: bool = True
    fail: bool = False
    names: list[str] = field(default_factory=list)

    async def fetch(self, artist: RankedEntity) -> ArtistTagMetadata:
        """Return deterministic tags or a controlled provider failure.

        Args:
            artist: Selected public name and analytics identity.

        Returns:
            Complete fixture metadata, never a network result.

        Raises:
            TagSourceError: A deliberate fixture outage.
        """
        self.names.append(artist.name)
        if self.fail:
            raise TagSourceError("Fixture provider unavailable.")
        return tag_metadata(artist.name, fetched_at=datetime.now(UTC).isoformat())
