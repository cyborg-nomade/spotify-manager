"""Review releases sequentially and retain accepted-write restart ordering."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.release_check_values import ReleaseCheckError
from spotify_manager.application.release_destinations import ReleaseDestinations
from spotify_manager.application.release_progress import ReleaseProgress
from spotify_manager.application.release_results import release_result
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_catalog import current_editions
from spotify_manager.domain.release_catalog import eligible_records
from spotify_manager.domain.release_catalog import ordered_releases
from spotify_manager.domain.release_check import artist_is_present
from spotify_manager.domain.release_check import future_record
from spotify_manager.domain.release_check import release_scope_reason
from spotify_manager.domain.release_check import track_is_present
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import PlaylistAction
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseCheckResult
from spotify_manager.domain.release_check_values import ReleaseTrack


type ReleaseChoiceReader = Callable[
    [RankedArtist, ReleaseCandidate, ReleaseTrack, tuple[str, ...], bool], str
]


@dataclass(frozen=True)
class ReleaseAssessment:
    """Original loaded marker and eligibility observations for one release.

    Args:
        track: Playable first marker, including a retained pending marker.
        linked: Matching announced future record, when present.
        reason: Original exclusion reason.
        unattached: Single without an eligible containing record.
    """

    track: ReleaseTrack | None
    linked: ReleaseCandidate | None = None
    reason: str | None = None
    unattached: bool = False


@dataclass
class ReleaseCatalog:
    """Retain ordered containing records and their per-artist cache.

    Args:
        future: Eligible definitely future albums or EPs.
        current: Eligible current albums or EPs.
        pending: Valid retained singles for this artist.
        releases: Calendar-ordered releases to review.
        tracks: Cache shared across this artist's singles.
    """

    future: tuple[ReleaseCandidate, ...]
    current: tuple[ReleaseCandidate, ...]
    pending: dict[str, PendingSingle]
    releases: tuple[ReleaseCandidate, ...]
    tracks: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ReleaseReview:
    """Coordinate release observations, user choices and ordered destination writes.

    Args:
        progress: Original state authority and accepted checkpoints/audits.
        destinations: Original mutable memberships and destination identities.
        reader: Optional original release-choice callback.
    """

    progress: ReleaseProgress
    destinations: ReleaseDestinations
    reader: ReleaseChoiceReader | None

    def check_artist(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate
    ) -> bool:
        """Review an artist's current and pending releases before marking completion.

        Args:
            artist: Frozen ranked artist.
            mapped: Accepted Spotify mapping.

        Returns:
            Whether the artist completed rather than pausing at a release choice.
        """
        self.progress.notify(f"#{artist.rank} {artist.name}: checking releases")
        plan = self._catalog(artist, mapped)
        for release in plan.releases:
            pending = plan.pending.get(release.spotify_id)
            if release.spotify_id in self.progress.processed and pending is None:
                continue
            if not self._review(artist, mapped, release, pending, plan):
                return False
        self.progress.complete(artist)
        self.progress.notify(f"#{artist.rank} {artist.name}: complete")
        return True

    def _catalog(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate
    ) -> ReleaseCatalog:
        opening = self.progress.opening
        catalog = self.progress.effects.catalog(artist, mapped, opening.checked_from)
        future: list[ReleaseCandidate] = []
        for release in catalog:
            if future_record(release, opening.checked_through, artist.rank):
                future.append(release)
        current, duplicates = current_editions(
            catalog, opening.checked_from, opening.checked_through
        )
        self._record_duplicates(artist, mapped, duplicates)
        records = eligible_records(current, artist.rank)
        pending = self._pending(artist)
        return ReleaseCatalog(
            tuple(future), records, pending, ordered_releases(current, pending)
        )

    def _record_duplicates(
        self,
        artist: RankedArtist,
        mapped: SpotifyArtistCandidate,
        duplicates: tuple[ReleaseCandidate, ...],
    ) -> None:
        for release in duplicates:
            if release.spotify_id in self.progress.processed:
                continue
            result = release_result(
                artist,
                mapped,
                release,
                reason="duplicate Spotify market edition",
                dry_run=self.progress.preview,
            )
            self.progress.record(result)

    def _pending(self, artist: RankedArtist) -> dict[str, PendingSingle]:
        pending: dict[str, PendingSingle] = {}
        for release_id, raw in self.progress.pending.items():
            single = self.progress.effects.decode_pending(raw)
            if single is not None and single.artist_key == artist.key:
                pending[release_id] = single
        return pending

    def _assess(
        self,
        artist: RankedArtist,
        release: ReleaseCandidate,
        pending: PendingSingle | None,
        plan: ReleaseCatalog,
    ) -> ReleaseAssessment:
        track = pending.first_track if pending else None
        if release.release_type == "Single":
            track = (
                track
                if track is not None
                else self.progress.effects.first_track(release)
            )
            return self._single(artist, track, plan)
        reason = release_scope_reason(release, artist.rank)
        if reason is not None:
            return ReleaseAssessment(track, reason=reason)
        track = self.progress.effects.first_track(release)
        return ReleaseAssessment(
            track, reason=None if track else "release has no playable first track"
        )

    def _single(
        self, artist: RankedArtist, track: ReleaseTrack | None, plan: ReleaseCatalog
    ) -> ReleaseAssessment:
        if track is None:
            return ReleaseAssessment(None, reason="release has no playable first track")
        if artist.accepts_all_singles:
            return ReleaseAssessment(track)
        linked = self.progress.effects.match(track, plan.future, plan.tracks)
        if linked is not None:
            return ReleaseAssessment(track, linked)
        current = self.progress.effects.match(track, plan.current, plan.tracks)
        if current is not None:
            return ReleaseAssessment(
                track, reason="containing album or EP has already been released"
            )
        return ReleaseAssessment(track, unattached=True)

    def _review(
        self,
        artist: RankedArtist,
        mapped: SpotifyArtistCandidate,
        release: ReleaseCandidate,
        pending: PendingSingle | None,
        plan: ReleaseCatalog,
    ) -> bool:
        self.progress.opening.active["pending_release_id"] = release.spotify_id
        assessment = self._assess(artist, release, pending, plan)
        if assessment.reason is not None:
            result = release_result(
                artist,
                mapped,
                release,
                track=assessment.track,
                reason=assessment.reason,
                dry_run=self.progress.preview,
            )
            self.progress.record(result)
            self.progress.finish_release()
            return True
        assert assessment.track is not None
        return self._eligible(artist, mapped, release, assessment)

    def _eligible(
        self,
        artist: RankedArtist,
        mapped: SpotifyArtistCandidate,
        release: ReleaseCandidate,
        assessment: ReleaseAssessment,
    ) -> bool:
        assert assessment.track is not None
        vintage = artist.is_new_vintage and (
            release.release_type != "Single" or artist.accepts_all_singles
        )
        wine_present = artist_is_present(self.destinations.wine, mapped)
        destinations: list[str] = []
        if not wine_present:
            destinations.append("Wine Cellar")
        if vintage and not track_is_present(
            self.destinations.vintage, assessment.track
        ):
            destinations.append("New Vintage")
        choice = self._choice(artist, release, assessment, tuple(destinations))
        if choice == "quit":
            self.progress.pause(artist, release.name)
            return False
        result = self._decision(
            artist, mapped, release, assessment, choice, wine_present, vintage
        )
        self.progress.record(result, terminal=choice != "pending")
        self.progress.finish_release()
        return True

    def _choice(
        self,
        artist: RankedArtist,
        release: ReleaseCandidate,
        assessment: ReleaseAssessment,
        destinations: tuple[str, ...],
    ) -> str:
        choice = "pending" if assessment.unattached and destinations else "add"
        if not destinations or self.reader is None:
            return choice
        if not self.progress.preview:
            self.progress.save()
        assert assessment.track is not None
        return self.reader(
            artist, release, assessment.track, destinations, assessment.unattached
        )

    def _decision(
        self,
        artist: RankedArtist,
        mapped: SpotifyArtistCandidate,
        release: ReleaseCandidate,
        assessment: ReleaseAssessment,
        choice: str,
        wine_present: bool,
        vintage: bool,
    ) -> ReleaseCheckResult:
        if choice == "pending" and not assessment.unattached:
            raise ReleaseCheckError("Only an unattached single can remain pending.")
        if choice not in {"add", "pending", "skip"}:
            raise ReleaseCheckError("The release review choice is invalid.")
        if choice == "pending":
            assert assessment.track is not None
            self.progress.store_pending(
                PendingSingle(artist.key, release, assessment.track)
            )
            return release_result(
                artist,
                mapped,
                release,
                track=assessment.track,
                reason="single kept pending for a future album or EP",
                dry_run=self.progress.preview,
            )
        if choice == "skip":
            return release_result(
                artist,
                mapped,
                release,
                track=assessment.track,
                linked_future_release=assessment.linked,
                reason="skipped by user",
                dry_run=self.progress.preview,
            )
        return self._add(artist, mapped, release, assessment, wine_present, vintage)

    def _add(
        self,
        artist: RankedArtist,
        mapped: SpotifyArtistCandidate,
        release: ReleaseCandidate,
        assessment: ReleaseAssessment,
        wine_present: bool,
        vintage: bool,
    ) -> ReleaseCheckResult:
        assert assessment.track is not None
        wine_action: PlaylistAction = "artist already present"
        if not wine_present:
            wine_action = self.progress.effects.add(
                self.destinations.wine_id,
                self.destinations.wine,
                assessment.track,
                self.progress.preview,
            )
        vintage_action: PlaylistAction = "not applicable"
        if vintage:
            vintage_action = self.progress.effects.add(
                self.destinations.vintage_id,
                self.destinations.vintage,
                assessment.track,
                self.progress.preview,
            )
        return release_result(
            artist,
            mapped,
            release,
            track=assessment.track,
            linked_future_release=assessment.linked,
            wine_cellar_action=wine_action,
            new_vintage_action=vintage_action,
            dry_run=self.progress.preview,
        )
