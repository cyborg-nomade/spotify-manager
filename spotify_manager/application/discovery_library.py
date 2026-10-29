"""Reconcile completed discovery releases at the original effect boundaries."""

from dataclasses import dataclass

from spotify_manager.application.ports.discovery import DiscoveryAudit
from spotify_manager.application.ports.discovery import DiscoveryLibrary
from spotify_manager.application.ports.discovery import DiscoveryLibraryPresentation
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation


@dataclass(frozen=True)
class DiscoveryLibraryReconciliation:
    """Apply a live keep decision without changing recovery or mirror ordering.

    Args:
        access: Saved membership, remote changes, recovery log and mirror boundary.
        audit: Original routine event sink, including preview events.
        presentation: Original outcome renderer.
        dry_run: Whether to suppress writes while retaining observations and audit.
    """

    access: DiscoveryLibrary
    audit: DiscoveryAudit
    presentation: DiscoveryLibraryPresentation
    dry_run: bool

    async def reconcile(
        self, release: RankedRelease, evaluation: AlbumEvaluation
    ) -> str:
        """Reconcile one release and report its original action string.

        Args:
            release: Completed discovery release.
            evaluation: Accepted live evaluation from the durable plan.

        Returns:
            Existing kept, absent, saved, removed or preview action.

        Raises:
            OSError: An external write fails; later effects are not attempted.
        """
        saved = await self.access.saved(release)
        should_save = evaluation.decision == "keep"
        action = await self._change(release, evaluation, saved, should_save)
        if not self.dry_run:
            await self.access.mirror(release, should_save)
        await self._audit(release, evaluation, action)
        self.presentation.reconciled(release, evaluation, action, self.dry_run)
        return action

    async def _change(
        self,
        release: RankedRelease,
        evaluation: AlbumEvaluation,
        saved: bool,
        should_save: bool,
    ) -> str:
        if saved == should_save:
            return "kept" if should_save else "absent"
        if self.dry_run:
            return "would save" if should_save else "would remove"
        if should_save:
            await self.access.save_album(release)
            return "saved"
        await self.access.remove_album(release)
        await self.access.removed_audit(release, evaluation)
        return "removed"

    async def _audit(
        self, release: RankedRelease, evaluation: AlbumEvaluation, action: str
    ) -> None:
        await self.audit.event(
            "release_library_checked",
            artist=release.primary_artist_name,
            release=release.name,
            release_id=release.spotify_id,
            liked_tracks=evaluation.liked_tracks,
            total_tracks=evaluation.total_tracks,
            decision=evaluation.decision,
            action=action,
            dry_run=self.dry_run,
        )
