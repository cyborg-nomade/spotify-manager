"""Independent dormant recovery and top-first live liked-marker observations."""

from dataclasses import dataclass
from dataclasses import field
from datetime import date

import pytest

from spotify_manager.application.dormant_recovery import DormantRecovery
from spotify_manager.application.dormant_tracks import DormantLikedTrack
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.dormant_artists import DormantArtist
from spotify_manager.domain.history_matching import PlaylistState


ARTIST = DormantArtist("artist", "Artist", 4)
TRACK = CatalogTrack(
    "track", "spotify:track:track", "Song", 1, 1, "artist", "Artist", 50
)
MAPPING = SpotifyArtistCandidate("artist", "Artist", "uri", 1, 1, 1, True)


def _clock() -> date:
    return date(2026, 9, 25)


@dataclass
class Effects:
    """Record independent observations and failure after an accepted append.

    Args:
        failure: Boundary to fail after recording it.
        artists: Ordered history candidates.
        playlist: Original represented membership.
        mapped: Per-artist unique mapping outcomes.
        tracks: Per-mapping liked marker outcomes.
    """

    failure: str | None = None
    artists: tuple[DormantArtist, ...] = (ARTIST,)
    playlist: PlaylistState = PlaylistState(0, frozenset())
    mapped: dict[str, SpotifyArtistCandidate | None] = field(default_factory=dict)
    tracks: dict[str, CatalogTrack | None] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)

    def _record(self, event: str) -> None:
        self.events.append(event)
        if event == self.failure:
            raise RuntimeError(event)

    def candidates(self, today: date) -> tuple[DormantArtist, ...]:
        """Observe original history candidates.

        Args:
            today: Effective local date.

        Returns:
            Original ordered artists.
        """
        self._record("candidates")
        assert today == _clock()
        return self.artists

    def read(self) -> PlaylistState:
        """Observe original represented membership.

        Returns:
            Original destination facts.
        """
        self._record("read")
        return self.playlist

    def mapping(
        self, artist: DormantArtist, rank: int
    ) -> SpotifyArtistCandidate | None:
        """Return configured original mapping evidence.

        Args:
            artist: Original history candidate.
            rank: Full history position.

        Returns:
            Unique mapping or no mapping.
        """
        self._record(f"mapping:{rank}")
        return self.mapped.get(artist.key, MAPPING)

    def track(self, artist_id: str) -> CatalogTrack | None:
        """Return configured original live-liked marker.

        Args:
            artist_id: Original mapped identity.

        Returns:
            Preferred marker or no liked track.
        """
        self._record("track")
        return self.tracks.get(artist_id, TRACK)

    def append(self, tracks: list[CatalogTrack]) -> None:
        """Record acceptance before an injected ambiguous failure.

        Args:
            tracks: Original ordered proposals.
        """
        self.accepted.extend(track.uri for track in tracks)
        self._record("append")

    def cancel(self) -> None:
        """Record original per-candidate cancellation."""
        self._record("cancel")

    def progress(self, done: int, total: int, text: str) -> None:
        """Record original progress before mapping and after append.

        Args:
            done: Proposed additions.
            total: Original requested count.
            text: Original stage message.
        """
        self._record(f"progress:{done}:{text}")

    def echo(self, message: str) -> None:
        """Record original skipped-candidate output.

        Args:
            message: Original skip message.
        """
        self._record(message)


def _workflow(effects: Effects) -> DormantRecovery:
    return DormantRecovery(
        effects, _clock, effects.cancel, effects.progress, effects.echo
    )


EVENTS = [
    "candidates",
    "read",
    "cancel",
    "progress:0:Checking dormant artist Artist",
    "mapping:1",
    "track",
    "append",
    "progress:1:Dormant-artist recovery complete",
]


@pytest.mark.parametrize("failure", EVENTS)
def test_dormant_accepted_failure_prefix(failure: str) -> None:
    """Retain original accepted writes and exact failure prefixes.

    Args:
        failure: Original observed boundary.
    """
    effects = Effects(failure=failure)
    with pytest.raises(RuntimeError, match=failure):
        _workflow(effects).run(1, False)
    assert effects.events == EVENTS[: EVENTS.index(failure) + 1]
    assert effects.accepted == (
        [TRACK.uri] if EVENTS.index(failure) >= EVENTS.index("append") else []
    )


@pytest.mark.parametrize("preview", [False, True])
def test_dormant_completion_and_selection_limit(preview: bool) -> None:
    """Preserve original added preview labels and stop before another cancellation.

    Args:
        preview: Original preview mode.
    """
    effects = Effects(artists=(ARTIST, DormantArtist("second", "Second", 4)))
    summary = _workflow(effects).run(1, preview)
    assert summary.added == 1
    assert summary.playlist_length_after == int(not preview)
    assert summary.history_years == (2022, 2023, 2024, 2025)
    assert effects.events == (EVENTS[:6] + EVENTS[7:] if preview else EVENTS)


