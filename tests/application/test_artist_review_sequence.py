"""Replay original artist-review outcomes through independently injected stages."""

from dataclasses import dataclass
from typing import cast

import pytest

from spotify_manager.application.artist_review_effects import ReviewCatalog
from spotify_manager.application.artist_review_effects import ReviewInteraction
from spotify_manager.application.artist_review_membership import MembershipPage
from spotify_manager.application.artist_review_run import ArtistReview
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.application.artist_review_values import ArtistReviewSummary
from spotify_manager.domain.artist_review_values import PlaylistMembership
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.infrastructure.artist_review_records import membership_page
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from tests.support import artist_review_run as original


@dataclass(frozen=True)
class MemoryReview:
    """Supply observed external facts without invoking a production facade or SDK.

    Args:
        edge: Original inputs and accepted authority.
    """

    edge: original.ReviewObservations

    def state(self) -> ArtistReviewState:
        """Load original accepted progress and attach its checkpoint callback.

        Returns:
            Original independently reconstructed mutable progress.
        """
        self.edge.state_access()
        raw = self.edge.load()
        state = ArtistReviewState(
            set(cast(list[str], raw["completed_artist_ids"])),
            cast(dict[str, dict[str, object]], raw["pending_unfollows"]),
            cast(dict[str, dict[str, object]], raw["pending_queue_moves"]),
        )
        state.checkpoint = MemoryReviewCheckpoint(self.edge)
        return state

    def cache(self, refresh: bool) -> None:
        """Observe original cache opening before catalog reads.

        Args:
            refresh: Original requested metadata refresh.
        """
        self.edge.cache(original.PATHS.cache, refresh)

    def pages(self, identity: str) -> MemoryMembershipPages:
        """Select a recorded queue page reader.

        Args:
            identity: Queue identity.

        Returns:
            Named raw page reader.
        """
        return MemoryMembershipPages(self.edge, identity)

    def append(self, identity: str, uri: str, description: str) -> object:
        """Accept the original fake destination effect.

        Args:
            identity: Original destination.
            uri: Original chosen marker.
            description: Original retry presentation, unused by the offline edge.

        Returns:
            Original accepted response.
        """
        return self.edge._post(f"playlists/{identity}/items", {"uris": [uri]})

    def remove(self, identity: str, uris: list[str], description: str) -> object:
        """Accept the original ordered fake source removals.

        Args:
            identity: Original source.
            uris: Original complete batch.
            description: Original retry presentation, unused by the offline edge.

        Returns:
            Original accepted response.
        """
        return self.edge._delete(
            f"playlists/{identity}/items", {"items": [{"uri": uri} for uri in uris]}
        )

    def unfollow(self, uris: list[str], description: str) -> object:
        """Accept the original complete fake unfollow batch.

        Args:
            uris: Original ordered artist URIs.
            description: Original retry presentation, unused by the offline edge.

        Returns:
            Original accepted response.
        """
        return self.edge._delete("me/library", uris=",".join(uris))


@dataclass(frozen=True)
class MemoryReviewCheckpoint:
    """Observe complete model persistence through the recorded state authority.

    Args:
        edge: Recorded state owner.
    """

    edge: original.ReviewObservations

    def save(self, state: ArtistReviewState) -> None:
        """Accept the complete current model.

        Args:
            state: Current review progress.
        """
        self.edge.save(
            {
                "version": 1,
                "completed_artist_ids": sorted(state.completed_artist_ids),
                "pending_unfollows": state.pending_unfollows,
                "pending_queue_moves": state.pending_queue_moves,
            }
        )


def _retain_marker(membership: PlaylistMembership, raw: dict[str, object]) -> None:
    identity = str(raw.get("id") or "").strip()
    if identity:
        membership.track_ids.add(identity)
    artists = cast(list[dict[str, object]], raw["artists"])
    primary = str(artists[0]["id"])
    membership.primary_artist_ids.add(primary)
    uri = str(raw.get("uri") or "").strip()
    if uri:
        membership.track_uris_by_primary_artist.setdefault(primary, []).append(uri)


def _event(run_id: str, name: str, **details: object) -> dict[str, object]:
    return {
        "timestamp": "2026-08-08T00:00:00+00:00",
        "run_id": run_id,
        "event": name,
        **details,
    }


def _run(edge: original.ReviewObservations) -> ArtistReviewSummary:
    memory = MemoryReview(edge)
    storage = MemoryReviewFiles(edge)
    catalog = cast(ReviewCatalog, ScriptedReviewCatalog(edge))
    spotify = memory
    interaction = ReviewInteraction(
        edge.echo,
        None if edge.profile == "no-progress" else edge.progress,
        None if edge.profile == "low-auto-tie" else edge.track_choice,
        None if edge.profile == "release-auto" else edge.release_choice,
    )
    limit = {"limit-zero": 0, "limit-negative": -1}.get(edge.profile)
    return ArtistReview(original.PLAYLISTS, storage, catalog, spotify, interaction).run(
        edge.profile == "cache-refresh", limit
    )


