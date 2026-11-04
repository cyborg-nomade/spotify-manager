"""Review successive eligible albums before applying one Requeue transition."""

from dataclasses import dataclass
from dataclasses import replace

from spotify_manager.application.ports.listening import MessageSink
from spotify_manager.application.ports.requeue import RequeueAlbumReader
from spotify_manager.application.ports.requeue import RequeueCatalog
from spotify_manager.application.requeue_result import RequeueForADreamError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography import release_transition
from spotify_manager.domain.requeue import RequeuePlan
from spotify_manager.domain.requeue import cancel_transition
from spotify_manager.domain.requeue import plan_transition


@dataclass(frozen=True)
class RequeueAlbumSelection:
    """Own album review without mutating the playlist or persisting choices.

    Args:
        catalog: Eligible release track observations.
        reader: Explicit operator decisions for proposed albums.
        progress: Optional caller-owned progress and cancellation boundary.
    """

    catalog: RequeueCatalog
    reader: RequeueAlbumReader
    progress: MessageSink | None

    async def select(
        self,
        playlist: tuple[PlaylistTrack, ...],
        discography: tuple[DiscographyRelease, ...],
    ) -> RequeuePlan:
        """Offer successors until one is accepted, selection is cancelled or exhausted.

        Args:
            playlist: Nonempty original source markers.
            discography: Already selected and chronologically ordered releases.

        Returns:
            Accepted transition or the existing completion/ineligible outcome.

        Raises:
            RequeueForADreamError: The interaction returns an unsupported action.
        """
        current, following = release_transition(playlist[0].release.name, discography)
        skipped = False
        while following is not None:
            choice = await self.reader.choose_album(playlist[0], following)
            if choice == "cancel":
                return cancel_transition(playlist)
            if choice == "accept":
                return await self._accept(playlist, current, following)
            if choice != "skip":
                raise RequeueForADreamError(
                    "Album choice must be accept, skip or cancel."
                )
            skipped = True
            _, following = release_transition(following.name, discography)
        plan = plan_transition(playlist, current, None, ())
        if skipped:
            return replace(plan, reason="all remaining eligible albums were skipped")
        return plan

    async def _accept(
        self,
        playlist: tuple[PlaylistTrack, ...],
        current: DiscographyRelease | None,
        release: DiscographyRelease,
    ) -> RequeuePlan:
        if self.progress is not None:
            self.progress.echo(f"Loading {release.name}")
        tracks = await self.catalog.release_tracks(release)
        return plan_transition(playlist, current, release, tracks)
