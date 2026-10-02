"""Recommendation match preference and ordered artist, membership and count rules."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import Literal

from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate


FoundArtAction = Literal[
    "added",
    "would add",
    "already present",
    "artist already selected",
    "duplicate",
    "liked",
    "no Spotify match",
]


@dataclass(frozen=True)
class FoundArtResult:
    """Ordered Spotify resolution outcome for one recommendation candidate.

    Args:
        candidate: Original ranked neighborhood candidate.
        match: Preferred live Spotify observation, if any.
        action: Original selection, exclusion or preview outcome.
    """

    candidate: FoundArtCandidate
    match: SpotifyTrackMatch | None
    action: FoundArtAction


def _rank(match: SpotifyTrackMatch) -> tuple[float, int, int]:
    return (
        match.track_similarity,
        match.popularity if match.popularity is not None else -1,
        -match.search_rank,
    )


def preferred_recommendation_match(
    matches: tuple[SpotifyTrackMatch, ...],
    liked_ids: set[str],
    *,
    liked: bool,
) -> SpotifyTrackMatch | None:
    """Choose by title similarity, popularity and search order within live liked status.

    Args:
        matches: Original artist/title-qualified search observations.
        liked_ids: Live liked identities, replacing stored status.
        liked: Select liked matches when true, otherwise select unliked matches.

    Returns:
        Highest-ranked matching observation, ignoring album similarity, or none.
    """
    eligible = []
    for match in matches:
        if (match.spotify_id in liked_ids) == liked:
            eligible.append(replace(match, liked=liked))
    if not eligible:
        return None
    return max(eligible, key=_rank)


@dataclass
class RecommendationSelection:
    """Preserve original ordered membership, artist diversity and capacity decisions.

    Args:
        playlist: Observed destination membership.
        count: Original requested addition count.
        dry_run: Present selected additions as previews when true.
        results: Ordered accepted candidate outcomes.
        pending: Ordered unique matches selected for append.
        pending_ids: Previously selected identities.
        selected_artists: Artists with an accepted pending addition.
    """

    playlist: PlaylistState
    count: int
    dry_run: bool
    results: list[FoundArtResult] = field(default_factory=list)
    pending: list[SpotifyTrackMatch] = field(default_factory=list)
    pending_ids: set[str] = field(default_factory=set)
    selected_artists: set[str] = field(default_factory=set)

    def skips_search(self, candidate: FoundArtCandidate) -> bool:
        """Check exclusions known before the current batch is projected.

        Args:
            candidate: Original ranked candidate.

        Returns:
            Whether its key is present or its artist has already been selected.
        """
        return (
            candidate.key in self.playlist.track_keys
            or candidate.key[0] in self.selected_artists
        )

    def observe(
        self,
        candidate: FoundArtCandidate,
        matches: tuple[SpotifyTrackMatch, ...],
        liked_ids: set[str],
    ) -> bool:
        """Project a candidate, retaining skipped outcomes after requested capacity.

        Args:
            candidate: Original candidate in batch order.
            matches: Its already-observed ordered search results.
            liked_ids: Live status shared by the complete current batch.

        Returns:
            False only when the next eligible addition exceeds requested capacity.
        """
        result = self._result(candidate, matches, liked_ids)
        if result is None:
            return False
        self.results.append(result)
        return True

    def _result(
        self,
        candidate: FoundArtCandidate,
        matches: tuple[SpotifyTrackMatch, ...],
        liked_ids: set[str],
    ) -> FoundArtResult | None:
        if candidate.key[0] in self.selected_artists:
            return FoundArtResult(candidate, None, "artist already selected")
        if candidate.key in self.playlist.track_keys:
            return FoundArtResult(candidate, None, "already present")
        liked = preferred_recommendation_match(matches, liked_ids, liked=True)
        if liked is not None:
            return FoundArtResult(candidate, liked, "liked")
        match = preferred_recommendation_match(matches, liked_ids, liked=False)
        return self._unliked(candidate, match)

    def _unliked(
        self,
        candidate: FoundArtCandidate,
        match: SpotifyTrackMatch | None,
    ) -> FoundArtResult | None:
        if match is None:
            return FoundArtResult(candidate, None, "no Spotify match")
        if match.spotify_id in self.playlist.track_ids:
            return FoundArtResult(candidate, match, "already present")
        if match.spotify_id in self.pending_ids:
            return FoundArtResult(candidate, match, "duplicate")
        if len(self.pending) >= self.count:
            return None
        self.pending.append(match)
        self.pending_ids.add(match.spotify_id)
        self.selected_artists.add(candidate.key[0])
        action: FoundArtAction = "would add" if self.dry_run else "added"
        return FoundArtResult(candidate, match, action)
