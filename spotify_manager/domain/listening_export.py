"""Model an exact playlist addition and reconcile an interrupted append."""

from dataclasses import dataclass
from typing import Literal


SPOTIFY_BATCH_SIZE = 100
SPOTIFY_PLAYLIST_LIMIT = 10_000

type ExportStage = Literal[
    "prepared", "queued", "running", "paused", "failed", "complete"
]
type ExportSourceKind = Literal["albums", "history"]


@dataclass(frozen=True)
class ExportPlaylists:
    """Keep the configured routine destination for each preview mode."""

    palace: str | None = None
    blast: str | None = None

    def destination(self, source: ExportSourceKind) -> str | None:
        """Return the configured playlist for the requested source."""
        return self.palace if source == "albums" else self.blast


@dataclass(frozen=True)
class ExportTrack:
    """Identify one addition and its display credit from the prepared source."""

    uri: str
    name: str
    credit: str


@dataclass(frozen=True)
class ExportSources:
    """Identify the two publications used to prepare a playlist."""

    history: str
    library: str


@dataclass(frozen=True)
class SpotifyDestination:
    """Describe the exact account-owned playlist revision observed at Spotify."""

    identity: str
    name: str
    owner: str
    public: bool
    snapshot: str
    count: int


@dataclass(frozen=True)
class ExportTarget:
    """Keep the chosen name or known playlist and the confirmed account scope."""

    name: str
    account: str
    existing: SpotifyDestination | None


@dataclass(frozen=True)
class ExportPlan:
    """Freeze the published source choices and the exact records to be added."""

    scope: ExportSources
    target: ExportTarget
    tracks: tuple[ExportTrack, ...]


@dataclass(frozen=True)
class AttemptedAppend:
    """Hold the starting position and possible write acknowledgment."""

    offset: int
    uris: tuple[str, ...]
    receipt: str | None = None


class PlaylistExportConflictError(ValueError):
    """Stop when a Spotify playlist no longer matches the confirmed baseline."""


def check_export_size(count: int, target: ExportTarget) -> None:
    """Require a nonempty export that fits the destination playlist.

    Args:
        count: Number of additions.
        target: Chosen new playlist or the observed existing baseline.

    Raises:
        PlaylistExportConflictError: The exact additions exceed available capacity.
    """
    if count == 0:
        raise PlaylistExportConflictError("The preview has no tracks to add.")
    original = target.existing.count if target.existing else 0
    if original + count > SPOTIFY_PLAYLIST_LIMIT:
        raise PlaylistExportConflictError(
            "The playlist would exceed 10,000 tracks. Use a smaller selection."
        )


def observed_append(
    attempt: AttemptedAppend,
    current: SpotifyDestination,
    items: tuple[str | None, ...],
) -> int:
    """Count only a contiguous, exact prefix of the attempted additions.

    Args:
        attempt: The in-flight batch and its absolute start.
        current: Stable playlist facts used to request the observed positions.
        items: Spotify items at those exact positions.

    Returns:
        Matched items, including repeated URIs in their original order.

    Raises:
        PlaylistExportConflictError: Observed items conflict with the confirmed order.
    """
    count = current.count - attempt.offset
    if count < 0 or count > len(attempt.uris):
        raise PlaylistExportConflictError("The playlist length changed during export.")
    if len(items) != count or attempt.uris[:count] != items:
        raise PlaylistExportConflictError("The playlist order changed during export.")
    if count and attempt.receipt and current.snapshot != attempt.receipt:
        raise PlaylistExportConflictError(
            "The playlist changed after Spotify added tracks."
        )
    return count
