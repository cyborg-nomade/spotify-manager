"""Choose album editions and load all proposals before accepting remote writes."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Literal
from typing import Protocol

from spotify_manager.application.album_recommendations import choose_album
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_selection import PendingAlbum
from spotify_manager.domain.album_selection import SauvignonResult


@dataclass(frozen=True)
class AlbumEditionChoice:
    """Apply the edition policy before requesting an operator choice.

    Args:
        reader: Optional operator interaction for ambiguous editions.
        skip: Original skip response marker.
        quit: Original quit response marker.
    """

    reader: Callable[[AlbumRecommendation, tuple[SpotifyAlbumOption, ...]], str] | None
    skip: str = "skip"
    quit: str = "quit"

    def choose(
        self, item: AlbumRecommendation
    ) -> SpotifyAlbumOption | Literal["skip", "quit"]:
        """Resolve equivalent editions directly and prompt only for ambiguity.

        Args:
            item: Ranked album evidence and original ordered options.

        Returns:
            Accepted edition, skip or quit.
        """
        return choose_album(item, self.reader, self.skip, self.quit)


class AlbumMarkers(Protocol):
    """Read a playable first track for an accepted edition."""

    def first(self, album: SpotifyAlbumOption) -> FirstTrack:
        """Read the original marker before any playlist mutation.

        Args:
            album: Accepted edition.

        Returns:
            First playable track.
        """


@dataclass
class AlbumSelection:
    """Retain artist and album uniqueness in original ranked interaction order.

    Args:
        choice: Named edition-choice stage.
        catalog: Original first-track observation integration.
        dry_run: Record proposals rather than completed additions.
        artists: Primary artist keys already selected in this invocation.
        albums: Album identities already selected in this invocation.
        results: Original ordered selection outcomes.
        pending: Original ordered proposed marker additions.
        paused: Whether the operator has requested a pause.
    """

    choice: AlbumEditionChoice
    catalog: AlbumMarkers
    dry_run: bool
    artists: set[str] = field(default_factory=set)
    albums: set[str] = field(default_factory=set)
    results: list[SauvignonResult] = field(default_factory=list)
    pending: list[PendingAlbum] = field(default_factory=list)
    paused: bool = False

    def run(
        self, recommendations: tuple[AlbumRecommendation, ...], requested: int
    ) -> None:
        """Observe ordered choices until enough additions or the original quit.

        Args:
            recommendations: Original ranked album evidence.
            requested: Maximum proposed additions.

        Raises:
            SauvignonSpotifyError: A selected album lacks a playable marker.
        """
        for item in recommendations:
            if len(self.pending) >= requested:
                return
            self._select(item)
            if self.paused:
                return

    def _select(self, item: AlbumRecommendation) -> None:
        if item.key[0] in self.artists:
            self.results.append(
                SauvignonResult(item, None, None, "artist already selected")
            )
            return
        choice = self.choice.choose(item)
        if choice == "quit":
            self.results.append(SauvignonResult(item, None, None, "quit"))
            self.paused = True
            return
        if choice == "skip":
            self.results.append(SauvignonResult(item, None, None, "skipped"))
            return
        if choice.spotify_id in self.albums:
            self.results.append(
                SauvignonResult(item, choice, None, "already represented")
            )
            return
        self._remember(item, choice)

    def _remember(self, item: AlbumRecommendation, album: SpotifyAlbumOption) -> None:
        track = self.catalog.first(album)
        self.results.append(
            SauvignonResult(
                item, album, track, "would add" if self.dry_run else "added"
            )
        )
        self.pending.append((album, track))
        self.artists.add(item.key[0])
        self.albums.add(album.spotify_id)
