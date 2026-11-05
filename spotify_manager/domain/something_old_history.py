"""Stable artist identities and recorded mode usage for Something Old."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from hashlib import sha256
from typing import Literal

from spotify_manager.domain.golden_selection import SelectionMode


MODES: tuple[SelectionMode, ...] = ("lastfm_top_tracks", "spotify_top_tracks", "album")
type ChoiceProvenance = Literal["applied", "audit", "recovered"]


@dataclass(frozen=True)
class ArtistChoice:
    """A completed selection, or an intent kept separately until verified.

    Args:
        artist_id: Accepted Spotify artist identity, independent of display names.
        artist_name: Spotify display name at selection time.
        lastfm_artist: Original history label used to select this artist.
        mode: Explicitly selected listening mode.
        chosen_at: Original aware selection timestamp.
        playlist_id: Destination of the complete selection.
        track_ids: All selected markers in append order.
        release_name: Selected album label, when applicable.
        release_id: Selected album identity, when applicable.
        provenance: Accepted append, imported audit or verified playlist recovery.
    """

    artist_id: str
    artist_name: str
    lastfm_artist: str
    mode: SelectionMode
    chosen_at: datetime
    playlist_id: str
    track_ids: tuple[str, ...]
    release_name: str | None = None
    release_id: str | None = None
    provenance: ChoiceProvenance = "applied"


@dataclass
class ChoiceLedger:
    """Keep completed selections separate from unconfirmed playlist effects.

    Args:
        choices: Completed events keyed by their stable fingerprint.
        pending: Unconfirmed intents keyed by destination playlist.
        version: Persisted format version.
    """

    choices: dict[str, ArtistChoice] = field(default_factory=dict)
    pending: dict[str, ArtistChoice] = field(default_factory=dict)
    version: Literal[1] = 1


@dataclass(frozen=True)
class PreviousMode:
    """Summarize recorded use without selecting the next mode automatically.

    Args:
        mode: Available selection option.
        count: Number of completed recorded selections.
        last_chosen_at: Most recent recorded use, or none without evidence.
        release_name: Album chosen on that most recent use, when applicable.
        provenance: Evidence for the most recent use.
    """

    mode: SelectionMode
    count: int
    last_chosen_at: datetime | None = None
    release_name: str | None = None
    provenance: ChoiceProvenance | None = None


def choice_identity(choice: ArtistChoice) -> str:
    """Deduplicate a completed append and its later audit import or recovery.

    Args:
        choice: Complete selection evidence.

    Returns:
        Stable event fingerprint, independent of labels and provenance.
    """
    parts = (
        choice.artist_id,
        choice.mode,
        choice.chosen_at.astimezone(UTC).isoformat(),
        choice.playlist_id,
        *choice.track_ids,
    )
    return sha256("\x1f".join(parts).encode()).hexdigest()


def previous_modes(ledger: ChoiceLedger, artist_id: str) -> tuple[PreviousMode, ...]:
    """Summarize all three modes for one exact Spotify identity.

    Args:
        ledger: Completed and pending evidence; pending entries are excluded.
        artist_id: Accepted Spotify artist identity.

    Returns:
        Three usage summaries in the original option order.
    """
    result = []
    for mode in MODES:
        result.append(_previous_mode(mode, _matching_choices(ledger, artist_id, mode)))
    return tuple(result)


def _matching_choices(
    ledger: ChoiceLedger, artist_id: str, mode: SelectionMode
) -> list[ArtistChoice]:
    matches = []
    for choice in ledger.choices.values():
        if choice.artist_id == artist_id and choice.mode == mode:
            matches.append(choice)
    return matches


def _previous_mode(mode: SelectionMode, matches: list[ArtistChoice]) -> PreviousMode:
    if not matches:
        return PreviousMode(mode, 0)
    latest = max(matches, key=_choice_date)
    return PreviousMode(
        mode, len(matches), latest.chosen_at, latest.release_name, latest.provenance
    )


def _choice_date(choice: ArtistChoice) -> datetime:
    return choice.chosen_at
