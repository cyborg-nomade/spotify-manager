"""Track artist completion, preview learning and accepted release checkpoints."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotify_manager.application.release_check_values import ReleaseCheckStateError
from spotify_manager.application.release_effects import ReleaseEffects
from spotify_manager.application.release_opening import OpenedReleaseRun
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCheckResult


def _mapping(raw: object) -> ReleaseState:
    assert isinstance(raw, dict)
    return cast(ReleaseState, raw)


def _section(state: ReleaseState, name: str) -> ReleaseState:
    return _mapping(state[name])


@dataclass
class ReleaseProgress:
    """Keep original mutable state authority and accepted-effect ordering.

    Args:
        opening: Loaded and copied restart state.
        effects: Original checkpoint and audit boundaries.
        preview: Whether only learned mappings and permanent skips may be saved.
        interval: Original artist and learned-mapping checkpoint interval.
    """

    opening: OpenedReleaseRun
    effects: ReleaseEffects
    preview: bool
    interval: int = 100
    completed: set[str] = field(init=False)
    mappings: ReleaseState = field(init=False)
    skipped: ReleaseState = field(init=False)
    processed: ReleaseState = field(init=False)
    pending: ReleaseState = field(init=False)
    results: list[ReleaseCheckResult] = field(default_factory=list)
    completed_changes: int = 0
    learned_changes: int = 0

    def __post_init__(self) -> None:
        """Validate progress and retrieve all state sections before narrowing them.

        Raises:
            ReleaseCheckStateError: Stored completed artists are not a list.
            KeyError: A required state section is absent.
            AssertionError: A required state section is not a mapping.
        """
        raw = self.opening.active.get("completed_artist_keys", [])
        if not isinstance(raw, list):
            raise ReleaseCheckStateError(
                "The active release-check progress is invalid."
            )
        self.completed = {str(key) for key in raw}
        state = self.opening.state
        mappings, skipped = state["artist_mappings"], state["skipped_artists"]
        processed, pending = state["processed_releases"], state["pending_singles"]
        self.mappings, self.skipped = _mapping(mappings), _mapping(skipped)
        self.processed, self.pending = _mapping(processed), _mapping(pending)

    def notify(self, message: str) -> None:
        """Report the original completed and total artist counts.

        Args:
            message: Original progress message.
        """
        self.effects.progress(len(self.completed), len(self.opening.artists), message)

    def mark_completed(self, artist: RankedArtist) -> None:
        """Update sorted working progress without accepting a checkpoint.

        Args:
            artist: Artist whose current work is complete.
        """
        self.completed.add(artist.key)
        self.opening.active["completed_artist_keys"] = sorted(self.completed)

    def complete(self, artist: RankedArtist) -> None:
        """Mark an artist complete and batch read-only real-run checkpoints.

        Args:
            artist: Artist whose current work is complete.
        """
        self.mark_completed(artist)
        if self.preview:
            return
        self.checkpoint_completed()

    def checkpoint_completed(self) -> None:
        """Batch a real artist completion after its preceding accepted effects."""
        self.completed_changes += 1
        if self.completed_changes >= self.interval:
            self.save()

    def save(self) -> None:
        """Accept working state, then reset the real-run batching counter."""
        self.effects.persist(self.opening.state)
        self.completed_changes = 0

    def flush_learning(self, force: bool = False) -> None:
        """Save only preview learning when its original checkpoint is due.

        Args:
            force: Flush any nonzero learned changes on completion or pause.
        """
        if self.learned_changes == 0:
            return
        if not force and self.learned_changes < self.interval:
            return
        self.effects.persist(self.opening.persisted_state)
        self.learned_changes = 0

    def remember_mapping(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate
    ) -> None:
        """Remember the mapping and batch preview learning separately from run state.

        Args:
            artist: Original ranked artist.
            mapped: Original accepted Spotify mapping.
        """
        self.mappings[artist.key] = asdict(mapped)
        if not self.preview:
            return
        _section(self.opening.persisted_state, "artist_mappings")[artist.key] = asdict(
            mapped
        )
        self.learned_changes += 1
        self.flush_learning()

    def skip_permanently(self, artist: RankedArtist) -> None:
        """Save a permanent skip with the original preview/real audit ordering.

        Args:
            artist: Artist explicitly excluded by the user.
        """
        record = {
            "artist": artist.name,
            "rank": artist.rank,
            "scrobbles": artist.scrobbles,
            "skipped_at": self.opening.generated_at.isoformat(),
        }
        self.skipped[artist.key] = record
        self.mark_completed(artist)
        if self.preview:
            _section(self.opening.persisted_state, "skipped_artists")[artist.key] = (
                record
            )
            self.effects.persist(self.opening.persisted_state)
            self.learned_changes = 0
            return
        self.effects.audit(
            self.opening.run_id, "artist_permanently_skipped", artist=artist.name
        )
        self.save()

    def pause(self, artist: RankedArtist, release: str | None = None) -> None:
        """Flush preview learning or audit a pause before returning its summary.

        Args:
            artist: Artist at which the user quit.
            release: Reviewed release, absent for an artist-mapping pause.
        """
        if self.preview:
            self.flush_learning(force=True)
            return
        details: dict[str, object] = {"artist": artist.name}
        if release is not None:
            details["release"] = release
        self.effects.audit(self.opening.run_id, "run_paused", **details)

    def store_pending(self, pending: PendingSingle) -> None:
        """Retain a pending single in working state, including during previews.

        Args:
            pending: The unconfirmed single and its loaded marker.
        """
        _section(self.opening.state, "pending_singles")[pending.release.spotify_id] = {
            "artist_key": pending.artist_key,
            "release": asdict(pending.release),
            "first_track": asdict(pending.first_track),
        }

    def record(self, result: ReleaseCheckResult, terminal: bool = True) -> None:
        """Append a result, then audit it before changing terminal restart state.

        Args:
            result: Original ordered release decision.
            terminal: Whether this decision closes the release and any pending single.
        """
        self.results.append(result)
        if self.preview:
            return
        self.effects.audit(
            self.opening.run_id, "release_checked", result=asdict(result)
        )
        if not terminal:
            return
        _section(self.opening.state, "processed_releases")[result.release_id] = {
            "checked_at": self.opening.generated_at.isoformat(),
            "artist": result.artist,
            "release": result.release,
            "reason": result.reason,
            "wine_cellar_action": result.wine_cellar_action,
            "new_vintage_action": result.new_vintage_action,
        }
        _section(self.opening.state, "pending_singles").pop(result.release_id, None)

    def finish_release(self) -> None:
        """Clear the current marker and checkpoint accepted real-run release work."""
        self.opening.active["pending_release_id"] = None
        if not self.preview:
            self.save()

    def finish(self) -> None:
        """Accept final success state before its audit, or flush preview learning."""
        if self.preview:
            self.flush_learning(force=True)
            return
        state = self.opening.state
        state["last_successful_check_at"] = self.effects.clock().isoformat()
        state["last_checked_through"] = self.opening.checked_through.isoformat()
        state["active_run"] = None
        self.save()
        self.effects.audit(
            self.opening.run_id,
            "run_completed",
            checked_through=self.opening.checked_through.isoformat(),
            artists=len(self.opening.artists),
            releases=len(self.results),
        )
