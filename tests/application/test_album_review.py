"""Run album assessment entirely against typed in-memory dependencies."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.album_review import review_album
from spotify_manager.application.music import Album
from spotify_manager.application.music import Track


@dataclass
class MemoryAlbums:
    """Supply ordered album observations and record use-case boundaries.

    Args:
        tracks: Catalog observations to return.
        liked: Membership observations keyed by identifier.
        failure: Optional boundary at which to raise.
        events: Ordered calls made by the use case.
    """

    tracks: tuple[Track, ...]
    liked: dict[str, bool]
    failure: str | None = None
    events: list[object] = field(default_factory=list)

    def resolve_album(
        self, *, name: str | None, album_id: str | None, artist: str | None
    ) -> Album:
        """Record resolution inputs and return the supplied album identity.

        Args:
            name: Supplied display name.
            album_id: Preferred identifier.
            artist: Supplied primary artist.

        Returns:
            The scripted resolved identity.

        Raises:
            RuntimeError: Resolution is the scripted failing boundary.
        """
        self.events.append(("resolve", name, album_id, artist))
        self._fail("resolve")
        return Album(album_id or "album", name or "Album", artist)

    def album_tracks(self, album_id: str) -> tuple[Track, ...]:
        """Return the current ordered tracks after recording the read.

        Args:
            album_id: Resolved album identifier.

        Returns:
            The supplied catalog observations.

        Raises:
            RuntimeError: Track retrieval is the scripted failing boundary.
        """
        self.events.append(("tracks", album_id))
        self._fail("tracks")
        return self.tracks

    def liked_tracks(self, track_ids: tuple[str, ...]) -> dict[str, bool]:
        """Record exact query identifiers, without deduplicating them.

        Args:
            track_ids: Ordered membership query.

        Returns:
            A detached copy of the scripted statuses.

        Raises:
            RuntimeError: Membership is the scripted failing boundary.
        """
        self.events.append(("liked", track_ids))
        self._fail("liked")
        return dict(self.liked)

    def _fail(self, stage: str) -> None:
        if self.failure == stage:
            raise RuntimeError(stage)


@pytest.mark.parametrize(
    ("total", "liked", "decision", "required"),
    [
        (0, 0, "remove", 1),
        (1, 0, "remove", 1),
        (1, 1, "keep", 1),
        (3, 1, "keep", 1),
        (4, 1, "remove", 2),
        (4, 2, "keep", 2),
    ],
)
def test_assessment_with_memory_ports(
    total: int, liked: int, decision: str, required: int
) -> None:
    """Keep retention decisions and read order stable using only in-memory ports.

    Args:
        total: Observed album size.
        liked: Number of liked tracks.
        decision: Expected keep/remove decision.
        required: Expected minimum liked count.
    """
    tracks = tuple(Track(str(i), str(i), f"spotify:track:{i}") for i in range(total))
    statuses = {str(i): i < liked for i in range(total)}
    memory = MemoryAlbums(tracks, statuses)
    result = review_album(memory, memory, album_id="a", name="Album", artist="Artist")
    assert result.album == Album("a", "Album", "Artist")
    assert result.tracks is tracks
    assert sum(result.liked) == liked
    assert result.assessment.decision == decision
    assert result.assessment.required_liked_tracks == required
    assert memory.events == [
        ("resolve", "Album", "a", "Artist"),
        ("tracks", "a"),
        ("liked", tuple(str(i) for i in range(total))),
    ]


def test_duplicate_and_missing_identifiers_keep_positions() -> None:
    """Preserve duplicate track positions and missing-identifier membership."""
    tracks = (
        Track("x", "First", "x"),
        Track(None, "Missing", "m"),
        Track("x", "Last", "x"),
    )
    memory = MemoryAlbums(tracks, {"x": True})
    result = review_album(memory, memory, album_id="a")
    assert result.liked == (True, False, True)
    assert memory.events[-1] == ("liked", ("x", "x"))


@pytest.mark.parametrize(
    ("failure", "calls"), [("resolve", 1), ("tracks", 2), ("liked", 3)]
)
def test_failures_stop_subsequent_reads(failure: str, calls: int) -> None:
    """Stop reading after the first integration failure without hiding its error.

    Args:
        failure: Scripted failing integration boundary.
        calls: Expected number of reads.
    """
    memory = MemoryAlbums((), {}, failure)
    with pytest.raises(RuntimeError, match=failure):
        review_album(memory, memory, name="Album")
    assert len(memory.events) == calls


@pytest.mark.parametrize(
    ("threshold", "required"), [(-1.0, 0), (0.0, 0), (0.3, 1), (0.75, 1), (2.0, 2)]
)
def test_threshold_is_passed_to_policy_unchanged(
    threshold: float, required: int
) -> None:
    """Retain the original behavior for nonpositive and out-of-range thresholds.

    Args:
        threshold: Original threshold passed by the caller.
        required: Expected minimum liked count.
    """
    memory = MemoryAlbums((Track("x", "Track", "x"),), {"x": True})
    result = review_album(memory, memory, name="Album", threshold=threshold)
    assert result.threshold == threshold
    assert result.assessment.required_liked_tracks == required


def test_boundary_membership_keys_preserve_falsey_identifier_lookup() -> None:
    """Preserve a parsed legacy lookup key without querying its missing identifier."""
    track = Track(None, "Malformed identifier", "x", membership_key="0")
    memory = MemoryAlbums((track,), {"0": True})
    result = review_album(memory, memory, name="Album")
    assert result.liked == (True,)
    assert memory.events[-1] == ("liked", ())
