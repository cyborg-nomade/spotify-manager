"""Observe future-record cache ownership and original first-match resolution."""

import pytest

from spotify_manager.application.future_release import matching_future_record
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from tests.support.future_release import Reads


SINGLE = ReleaseTrack("single", "uri", "Song (Remastered)", "artist", "Artist", 1, 1)


def _release(identity: str) -> ReleaseCandidate:
    return ReleaseCandidate(
        identity, identity, identity, "Album", "2027", "year", 10, "artist", "Artist"
    )


def _track(identity: str = "different", title: str = "Song") -> ReleaseTrack:
    return ReleaseTrack(identity, identity, title, "artist", "Artist", 1, 1)


def _run(
    observed: Reads,
    cache: dict[str, tuple[ReleaseTrack, ...]] | None = None,
    single: ReleaseTrack = SINGLE,
) -> ReleaseCandidate | None:
    return matching_future_record(
        observed.read, single, (_release("one"), _release("two")), cache
    )


@pytest.mark.parametrize("track", [_track(), _track("single", "Different")])
def test_future_future_record_identity_and_qualifier_title(track: ReleaseTrack) -> None:
    """Retain first ID or qualifier-title matches and their cached observations.

    Args:
        track: Original first matching observation.
    """
    observed = Reads({"one": (track,), "two": (_track(),)})
    cache: dict[str, tuple[ReleaseTrack, ...]] = {}
    assert _run(observed, cache) == _release("one")
    assert observed.events == ["one"]
    assert cache == {"one": (track,)}


def test_future_future_record_empty_cache_hits_and_first_match() -> None:
    """Retain empty cache hits and caller-owned identity without additional reads."""
    observed = Reads({})
    cache = {"one": (), "two": (_track(),)}
    assert _run(observed, cache) == _release("two")
    assert observed.events == []
    assert cache == {"one": (), "two": (_track(),)}


def test_future_future_record_empty_normalized_title_is_not_a_match() -> None:
    """Reject empty title equality and keep original observed misses in the cache."""
    single = _track("single", " ")
    observed = Reads({"one": (_track("different", " "),)})
    cache: dict[str, tuple[ReleaseTrack, ...]] = {}
    assert _run(observed, cache, single) is None
    assert observed.events == ["one", "two"]
    assert cache == {"one": observed.tracks["one"], "two": ()}


def test_future_future_record_read_failure_retains_prior_cache() -> None:
    """Retain accepted prior observations when the next catalog read fails."""
    observed = Reads({"one": (_track("other", "Unrelated"),)}, fail="two")
    cache: dict[str, tuple[ReleaseTrack, ...]] = {}
    with pytest.raises(RuntimeError, match="two"):
        _run(observed, cache)
    assert observed.events == ["one", "two"]
    assert cache == {"one": observed.tracks["one"]}


def test_future_future_record_without_caller_cache() -> None:
    """Retain original default cache lifetime for one invocation."""
    observed = Reads({"two": (_track(),)})
    assert _run(observed) == _release("two")
    assert observed.events == ["one", "two"]
