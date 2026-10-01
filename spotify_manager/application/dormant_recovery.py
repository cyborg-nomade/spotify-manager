"""Coordinate alphabetical dormant recovery with original safe effect ordering."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import Protocol

from spotify_manager.application.dormant_values import DormantArtistSummary
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.dormant_artists import DormantArtist
from spotify_manager.domain.dormant_artists import DormantArtistResult
from spotify_manager.domain.history_matching import PlaylistState


class DormantEffects(Protocol):
    """Original history, destination, artist mapping and live liked-track boundaries."""

    def candidates(self, today: date) -> tuple[DormantArtist, ...]:
        """Read original history eligibility.

        Args:
            today: Effective local calendar date.

        Returns:
            Alphabetically ordered candidates.
        """

    def read(self) -> PlaylistState:
        """Read destination membership before selection.

        Returns:
            Original size and represented artists/tracks.
        """

    def mapping(
        self, artist: DormantArtist, rank: int
    ) -> SpotifyArtistCandidate | None:
        """Resolve the original unique exact artist mapping.

        Args:
            artist: Original dormant candidate.
            rank: Position in the full history candidate list.

        Returns:
            Unique mapping or no unambiguous match.
        """

    def track(self, artist_id: str) -> CatalogTrack | None:
        """Read the original most popular live-liked primary-credit track.

        Args:
            artist_id: Mapped artist identity.

        Returns:
            Preferred marker or no live-liked track.
        """

    def append(self, tracks: list[CatalogTrack]) -> None:
        """Accept original ordered markers.

        Args:
            tracks: Original selected tracks.
        """


@dataclass
class _Selection:
    """Retain ordered original outcomes and markers before the single append.

    Args:
        effects: Original catalog and mapping observations.
        playlist: Initial represented destination membership.
        echo: Original skipped-candidate presentation.
        represented: Original mutable represented artist keys.
        results: Original ordered selected and skipped outcomes.
        pending: Original ordered marker proposals.
    """

    effects: DormantEffects
    playlist: PlaylistState
    echo: Callable[[str], None]
    represented: set[str]
    results: list[DormantArtistResult] = field(default_factory=list)
    pending: list[CatalogTrack] = field(default_factory=list)

    def select(self, candidate: DormantArtist, rank: int) -> None:
        """Observe mapping before live liked status and record original outcomes.

        Args:
            candidate: Original alphabetical candidate.
            rank: Position in the full eligible history list.
        """
        mapped = self.effects.mapping(candidate, rank)
        if mapped is None:
            self.echo(f"Skipped {candidate.name}: no unambiguous Spotify mapping.")
            self.results.append(
                DormantArtistResult(
                    candidate.name, candidate.scrobbles, None, None, None, "no mapping"
                )
            )
            return
        track = self.effects.track(mapped.spotify_id)
        if track is None:
            self.echo(f"Skipped {candidate.name}: no liked primary-artist track.")
            self.results.append(
                DormantArtistResult(
                    candidate.name,
                    candidate.scrobbles,
                    mapped.name,
                    None,
                    None,
                    "no liked track",
                )
            )
            return
        self._remember(candidate, mapped, track)

    def _remember(
        self,
        candidate: DormantArtist,
        mapped: SpotifyArtistCandidate,
        track: CatalogTrack,
    ) -> None:
        if track.spotify_id in self.playlist.track_ids or any(
            selected.spotify_id == track.spotify_id for selected in self.pending
        ):
            self.represented.add(candidate.key)
            return
        self.pending.append(track)
        self.represented.add(candidate.key)
        self.results.append(
            DormantArtistResult(
                candidate.name,
                candidate.scrobbles,
                mapped.name,
                track.name,
                track.popularity,
                "added",
            )
        )


@dataclass(frozen=True)
class DormantRecovery:
    """Preserve original cancellation, progress, mapping and ordered batch append.

    Args:
        effects: Original observations and writes.
        clock: Resolve original local date after validation.
        cancel: Original per-candidate safe boundary.
        progress: Original candidate and completion presentation.
        echo: Original skip presentation.
        lookback: Original prior-year intersection width.
    """

    effects: DormantEffects
    clock: Callable[[], date]
    cancel: Callable[[], None]
    progress: Callable[[int, int, str], None]
    echo: Callable[[str], None]
    lookback: int = 4

    def run(self, count: int, dry_run: bool) -> DormantArtistSummary:
        """Recover original alphabetical candidates until enough distinct tracks.

        Args:
            count: Positive requested marker count.
            dry_run: Suppress remote append, retaining original added result labels.

        Returns:
            Original summary after accepted append and completion progress.

        Raises:
            ValueError: Count is below the original minimum.
            BlastFromPastArtistsError: Original catalog or membership is unusable.
            BlastFromPastCancelledError: Original safe cancellation is requested.
        """
        if count < 1:
            raise ValueError("count must be at least 1")
        today = self.clock()
        candidates = self.effects.candidates(today)
        playlist = self.effects.read()
        represented = set(playlist.primary_artist_keys)
        represented_count = sum(
            candidate.key in represented for candidate in candidates
        )
        selection = _Selection(self.effects, playlist, self.echo, represented)
        self._select(candidates, count, selection)
        if selection.pending and not dry_run:
            self.effects.append(selection.pending)
        self.progress(len(selection.pending), count, "Dormant-artist recovery complete")
        return DormantArtistSummary(
            today.year,
            tuple(range(today.year - self.lookback, today.year)),
            len(candidates),
            represented_count,
            playlist.total_items,
            playlist.total_items + (0 if dry_run else len(selection.pending)),
            count,
            tuple(selection.results),
        )

    def _select(
        self, candidates: tuple[DormantArtist, ...], count: int, selection: _Selection
    ) -> None:
        for rank, candidate in enumerate(candidates, start=1):
            if len(selection.pending) >= count:
                return
            self.cancel()
            if candidate.key in selection.represented:
                continue
            self.progress(
                len(selection.pending),
                count,
                f"Checking dormant artist {candidate.name}",
            )
            selection.select(candidate, rank)
