"""Deterministic release observations and accepted effects for workflow contracts."""

from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from typing import cast

from spotify_manager.application.release_opening import OpenedReleaseRun
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.release_check import membership
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import PlaylistAction
from spotify_manager.domain.release_check_values import PlaylistEntry
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import PlaylistSnapshot
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


STAMP = datetime(2026, 9, 25, tzinfo=UTC)
ARTIST = SpotifyArtistCandidate(
    "spotify-artist", "Artist", "spotify:artist:spotify-artist", None, None, 1, True
)
TRACK = ReleaseTrack(
    "track", "spotify:track:track", "Song", ARTIST.spotify_id, ARTIST.name, 1, 1
)
PROFILES = (
    "album",
    "preview",
    "completed",
    "permanent",
    "skip_artist",
    "skip_artist_preview",
    "skip",
    "missing",
    "quit_artist",
    "quit_artist_preview",
    "mapped",
    "composer",
    "wine_outside",
    "wine_inside",
    "duplicates",
    "processed",
    "pending_processed",
    "pending",
    "pending_preview",
    "single_top",
    "single_future",
    "single_current",
    "skip_release",
    "quit_release",
    "quit_release_preview",
    "invalid_pending",
    "invalid_choice",
    "empty_track",
    "excluded",
    "catalog_empty",
)


class EffectFailureError(RuntimeError):
    """Stop at a selected observation or accepted effect."""


def release(
    identifier: str = "release",
    kind: str = "Album",
    title: str = "Release",
    stamp: str = "2026-09-01",
    count: int = 10,
) -> ReleaseCandidate:
    """Build a primary-artist release.

    Args:
        identifier: Release identity.
        kind: Observed release type.
        title: Display title.
        stamp: Original release date.
        count: Track count.

    Returns:
        The observed release.
    """
    return ReleaseCandidate(
        identifier,
        "spotify:album:" + identifier,
        title,
        kind,
        stamp,
        "day",
        count,
        ARTIST.spotify_id,
        ARTIST.name,
    )


def _state(artist: RankedArtist, profile: str) -> ReleaseState:
    state: ReleaseState = {
        "artist_mappings": {},
        "skipped_artists": {},
        "processed_releases": {},
        "pending_singles": {},
        "operator_field": {"retain": "unknown"},
    }
    active: ReleaseState = {
        "run_id": "run",
        "started_at": STAMP.isoformat(),
        "checked_from": "2026-01-01",
        "checked_through": "2026-09-25",
        "artists": [asdict(artist)],
        "completed_artist_keys": [],
        "pending_release_id": None,
    }
    state["active_run"] = active
    if profile == "completed":
        active["completed_artist_keys"] = [artist.key]
    if profile == "permanent":
        cast(ReleaseState, state["skipped_artists"])[artist.key] = {"artist": "Artist"}
    if profile == "mapped":
        cast(ReleaseState, state["artist_mappings"])[artist.key] = asdict(ARTIST)
    if profile in {"processed", "pending_processed"}:
        cast(ReleaseState, state["processed_releases"])["release"] = {
            "original": "kept"
        }
    if profile == "pending_processed":
        cast(ReleaseState, state["pending_singles"])["release"] = asdict(
            PendingSingle(artist.key, release(kind="Single", count=1), TRACK)
        )
    return state


def opening(profile: str) -> OpenedReleaseRun:
    """Build an authoritative resumed context without history or service dependencies.

    Args:
        profile: Original workflow scenario.

    Returns:
        Loaded and copied restart state with a frozen ranked artist.
    """
    rank = (
        21
        if profile.startswith("pending")
        or profile in {"single_future", "single_current"}
        else 1
    )
    rank = 51 if profile == "wine_outside" else rank
    artist = RankedArtist("artist", "Artist", 100, rank)
    persisted = _state(artist, profile)
    state = deepcopy(persisted)
    return OpenedReleaseRun(
        STAMP,
        STAMP.date(),
        persisted,
        state,
        cast(ReleaseState, state["active_run"]),
        (artist,),
        date(2026, 1, 1),
        STAMP.date(),
        "run",
        True,
        None,
    )


