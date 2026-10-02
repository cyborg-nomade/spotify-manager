"""Replay original artist-review outcomes through independently injected stages."""

from dataclasses import dataclass
from functools import partial
from typing import cast

import pytest

from spotify_manager.application.artist_review_effects import ReviewCatalog
from spotify_manager.application.artist_review_effects import ReviewInteraction
from spotify_manager.application.artist_review_effects import ReviewSpotify
from spotify_manager.application.artist_review_effects import ReviewStorage
from spotify_manager.application.artist_review_run import ArtistReview
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.application.artist_review_values import ArtistReviewSummary
from spotify_manager.domain.artist_review_values import PlaylistMembership
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
        state.persist = partial(_persist, self.edge, state)
        return state

    def cache(self, refresh: bool) -> None:
        """Observe original cache opening before catalog reads.

        Args:
            refresh: Original requested metadata refresh.
        """
        self.edge.cache(original.PATHS.cache, refresh)

    def membership(self, identity: str) -> PlaylistMembership:
        """Supply original complete fake queue facts and record the read.

        Args:
            identity: Original queue identity.

        Returns:
            Independent original primary-credit and track indexes.
        """
        self.edge._get(f"playlists/{identity}/items", 50, 0)
        membership = PlaylistMembership(set(), set(), {})
        for raw in self.edge.playlists.get(identity, []):
            _retain_marker(membership, raw)
        return membership

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


def _persist(edge: original.ReviewObservations, state: ArtistReviewState) -> None:
    edge.save(
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
    paths = original.PATHS
    storage = ReviewStorage(
        partial(edge.load_models, paths.artists, YourLibraryArtist),
        partial(edge.load_models, paths.liked_tracks, YourLibraryTrack),
        memory.state,
        memory.cache,
        edge.run_id,
        _event,
        partial(edge.append, paths.log),
        partial(edge.save_artists, paths.artists),
        partial(edge.stats, paths.stats_history),
    )
    catalog = ReviewCatalog(
        edge.ranked_tracks,
        partial(edge.ranked, "ranked"),
        partial(edge.ranked, "earliest"),
    )
    spotify = ReviewSpotify(
        memory.membership, memory.append, memory.remove, memory.unfollow
    )
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
