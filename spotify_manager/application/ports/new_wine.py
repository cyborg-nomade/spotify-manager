"""External effects and durable observations required by New Wine execution."""

from typing import Protocol

from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation


class NewWineAccess(Protocol):
    """Read live playlists and perform each original effect at its boundary."""

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read ordered live markers.

        Args:
            playlist_id: Configured playlist identifier.

        Returns:
            Parsed playable markers in original order.
        """

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Resolve namespace access and read durable state or fresh preview defaults.

        Args:
            dry_run: Whether to omit the durable read.

        Returns:
            Original namespace with unknown fields retained.
        """

    def save(self, state: dict[str, object]) -> None:
        """Persist one complete namespace checkpoint.

        Args:
            state: Current working namespace.
        """

    def append(self, playlist_id: str, track: ReleaseTrack) -> None:
        """Append a replacement marker.

        Args:
            playlist_id: Destination playlist.
            track: Accepted replacement.
        """

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove a source after additions are secure.

        Args:
            playlist_id: Source playlist.
            source: Original marker.
        """

    def saved(self, release: ReleaseCandidate, *, removing: bool = False) -> bool:
        """Observe saved-album membership with its original tolerant parsing.

        Args:
            release: Release whose current membership is needed.
            removing: Whether this read belongs to the drop path's SDK boundary.

        Returns:
            First truthy status, or false for an absent/malformed response.
        """

    def save_album(self, release: ReleaseCandidate) -> None:
        """Save a qualifying album remotely.

        Args:
            release: Selected album to save.
        """

    def unsave_album(self, release: ReleaseCandidate) -> None:
        """Unsave an album that failed the keep rule.

        Args:
            release: Selected album to remove.
        """

    def mirror_album(self, release: ReleaseCandidate) -> None:
        """Ensure a kept album exists in the canonical mirror and statistics.

        Args:
            release: Album accepted by the live keep rule.
        """

    def remove_mirror_album(self, release: ReleaseCandidate) -> None:
        """Remove an unsaved album from the canonical mirror and statistics.

        Args:
            release: Album just removed remotely.
        """

    def removed_audit(
        self, release: ReleaseCandidate, evaluation: AlbumEvaluation, reason: str
    ) -> None:
        """Append the original removed-album recovery record.

        Args:
            release: Album just removed remotely and from its mirror.
            evaluation: Original live keep evaluation.
            reason: Original drop action string.
        """

    def audit(self, run_id: str, result: FlushResult) -> None:
        """Append a completed or skipped result, including previews.

        Args:
            run_id: Original execution identifier.
            result: Original public result value.
        """

    def refill(
        self,
        cellar_id: str,
        no_discovery: bool,
        dry_run: bool,
        state: dict[str, object],
        run: dict[str, object],
        projected: set[str] | None,
    ) -> CellarRefillSummary:
        """Compose the established cellar use case at the post-flush boundary.

        Args:
            cellar_id: Effective cellar source from saved state or current settings.
            no_discovery: Effective library-affinity requirement.
            dry_run: Whether to preview transfers.
            state: Complete namespace.
            run: Active run within the namespace.
            projected: Preview destination membership after planned transitions.

        Returns:
            Existing refill summary.
        """


class NewWinePresentation(Protocol):
    """Render New Wine facts and effects at application-selected boundaries."""

    def canonical(self, source: PlaylistTrack, count: int) -> None:
        """Show an accepted canonical endpoint.

        Args:
            source: Marker chosen as the endpoint.
            count: Canonical track count.
        """

    def no_releases(self, source: PlaylistTrack, year: int) -> None:
        """Show absence of current-year primary-credit candidates.

        Args:
            source: Original marker.
            year: Existing active year.
        """

    def only_single(self, source: PlaylistTrack, year: int) -> None:
        """Show the original automatic single-drop reason.

        Args:
            source: Only current-year single marker.
            year: Existing active year.
        """

    def empty(self, release: ReleaseCandidate) -> None:
        """Show an empty selected release.

        Args:
            release: Selection with no playable tracks.
        """

    def empty_continuation(self, release: ReleaseCandidate) -> None:
        """Show why a selected follow-up was omitted.

        Args:
            release: Follow-up with no playable tracks.
        """

    def not_kept(self, release: ReleaseCandidate, evaluation: AlbumEvaluation) -> None:
        """Show why a Sauvignon album remains unsaved.

        Args:
            release: Completed release.
            evaluation: Observed live keep decision.
        """

    def kept(
        self,
        release: ReleaseCandidate,
        evaluation: AlbumEvaluation,
        saved: bool,
        dry_run: bool,
    ) -> None:
        """Show the original save, preview or already-saved outcome.

        Args:
            release: Completed release.
            evaluation: Live keep decision.
            saved: Saved status observed before this effect.
            dry_run: Whether to use preview wording.
        """

    def resumed(self, source: PlaylistTrack) -> None:
        """Show execution of a saved plan whose source is already absent.

        Args:
            source: Original saved marker.
        """

    def advanced(self, target: ReleaseTrack, dry_run: bool) -> None:
        """Show an accepted or previewed replacement marker.

        Args:
            target: Selected replacement.
            dry_run: Whether to use preview wording.
        """

    def sauvignon(self, release: ReleaseCandidate, dry_run: bool) -> None:
        """Show a marker added to Sauvignon.

        Args:
            release: Completed release routed to Sauvignon.
            dry_run: Whether to use preview wording.
        """

    def removed_album(
        self,
        release: ReleaseCandidate,
        evaluation: AlbumEvaluation,
        saved: bool,
        dry_run: bool,
    ) -> None:
        """Show album-removal eligibility and its original membership observation.

        Args:
            release: Rejected album.
            evaluation: Live keep decision.
            saved: Status observed before removal.
            dry_run: Whether to use preview wording.
        """

    def continuation(
        self, release: ReleaseCandidate, target: ReleaseTrack, dry_run: bool
    ) -> None:
        """Show a newly secured follow-up marker.

        Args:
            release: Accepted follow-up release.
            target: First playable follow-up track.
            dry_run: Whether to use preview wording.
        """

    def removed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show completion of source removal, including resumed plans.

        Args:
            source: Original marker.
            dry_run: Whether to use preview wording.
        """
