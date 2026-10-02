"""Library affinity keeps batch boundaries, precedence and early stopping."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.library_affinity import library_affinity


@dataclass
class Membership:
    """Serve membership while retaining every requested batch.

    Args:
        saved: IDs observed as saved albums.
        liked: IDs observed as liked tracks.
        calls: Requests in their observed order.
    """

    saved: set[str] = field(default_factory=set)
    liked: set[str] = field(default_factory=set)
    calls: list[tuple[str, list[str]]] = field(default_factory=list)

    def albums(self, ids: list[str]) -> tuple[bool, ...]:
        """Read saved-album membership.

        Args:
            ids: Requested candidate batch.

        Returns:
            Statuses in request order.
        """
        self.calls.append(("albums", ids))
        return tuple(spotify_id in self.saved for spotify_id in ids)

    def tracks(self, ids: list[str]) -> tuple[bool, ...]:
        """Read liked-track membership.

        Args:
            ids: Requested candidate batch.

        Returns:
            Statuses in request order.
        """
        self.calls.append(("tracks", ids))
        return tuple(spotify_id in self.liked for spotify_id in ids)


@pytest.mark.parametrize("album_count", [3, 4, 10, 11])
def test_album_threshold_skips_all_track_requests(album_count: int) -> None:
    """Count the entire accepted batch and skip remaining IDs once albums suffice.

    Args:
        album_count: Number of saved candidate albums.
    """
    ids = tuple(str(index) for index in range(album_count))
    membership = Membership(saved=set(ids))
    result = library_affinity(membership, ids, ("track",))
    assert result == (None, min(album_count, 10), True)
    assert membership.calls == [("albums", list(ids[:10]))]


@pytest.mark.parametrize("liked_count", [0, 17, 18, 20, 21])
def test_track_threshold_runs_after_unsatisfied_album_reads(liked_count: int) -> None:
    """Retain whole-batch counts and the exact 18-like qualification boundary.

    Args:
        liked_count: Number of liked candidate tracks.
    """
    tracks = tuple(str(index) for index in range(liked_count))
    membership = Membership(saved={"album"}, liked=set(tracks))
    result = library_affinity(membership, ("album",), tracks)
    assert result == (min(liked_count, 20), 1, liked_count >= 18)
    expected = [("albums", ["album"])]
    for offset in range(0, min(liked_count, 20), 10):
        expected.append(("tracks", list(tracks[offset : offset + 10])))
    assert membership.calls == expected


def test_empty_inventories_never_request_membership() -> None:
    """No candidates means no reads and no established affinity."""
    membership = Membership()
    assert library_affinity(membership, (), ()) == (0, 0, False)
    assert membership.calls == []


def test_duplicate_ids_still_count_when_supplied_by_the_boundary() -> None:
    """This policy preserves input observations; mirror deduplication is separate."""
    membership = Membership(saved={"same"})
    assert library_affinity(membership, ("same", "same", "same"), ()) == (None, 3, True)
