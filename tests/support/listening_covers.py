"""Synthetic album evidence and tiny image fixtures with no public requests."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from io import BytesIO
from uuid import NAMESPACE_URL
from uuid import uuid5

from PIL import Image

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import AlbumCoverMetadata
from spotify_manager.domain.listening_cover_values import CoverCandidate
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_cover_values import CoverState
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening.cover_image import cover_artwork
from spotify_manager.infrastructure.listening.cover_image import validate_cover_image


def album(name: str = "Record", artist: str = "Alpha") -> RankedEntity:
    """Return one original history identity with actual album/artist context.

    Args:
        name: Synthetic original album title.
        artist: Synthetic complete credited artist name.

    Returns:
        Synthetic album with its normalized original identity.
    """
    return RankedEntity(listening_identity((artist, name)), name, artist, 1, 1.0)


def jpeg(color: str = "#698e8c", size: tuple[int, int] = (32, 32)) -> bytes:
    """Create a tiny flat-color synthetic JPEG for decoder and browser fixtures.

    Args:
        color: Synthetic thumbnail background color.
        size: Encoded image dimensions used to exercise validation.

    Returns:
        Complete encoded synthetic JPEG bytes.
    """
    output = BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(output, format="JPEG")
    return output.getvalue()


def cover_result(
    name: str = "Record",
    artist: str = "Alpha",
    state: CoverState = "ready",
    count: int = 1,
    fetched_at: str = "2026-11-22T10:00:00+00:00",
    color: str = "#698e8c",
) -> CoverFetchResult:
    """Build deterministic name evidence and optional validated synthetic artwork.

    Args:
        name: Synthetic original album title.
        artist: Synthetic complete credited artist name.
        state: Deliberate search and artwork outcome.
        count: Number of captured requests or exact-name candidates.
        fetched_at: Aware retrieval date, independent of listening dates.
        color: Synthetic thumbnail background color.

    Returns:
        Dated synthetic name evidence and optional validated artwork.
    """
    candidates = []
    for index in range(min(count, 5)):
        candidates.append(
            CoverCandidate(
                str(uuid5(NAMESPACE_URL, artist + name + str(index))),
                name,
                artist,
                f"Synthetic candidate {index}",
            )
        )
    image = validate_cover_image(jpeg(color)) if state == "ready" else None
    art = (
        cover_artwork(
            image, str(uuid5(NAMESPACE_URL, artist + name + "release")), "12345"
        )
        if image
        else None
    )
    metadata = AlbumCoverMetadata(
        album(name, artist).key,
        name,
        artist,
        state,
        tuple(candidates),
        count,
        fetched_at,
        art,
    )
    return CoverFetchResult(metadata, image)


@dataclass
class FixtureCoverSource:
    """Record requested fixture album names while returning no-network artwork.

    Args:
        configured: Whether explicit fixture lookups are available.
        fail: Whether the controlled provider raises a safe error.
        names: Captured requested fixture titles.
    """

    configured: bool = True
    fail: bool = False
    names: list[str] = field(default_factory=list)

    async def fetch(self, selected: RankedEntity) -> CoverFetchResult:
        """Return one complete current fixture observation or deliberate failure.

        Args:
            selected: Captured synthetic album and artist identity.

        Returns:
            Complete controlled provider evidence and optional artwork.
        """
        self.names.append(selected.name)
        if self.fail:
            raise CoverSourceError("Fixture cover provider unavailable.")
        return cover_result(
            selected.name, selected.artist, fetched_at=datetime.now(UTC).isoformat()
        )
