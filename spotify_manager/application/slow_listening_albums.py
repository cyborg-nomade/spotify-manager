"""Checkpoint whole-album rejections separately from declined track markers."""

from dataclasses import dataclass
from typing import cast

from spotify_manager.application.checkpoints import Checkpoint
from spotify_manager.application.slow_listening_values import CHOICE_SKIP_ALBUM
from spotify_manager.application.slow_listening_values import ReleaseActionReader
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.application.slow_listening_values import SlowListeningStateError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


def album_skips(entry: dict[str, object]) -> dict[str, str]:
    """Read an additive edition-ID/name ledger without discarding invalid state.

    Args:
        entry: Current source marker's durable run entry.

    Returns:
        Mutable rejected edition identities and their original display names.

    Raises:
        SlowListeningStateError: The ledger or a stored identity/name is invalid.
    """
    raw = entry.setdefault("skipped_albums", {})
    if not isinstance(raw, dict):
        raise SlowListeningStateError("Slow Listening has invalid skipped albums.")
    for identity, name in raw.items():
        if not isinstance(identity, str) or not identity or not isinstance(name, str):
            raise SlowListeningStateError("Slow Listening has invalid skipped albums.")
    return cast(dict[str, str], raw)


@dataclass(frozen=True)
class AlbumSelection:
    """Retain whole-album decisions across pause, cancellation and restart.

    Args:
        choose: Optional next-album interaction; absent for compatibility readers.
        declined: Edition identities and display names already rejected.
        checkpoint: Invocation-owned persistence of the complete working namespace.
    """

    choose: ReleaseActionReader | None
    declined: dict[str, str]
    checkpoint: Checkpoint

    async def run(
        self, source: PlaylistTrack, target: ReleaseTrack, release: DiscographyRelease
    ) -> str | None:
        """Validate a release choice and checkpoint rejection before continuing.

        Args:
            source: Unchanged playlist marker.
            target: Candidate marker within the proposed next album.
            release: Proposed studio edition.

        Returns:
            Explicit action, or none to use the compatibility track interaction.

        Raises:
            SlowListeningError: The interaction returns an unsupported action.
        """
        if self.choose is None:
            return None
        choice = await self.choose.choose_release(source, target, release)
        if choice not in {"advance", "skip", CHOICE_SKIP_ALBUM, "quit"}:
            raise SlowListeningError(
                "Album action must be accept, skip track/album, or pause."
            )
        if choice == CHOICE_SKIP_ALBUM:
            self.declined[release.spotify_id] = release.name
            await self.checkpoint.save()
        return choice
