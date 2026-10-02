"""Original New Wine messages, separated from planning and ordered execution."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation


@dataclass(frozen=True)
class NewWinePresenter:
    """Render unchanged messages at application-selected observation/effect boundaries.

    Args:
        echo: Caller-owned message sink.
    """

    echo: Callable[[str], None]

    def canonical(self, source: PlaylistTrack, count: int) -> None:
        """Show an accepted canonical endpoint.

        Args:
            source: Marker chosen as the endpoint.
            count: Canonical track count.
        """
        self.echo(
            f"Using {source.name} as the canonical endpoint of "
            f"{source.release.name} ({count} tracks)."
        )

    def no_releases(self, source: PlaylistTrack, year: int) -> None:
        """Show absence of current-year primary-credit candidates.

        Args:
            source: Original marker.
            year: Existing active year.
        """
        self.echo(
            f"No {year} primary-artist releases found for "
            f"{source.primary_artist_name}; skipping this run."
        )

    def only_single(self, source: PlaylistTrack, year: int) -> None:
        """Show the original automatic single-drop reason.

        Args:
            source: Only current-year single marker.
            year: Existing active year.
        """
        self.echo(
            f"{source.release.name} is the only {year} release for "
            f"{source.primary_artist_name}; dropping it automatically."
        )

    def empty(self, release: ReleaseCandidate) -> None:
        """Show an empty selected release.

        Args:
            release: Selection with no playable tracks.
        """
        self.echo(f"{release.name} has no available tracks; skipping.")

    def empty_continuation(self, release: ReleaseCandidate) -> None:
        """Show why a selected follow-up was omitted.

        Args:
            release: Follow-up with no playable tracks.
        """
        self.echo(
            f"{release.name} has no available tracks; "
            "finishing without a follow-up release."
        )

    def not_kept(self, release: ReleaseCandidate, evaluation: AlbumEvaluation) -> None:
        """Show why a Sauvignon album remains unsaved.

        Args:
            release: Completed release.
            evaluation: Observed live keep decision.
        """
        self.echo(
            f"Left {release.name} unsaved: {evaluation.liked_tracks}/"
            f"{evaluation.total_tracks} liked."
        )

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
        action = (
            "Would save"
            if dry_run and not saved
            else "Saved"
            if not saved
            else "Kept saved"
        )
        self.echo(
            f"{action} {release.name}: {evaluation.liked_tracks}/"
            f"{evaluation.total_tracks} liked."
        )

    def resumed(self, source: PlaylistTrack) -> None:
        """Show execution of a saved plan whose source is already absent.

        Args:
            source: Original saved marker.
        """
        self.echo(f"Source already removed; completing saved plan for {source.name}.")

    def advanced(self, target: ReleaseTrack, dry_run: bool) -> None:
        """Show an accepted or previewed replacement marker.

        Args:
            target: Selected replacement.
            dry_run: Whether to use preview wording.
        """
        self.echo(f"{'Would add' if dry_run else 'Added'} next track: {target.name}")

    def sauvignon(self, release: ReleaseCandidate, dry_run: bool) -> None:
        """Show a marker added to Sauvignon.

        Args:
            release: Completed release routed to Sauvignon.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would add' if dry_run else 'Added'} to Sauvignon "
            f"Terre-Neuve: {release.name}"
        )

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
        if not saved:
            self.echo(
                f"{release.name} is already absent from saved albums; "
                "no library removal needed."
            )
            return
        action = "Would unsave" if dry_run else "Unsave check complete for"
        self.echo(
            f"{action} {release.name}: {evaluation.liked_tracks}/"
            f"{evaluation.total_tracks} liked."
        )

    def continuation(
        self, release: ReleaseCandidate, target: ReleaseTrack, dry_run: bool
    ) -> None:
        """Show a newly secured follow-up marker.

        Args:
            release: Accepted follow-up release.
            target: First playable follow-up track.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would start' if dry_run else 'Started'} follow-up release: "
            f"{release.name} - {target.name}"
        )

    def removed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show completion of source removal, including resumed plans.

        Args:
            source: Original marker.
            dry_run: Whether to use preview wording.
        """
        self.echo(
            f"{'Would remove' if dry_run else 'Removed'} previous track: {source.name}"
        )