def test_dormant_unmapped_and_unliked_results() -> None:
    """Retain original skip output before recording each skipped candidate."""
    first = DormantArtist("first", "First", 4)
    second = DormantArtist("second", "Second", 4)
    effects = Effects(
        artists=(first, second), mapped={"first": None}, tracks={"artist": None}
    )
    summary = _workflow(effects).run(1, False)
    assert [result.action for result in summary.results] == [
        "no mapping",
        "no liked track",
    ]
    assert summary.added == 0 and summary.playlist_length_after == 0
    assert "Skipped First: no unambiguous Spotify mapping." in effects.events
    assert "Skipped Second: no liked primary-artist track." in effects.events


@pytest.mark.parametrize("represented,duplicate", [(True, False), (False, True)])
def test_dormant_represented_artist_and_duplicate_track(
    represented: bool, duplicate: bool
) -> None:
    """Suppress represented artists before mapping and resolved duplicate markers.

    Args:
        represented: Original represented artist membership.
        duplicate: Original represented track membership.
    """
    playlist = PlaylistState(
        1,
        frozenset({"track"}) if duplicate else frozenset(),
        primary_artist_keys=frozenset({"artist"}) if represented else frozenset(),
    )
    effects = Effects(playlist=playlist)
    summary = _workflow(effects).run(1, False)
    assert summary.results == () and summary.added == 0
    assert summary.represented_count == int(represented)
    assert ("mapping:1" in effects.events) is not represented


def test_dormant_pending_duplicates_are_suppressed() -> None:
    """Suppress a second artist mapped to the same pending marker without a result."""
    effects = Effects(artists=(ARTIST, DormantArtist("second", "Second", 4)))
    summary = _workflow(effects).run(2, False)
    assert summary.added == 1
    assert effects.accepted == [TRACK.uri]


def test_dormant_validation_precedes_observations() -> None:
    """Reject original invalid count before clock and external reads."""
    effects = Effects()
    with pytest.raises(ValueError, match="at least 1"):
        _workflow(effects).run(0, False)
    assert effects.events == []


@dataclass
class LikedObservations:
    """Record top-first and conditional catalog/popularity reads.

    Args:
        top_tracks: Original top observations.
        catalog_tracks: Original catalog observations.
        populated: Original refreshed popularity observations.
        liked_ids: Original live-liked identities.
    """

    top_tracks: tuple[CatalogTrack, ...] = (TRACK,)
    catalog_tracks: tuple[CatalogTrack, ...] = (TRACK,)
    populated: tuple[CatalogTrack, ...] = (TRACK,)
    liked_ids: set[str] = field(default_factory=set)
    events: list[str] = field(default_factory=list)

    def top(self) -> tuple[CatalogTrack, ...]:
        """Read original top observations.

        Returns:
            Original top tracks.
        """
        self.events.append("top")
        return self.top_tracks

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Observe original live liked membership.

        Args:
            tracks: Original observed tracks.

        Returns:
            Original statuses by identity.
        """
        self.events.append("liked")
        return {
            track.spotify_id: track.spotify_id in self.liked_ids for track in tracks
        }

    def catalog(self) -> tuple[CatalogTrack, ...]:
        """Read original fallback catalog observations.

        Returns:
            Original catalog tracks.
        """
        self.events.append("catalog")
        return self.catalog_tracks

    def populate(self, tracks: tuple[CatalogTrack, ...]) -> tuple[CatalogTrack, ...]:
        """Read original popularity only for observed liked tracks.

        Args:
            tracks: Original filtered live-liked set.

        Returns:
            Original populated details.
        """
        assert tracks == (TRACK,)
        self.events.append("populate")
        return self.populated


def _liked_workflow(observations: LikedObservations) -> DormantLikedTrack:
    return DormantLikedTrack(
        observations.top,
        observations.liked,
        observations.catalog,
        observations.populate,
    )


def test_dormant_liked_top_prevents_catalog_fallback() -> None:
    """Keep top-track success before any catalog/popularity observation."""
    observations = LikedObservations(liked_ids={"track"})
    assert _liked_workflow(observations).run() == TRACK
    assert observations.events == ["top", "liked"]


@pytest.mark.parametrize("populated", [(), (TRACK,)])
def test_dormant_liked_catalog_popularity(populated: tuple[CatalogTrack, ...]) -> None:
    """Observe original popularity after liked filtering, including empty details.

    Args:
        populated: Original returned popularity details.
    """
    observations = LikedObservations(
        top_tracks=(), liked_ids={"track"}, populated=populated
    )
    assert _liked_workflow(observations).run() == (TRACK if populated else None)
    assert observations.events == ["top", "liked", "catalog", "liked", "populate"]


def test_dormant_no_liked_catalog_prevents_popularity_read() -> None:
    """Skip popularity when live liked statuses exclude every catalog track."""
    observations = LikedObservations()
    assert _liked_workflow(observations).run() is None
    assert observations.events == ["top", "liked", "catalog", "liked"]
