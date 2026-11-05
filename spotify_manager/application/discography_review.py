"""Review artist checklists and resolve explicit album additions before packing."""

from dataclasses import dataclass
from dataclasses import replace

from spotify_manager.application.discography_values import DiscographyAlbumError
from spotify_manager.application.discography_values import DiscographyCancelledError
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.application.ports.discography_review import DiscographyAlbumAccess
from spotify_manager.application.ports.discography_review import DiscographyReviewReader
from spotify_manager.application.ports.discography_review import ReleaseReviewDraft
from spotify_manager.domain.discography_batches import selected_releases
from spotify_manager.domain.discography_links import ReviewRelease
from spotify_manager.domain.discography_links import album_reference
from spotify_manager.domain.discography_links import merge_review_release
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import QueueArtist


@dataclass(frozen=True)
class DiscographyReleaseReview:
    """Own read-only edits using explicit operator and album resources.

    Args:
        albums: Exact album metadata and saved-status observations.
        reader: Operator decisions and cancellation resource.
    """

    albums: DiscographyAlbumAccess
    reader: DiscographyReviewReader

    async def run(
        self,
        artist: QueueArtist,
        catalog: tuple[CatalogRelease, ...],
        remaining: int | None = None,
    ) -> tuple[CatalogRelease, ...]:
        """Return exact reviewed editions without playlist or state writes.

        Args:
            artist: Current stable queue artist.
            catalog: Automatically fetched canonical choices.
            remaining: Available weekly slots, or None for the first artist.

        Returns:
            Confirmed chronological editions, or empty for a declined artist.

        Raises:
            DiscographyCancelledError: The operator quits.
            DiscographyError: An interaction supplies an unsupported action.
        """
        draft = _draft(artist, catalog, remaining)
        while True:
            self.reader.check()
            answer = await self.reader.review_releases(draft)
            self.reader.check()
            if answer.choice == "quit":
                raise DiscographyCancelledError("Discography planning cancelled.")
            if answer.choice == "none":
                return ()
            releases = tuple(entry.release for entry in draft.entries)
            selected = selected_releases(releases, answer.release_ids)
            if selected is None:
                draft = replace(
                    draft, notices=("Selected releases are not available.",)
                )
                continue
            if answer.choice == "select":
                return selected
            if answer.choice != "add":
                raise DiscographyError("Discography review choice is not available.")
            draft = replace(draft, selected_ids=answer.release_ids, notices=())
            draft = await self._add(draft, answer.references)

    async def _add(
        self, draft: ReleaseReviewDraft, references: tuple[str, ...]
    ) -> ReleaseReviewDraft:
        if not references:
            return replace(draft, notices=("Enter one or more Spotify album links.",))
        for reference in references:
            self.reader.check()
            draft = await self._addition(draft, reference)
        return draft

    async def _addition(
        self, draft: ReleaseReviewDraft, reference: str
    ) -> ReleaseReviewDraft:
        try:
            identity = album_reference(reference)
        except ValueError as exc:
            return _notice(draft, f"{reference}: {exc}")
        for entry in draft.entries:
            if entry.release.spotify_id == identity:
                return _select_added(
                    draft, entry, "Already listed; selected existing option"
                )
        try:
            entry = await self.albums.album(identity)
        except DiscographyAlbumError as exc:
            return _notice(draft, f"{reference}: {exc}")
        self.reader.check()
        return _select_added(draft, entry, "Added")


def _draft(
    artist: QueueArtist, catalog: tuple[CatalogRelease, ...], remaining: int | None
) -> ReleaseReviewDraft:
    entries = tuple(ReviewRelease(release) for release in catalog)
    selected = []
    for release in catalog:
        if release.default:
            selected.append(release.spotify_id)
    return ReleaseReviewDraft(artist, entries, tuple(selected), remaining)


def _notice(draft: ReleaseReviewDraft, message: str) -> ReleaseReviewDraft:
    return replace(draft, notices=(*draft.notices, message))


def _select_added(
    draft: ReleaseReviewDraft, entry: ReviewRelease, label: str
) -> ReleaseReviewDraft:
    identity = entry.release.spotify_id
    selected = draft.selected_ids
    if identity not in selected:
        selected = (*selected, identity)
    updated = replace(
        draft, entries=merge_review_release(draft.entries, entry), selected_ids=selected
    )
    return _notice(updated, f"{label}: {entry.release.name} ({identity})")