@pytest.mark.parametrize("case", original.cases())
def test_injected_review_matches_original_complete_effects(
    case: dict[str, object],
) -> None:
    """Retain complete decisions, mutation failures and recovery-before-review order.

    Args:
        case: Immutable original complete scenario and observations.
    """
    assert (
        original.outcome(
            cast(str, case["profile"]),
            cast(str | None, case["failure"]),
            cast(bool, case["resume"]),
            _run,
        )
        == case["outcome"]
    )


@pytest.mark.parametrize("case", original.cases())
def test_public_review_matches_original_complete_effects(
    case: dict[str, object],
) -> None:
    """Verify composition preserves the original public runner and caller seams.

    Args:
        case: Immutable original complete scenario and observations.
    """
    assert (
        original.outcome(
            cast(str, case["profile"]),
            cast(str | None, case["failure"]),
            cast(bool, case["resume"]),
        )
        == case["outcome"]
    )


def test_plain_review_state_has_an_explicit_noop_persistence_default() -> None:
    """Retain the original optional persistence callback for plain state callers."""
    state = ArtistReviewState(set(), {}, {})
    state.persist()
    assert state.completed_artist_ids == set()
    assert state.pending_unfollows == {}
    assert state.pending_queue_moves == {}


@dataclass(frozen=True)
class MemoryMembershipPages:
    """Observe queue pages independently of production composition.

    Args:
        edge: Recorded SDK authority.
        identity: Queue identity.
    """

    edge: original.ReviewObservations
    identity: str

    def read_membership(self, offset: int) -> MembershipPage:
        """Read and parse the recorded queue response.

        Args:
            offset: Raw row offset.

        Returns:
            Parsed markers and raw continuation facts.
        """
        return membership_page(
            self.edge._get(f"playlists/{self.identity}/items", 50, offset),
            self.identity,
        )


@dataclass(frozen=True)
class MemoryReviewFiles:
    """Observe file and progress effects through explicit methods.

    Args:
        edge: Recorded file authority.
    """

    edge: original.ReviewObservations

    def artists(self) -> list[YourLibraryArtist]:
        """Observe artists at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.edge.load_models(original.PATHS.artists, YourLibraryArtist)

    def tracks(self) -> list[YourLibraryTrack]:
        """Observe tracks at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.edge.load_models(original.PATHS.liked_tracks, YourLibraryTrack)

    def state(self) -> ArtistReviewState:
        """Observe state at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return MemoryReview(self.edge).state()

    def cache(self, refresh: bool) -> None:
        """Observe cache at the recorded boundary.

        Args:
            refresh: Whether the fixture bypasses existing cache values.
        """
        MemoryReview(self.edge).cache(refresh)

    def run_id(self) -> str:
        """Observe run id at the recorded boundary.

        Returns:
            Recorded boundary result.
        """
        return self.edge.run_id()

    def event(self, run_id: str, name: str, **details: object) -> dict[str, object]:
        """Observe event at the recorded boundary.

        Args:
            run_id: Recorded invocation identity.
            name: Observed label or reference.
            details: Complete recorded event fields.

        Returns:
            Recorded boundary result.
        """
        return _event(run_id, name, **details)

    def append(self, events: list[dict[str, object]]) -> None:
        """Observe append at the recorded boundary.

        Args:
            events: Ordered accepted events.
        """
        self.edge.append(original.PATHS.log, events)

    def save_artists(self, artists: list[YourLibraryArtist]) -> None:
        """Observe save artists at the recorded boundary.

        Args:
            artists: Complete followed-artist models.
        """
        self.edge.save_artists(original.PATHS.artists, artists)

    def stats(self, total: int, removed: int) -> None:
        """Observe stats at the recorded boundary.

        Args:
            total: Original total artist count.
            removed: Original removed artist count.
        """
        self.edge.stats(original.PATHS.stats_history, total, removed)


@dataclass(frozen=True)
class ScriptedReviewCatalog:
    """Supply the original recorded child-stage outcomes.

    Args:
        edge: Recorded catalog stage outcomes.
    """

    edge: original.ReviewObservations

    def tracks(self, artist: YourLibraryArtist) -> list[TrackCandidate]:
        """Observe tracks at the recorded boundary.

        Args:
            artist: Reviewed artist or matching constraint.

        Returns:
            Recorded boundary result.
        """
        return self.edge.ranked_tracks(artist)

    def ranked(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Observe ranked at the recorded boundary.

        Args:
            artist: Reviewed artist or matching constraint.

        Returns:
            Recorded boundary result.
        """
        return self.edge.ranked("ranked", artist)

    def earliest(self, artist: YourLibraryArtist) -> list[ReleaseCandidate]:
        """Observe earliest at the recorded boundary.

        Args:
            artist: Reviewed artist or matching constraint.

        Returns:
            Recorded boundary result.
        """
        return self.edge.ranked("earliest", artist)