def _catalog(profile: str) -> tuple[ReleaseCandidate, ...]:
    if profile == "empty_single":
        return (release(kind="Single", count=1),)
    if profile == "catalog_empty":
        return ()
    if profile == "duplicates":
        return release("b", count=4), release("a", count=6), release("c", count=6)
    if profile == "excluded":
        return (release(title="Greatest Hits"),)
    if profile.startswith("single_") or profile in {
        "pending",
        "pending_preview",
        "pending_processed",
    }:
        return (release(kind="Single", count=1), release("future", stamp="2027-01-01"))
    return (release(),)


@dataclass
class Effects:
    """Record reads, choices, accepted writes and saved state without SDK imports.

    Args:
        profile: Original scenario controls.
        failure: Event at which to stop, after recording its acceptance.
        persisted: Last accepted state, initialized by the caller.
    """

    profile: str
    failure: str | None = None
    persisted: ReleaseState = field(default_factory=dict)
    events: list[object] = field(default_factory=list)
    saves: list[ReleaseState] = field(default_factory=list)

    def _event(self, name: str, *details: object) -> None:
        self.events.append([name, *details])
        if name == self.failure:
            raise EffectFailureError(name)

    def clock(self) -> datetime:
        """Observe the final successful-check clock.

        Returns:
            Fixed timestamp.
        """
        self._event("clock")
        return STAMP

    def progress(self, done: int, total: int, message: str) -> None:
        """Record original user-visible progress.

        Args:
            done: Completed artists.
            total: Ranked artists.
            message: Stage text.
        """
        self._event("progress", done, total, message)

    def persist(self, state: ReleaseState) -> None:
        """Accept a complete checkpoint before a possible later failure.

        Args:
            state: Mutable working or preview-learning state.
        """
        state["updated_at"] = STAMP.isoformat()
        self.persisted = deepcopy(state)
        self.saves.append(deepcopy(state))
        self._event("persist")

    def audit(self, run_id: str, event: str, **details: object) -> None:
        """Accept original audit fields before a possible later failure.

        Args:
            run_id: Durable identity.
            event: Event name.
            details: Ordered event fields.
        """
        self._event("audit:" + event, run_id, details)

    def wine(self) -> PlaylistSnapshot:
        """Observe Wine Cellar before its cleanup.

        Returns:
            Original ordered snapshot.
        """
        self._event("wine")
        entries: tuple[PlaylistEntry, ...] = ()
        if self.profile in {"wine_inside", "wine_outside", "destinations_full"}:
            entries = (
                PlaylistEntry(
                    "spotify:track:original",
                    "original",
                    "Original",
                    ARTIST.spotify_id,
                    ARTIST.name,
                ),
            )
        return PlaylistSnapshot(entries, membership(entries))

    def cleanup(
        self, snapshot: PlaylistSnapshot, preview: bool
    ) -> tuple[int, PlaylistMembership]:
        """Observe original Wine Cellar cleanup.

        Args:
            snapshot: Loaded snapshot.
            preview: Preview mode.

        Returns:
            Original cleanup count and membership.
        """
        self._event("cleanup", preview)
        return (1 if self.profile == "duplicate_wine" else 0), snapshot.membership

    def vintage(self) -> PlaylistMembership:
        """Observe New Vintage after Wine Cellar cleanup.

        Returns:
            Original destination membership.
        """
        self._event("vintage")
        if self.profile == "destinations_full":
            entries = (
                PlaylistEntry(
                    TRACK.uri,
                    TRACK.spotify_id,
                    TRACK.name,
                    TRACK.primary_artist_id,
                    TRACK.primary_artist_name,
                ),
            )
            return membership(entries)
        return membership(())

    def composers(self) -> tuple[OwnedPlaylist, ...]:
        """Observe owned composer playlists.

        Returns:
            A matching playlist only in the composer scenario.
        """
        self._event("composers")
        return (
            (OwnedPlaylist("composer", "[CD] Artist", 0),)
            if self.profile == "composer"
            else ()
        )

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Observe persisted mapping decoding.

        Args:
            raw: Stored mapping or missing value.

        Returns:
            The scenario's previously stored mapping, when present.
        """
        return ARTIST if isinstance(raw, dict) else None

    def resolve(self, artist: RankedArtist) -> SpotifyArtistCandidate | str | None:
        """Observe artist interaction before catalog reads.

        Args:
            artist: Frozen ranked artist.

        Returns:
            Scenario's mapping, control choice or no match.
        """
        self._event("resolve", artist.key)
        if self.profile.startswith("skip_artist"):
            return "skip-artist"
        if self.profile.startswith("quit_artist"):
            return "quit"
        if self.profile == "skip":
            return "skip"
        if self.profile == "missing":
            return None
        return ARTIST

    def catalog(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate, start: date
    ) -> tuple[ReleaseCandidate, ...]:
        """Observe the catalog after artist exclusions.

        Args:
            artist: Frozen ranked artist.
            mapped: Resolved Spotify artist.
            start: Original inclusive window start.

        Returns:
            Scenario's ordered releases.
        """
        self._event("catalog", artist.key, mapped.spotify_id, start.isoformat())
        return _catalog(self.profile)

    def decode_pending(self, raw: object) -> PendingSingle | None:
        """Decode the explicit retained-single scenario.

        Args:
            raw: Stored single or missing value.

        Returns:
            A valid retained marker only for this fixture's stored record.
        """
        if not isinstance(raw, dict):
            return None
        return PendingSingle(
            "other" if self.profile == "other_pending" else "artist",
            release(kind="Single", count=1),
            TRACK,
        )

    def first_track(self, candidate: ReleaseCandidate) -> ReleaseTrack | None:
        """Observe a playable first track before eligibility review.

        Args:
            candidate: Reviewed release.

        Returns:
            Original marker, or no playable track.
        """
        self._event("first", candidate.spotify_id)
        return None if self.profile in {"empty_track", "empty_single"} else TRACK

    def match(
        self,
        track: ReleaseTrack,
        records: tuple[ReleaseCandidate, ...],
        cache: dict[str, tuple[ReleaseTrack, ...]],
    ) -> ReleaseCandidate | None:
        """Observe future/current matching with its run-scoped cache.

        Args:
            track: Single marker.
            records: Ordered containing-record candidates.
            cache: Shared per-artist track cache.

        Returns:
            The scenario's matching record, if present.
        """
        self._event(
            "match", track.spotify_id, [record.spotify_id for record in records]
        )
        if self.profile == "single_future" and records:
            return records[0]
        if self.profile == "single_current" and not records:
            return release("released")
        return None

    def choice(
        self,
        artist: RankedArtist,
        candidate: ReleaseCandidate,
        track: ReleaseTrack,
        destinations: tuple[str, ...],
        unattached: bool,
    ) -> str:
        """Record the release review before any playlist mutation.

        Args:
            artist: Ranked artist.
            candidate: Reviewed release.
            track: First playable marker.
            destinations: Missing destinations in Wine/Vintage order.
            unattached: Whether the single has no containing record.

        Returns:
            Scenario's explicit review choice.
        """
        self._event(
            "choice",
            artist.key,
            candidate.spotify_id,
            track.spotify_id,
            list(destinations),
            unattached,
        )
        if self.profile.startswith("quit_release"):
            return "quit"
        if self.profile == "skip_release":
            return "skip"
        if self.profile == "invalid_pending":
            return "pending"
        if self.profile == "invalid_choice":
            return "invalid"
        return "pending" if unattached and self.profile != "single_current" else "add"

    def add(
        self,
        destination: str,
        destination_membership: PlaylistMembership,
        track: ReleaseTrack,
        preview: bool,
    ) -> PlaylistAction:
        """Accept the fixture's playlist write and update membership.

        Args:
            destination: Wine or Vintage identifier.
            destination_membership: Original mutable observed membership.
            track: Selected marker.
            preview: Preview mode.

        Returns:
            Original planned or accepted action.
        """
        destination_membership.primary_artist_ids.add(track.primary_artist_id)
        destination_membership.track_ids.add(track.spotify_id)
        self._event("add:" + destination, track.spotify_id, preview)
        return "would add" if preview else "added"
