"""In-memory application ports that reproduce original Queue fill observations."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.application.queue_fill import QueueFill
from spotify_manager.application.queue_fill_effects import QueueFillState
from spotify_manager.application.queue_fill_values import FillResult
from spotify_manager.application.queue_fill_values import QueueFillRequest
from spotify_manager.application.queue_values import QueueSpotifyError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.queue_values import ArtistHistory
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.domain.release_check_values import RankedArtist
from tests.support.queue_fill import ARTIST
from tests.support.queue_fill import FillObservations
from tests.support.queue_neighbors import NOW
from tests.support.queue_neighbors import WEEK


@dataclass
class MemoryQueueFill:
    """Supply typed in-memory boundaries without invoking the legacy runner.

    Args:
        observations: Original shared scenario observations.
    """

    observations: FillObservations

    def configure(self) -> None:
        """Use direct in-memory calls without recording an external effect."""

    def clock(self) -> datetime:
        """Return the original explicit clock.

        Returns:
            Original fixed UTC timestamp.
        """
        return NOW

    def week(self, now: datetime) -> date:
        """Return the original explicit local week.

        Args:
            now: Original effective timestamp.

        Returns:
            Original fixed listening week.
        """
        assert now == NOW
        return WEEK

    def history(self, preview: bool, now: datetime) -> tuple[tuple[Scrobble, ...], int]:
        """Observe original history without a filesystem or service.

        Args:
            preview: Original preview behavior.
            now: Original effective timestamp.

        Returns:
            Original plays and live additions.
        """
        edge = self.observations
        edge.record("history", preview, now.isoformat())
        edge.progress(0, 0, "history status")
        from tests.support.queue_fill import PLAY

        return (PLAY,), 2

    def queue_length(self) -> int:
        """Observe original Queue membership.

        Returns:
            Original empty membership length.
        """
        self.observations.record("playlist", "queue")
        return 0

    def seeds(
        self,
        history: tuple[ArtistHistory, ...],
        count: int,
        week: date,
    ) -> tuple[ArtistSeed, ...]:
        """Observe original selection arguments.

        Args:
            history: Original aggregated history.
            count: Original seed count.
            week: Original effective week.

        Returns:
            Original fixed ordered seed.
        """
        return self.observations.seeds(history, seed_count=count, week_start=week)

    def candidates(
        self,
        seeds: tuple[ArtistSeed, ...],
        heard: set[str],
        week: date,
        limit: int,
        now: datetime,
    ) -> tuple[ArtistRecommendation, ...]:
        """Observe original gathering arguments.

        Args:
            seeds: Original ordered seeds.
            heard: Original heard identities.
            week: Original effective listening week.
            limit: Original candidate pool limit.
            now: Original effective timestamp.

        Returns:
            Original fixed candidate.
        """
        from tests.support.queue_fill import RECOMMENDATION

        self.observations.record("candidates", sorted(heard), limit)
        return (RECOMMENDATION,)

    def represented(self) -> set[str]:
        """Observe original representation destinations.

        Returns:
            Original configured represented identities.
        """
        self.observations.record(
            "represented", ("queue", "queue2", "new-kids", "queue3")
        )
        return {"artist"} if self.observations.scenario == "represented" else set()

    def state(self) -> QueueFillState:
        """Return caller-owned in-memory state without startup dependencies.

        Returns:
            Original observation state reader and writer.
        """
        return self.observations

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Decode only the trusted in-memory scenario's known mapping.

        Args:
            raw: Original test mapping value.

        Returns:
            Fixed original accepted mapping or a miss.
        """
        return (
            ARTIST
            if isinstance(raw, dict) and raw.get("spotify_id") == "artist"
            else None
        )

    def resolve(
        self, recommendation: ArtistRecommendation
    ) -> SpotifyArtistCandidate | str | None:
        """Observe original interaction arguments without a client or presenter.

        Args:
            recommendation: Original current candidate.

        Returns:
            Original configured mapping, skip, quit or no-match outcome.
        """
        ranked = RankedArtist(
            recommendation.key, recommendation.artist, 0, recommendation.base_rank
        )
        self.observations.record("resolve", asdict(ranked))
        scenario = self.observations.scenario
        if scenario in {"skip", "quit"}:
            return scenario
        return None if scenario == "no-match" else ARTIST

    def top_tracks(self, artist: SpotifyArtistCandidate) -> tuple[CatalogTrack, ...]:
        """Observe original top tracks.

        Args:
            artist: Original accepted mapping.

        Returns:
            Original ordered top tracks.
        """
        from tests.support.queue_fill import TRACK

        self.observations.record("top", artist.spotify_id)
        return (TRACK,)

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Observe original liked membership.

        Args:
            tracks: Original bounded top tracks.

        Returns:
            Original configured liked statuses.
        """
        self.observations.record("liked", [track.spotify_id for track in tracks])
        return {"track": self.observations.scenario == "all-liked"}

    def following(self, artist: SpotifyArtistCandidate) -> bool:
        """Observe and validate original follow status.

        Args:
            artist: Original accepted mapping.

        Returns:
            Original configured follow status.

        Raises:
            QueueSpotifyError: Original scenario returns an invalid response.
        """
        statuses = self.observations.current_user_following_artists([artist.spotify_id])
        if not statuses:
            raise QueueSpotifyError("Spotify returned invalid artist follow status.")
        return statuses[0]

    def follow(self, artist: SpotifyArtistCandidate) -> None:
        """Accept the original follow.

        Args:
            artist: Original accepted mapping.
        """
        self.observations.user_follow_artists([artist.spotify_id])

    def persist_followed(self, artist: SpotifyArtistCandidate) -> None:
        """Observe original persistence after following.

        Args:
            artist: Original accepted mapping.
        """
        self.observations.record("persist-follow", artist.spotify_id)

    def append(self, artist: SpotifyArtistCandidate, track: CatalogTrack) -> None:
        """Accept the original Queue append.

        Args:
            artist: Original accepted mapping.
            track: Original selected marker.
        """
        self.observations.record("append", "queue", track.uri)

    def audit(self, result: FillResult, preview: bool, selected: bool) -> None:
        """Observe original selected and rejection event fields.

        Args:
            result: Original current outcome.
            preview: Original preview behavior.
            selected: Whether an addition was selected.
        """
        details: dict[str, object] = {"result": asdict(result), "dry_run": preview}
        if selected:
            details["lastfm_artist_key"] = result.recommendation.key
        event = "artist_added" if selected and not preview else "fill_candidate"
        self.observations.record("audit", event, details)

    def present(self, result: FillResult, preview: bool) -> None:
        """Observe original addition text after accepted audit.

        Args:
            result: Original selected outcome.
            preview: Original preview behavior.
        """
        assert result.spotify_artist is not None and result.track is not None
        self.observations.echo(
            f"{'Would add' if preview else 'Added'} {result.spotify_artist.name} - "
            f"{result.track.name} to The Queue."
        )

    def progress(self, done: int, total: int, message: str) -> None:
        """Observe original resolution progress.

        Args:
            done: Original completed count.
            total: Original examination bound.
            message: Original resolution text.
        """
        self.observations.progress(done, total, message)


def application_outcome(scenario: str, preview: bool, failure: str | None) -> object:
    """Run the independent application using frozen original scenario facts.

    Args:
        scenario: Original configured interaction and membership outcome.
        preview: Original preview behavior.
        failure: Optional accepted boundary that raises.

    Returns:
        JSON-compatible original results, traces and checkpoint evidence.
    """
    observations = FillObservations(scenario, failure)
    outcome: dict[str, object] = {}
    try:
        result = QueueFill(MemoryQueueFill(observations)).run(
            QueueFillRequest(1, None, 30, preview)
        )
        outcome["result"] = asdict(result)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome.update(
        trace=observations.trace,
        state=observations.state,
        checkpoints=observations.checkpoints,
    )
    return json.loads(json.dumps(outcome, default=str))
