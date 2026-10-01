"""Protect original future-record cache ownership and ordered first-match resolution."""

from functools import partial
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import release_check as legacy
from tests.support.future_release import Reads


SINGLE = legacy.ReleaseTrack(
    "single", "uri", "Song (Remastered)", "artist", "Artist", 1, 1
)


def _release(identity: str) -> legacy.ReleaseCandidate:
    return legacy.ReleaseCandidate(
        identity, identity, identity, "Album", "2027", "year", 10, "artist", "Artist"
    )


def _track(identity: str = "different", title: str = "Song") -> legacy.ReleaseTrack:
    return legacy.ReleaseTrack(identity, identity, title, "artist", "Artist", 1, 1)


def _read(
    observed: Reads, sp: object, release: legacy.ReleaseCandidate, retry: object
) -> tuple[legacy.ReleaseTrack, ...]:
    return observed.read(release)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    observed: Reads,
    cache: dict[str, tuple[legacy.ReleaseTrack, ...]] | None = None,
    single: legacy.ReleaseTrack = SINGLE,
) -> legacy.ReleaseCandidate | None:
    monkeypatch.setattr(legacy, "load_release_tracks", partial(_read, observed))
    return legacy.matching_future_release(
        cast(Spotify, object()),
        single,
        (_release("one"), _release("two")),
        cast(legacy.RetryCall, object()),
        cache,
    )


@pytest.mark.parametrize("track", [_track(), _track("single", "Different")])
def test_original_future_record_identity_and_qualifier_title(
    monkeypatch: pytest.MonkeyPatch, track: legacy.ReleaseTrack
) -> None:
    """Retain first ID or qualifier-title matches and their cached observations.

    Args:
        monkeypatch: Original read substitution.
        track: Original first matching observation.
    """
    observed = Reads({"one": (track,), "two": (_track(),)})
    cache: dict[str, tuple[legacy.ReleaseTrack, ...]] = {}
    assert _run(monkeypatch, observed, cache) == _release("one")
    assert observed.events == ["one"]
    assert cache == {"one": (track,)}


def test_original_future_record_empty_cache_hits_and_first_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain empty cache hits and caller-owned identity without additional reads.

    Args:
        monkeypatch: Original read substitution.
    """
    observed = Reads({})
    cache = {"one": (), "two": (_track(),)}
    assert _run(monkeypatch, observed, cache) == _release("two")
    assert observed.events == []
    assert cache == {"one": (), "two": (_track(),)}


def test_original_future_record_empty_normalized_title_is_not_a_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject empty title equality and keep original observed misses in the cache.

    Args:
        monkeypatch: Original read substitution.
    """
    single = _track("single", " ")
    observed = Reads({"one": (_track("different", " "),)})
    cache: dict[str, tuple[legacy.ReleaseTrack, ...]] = {}
    assert _run(monkeypatch, observed, cache, single) is None
    assert observed.events == ["one", "two"]
    assert cache == {"one": observed.tracks["one"], "two": ()}


def test_original_future_record_read_failure_retains_prior_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain accepted prior observations when the next catalog read fails.

    Args:
        monkeypatch: Original read substitution.
    """
    observed = Reads({"one": (_track("other", "Unrelated"),)}, fail="two")
    cache: dict[str, tuple[legacy.ReleaseTrack, ...]] = {}
    with pytest.raises(RuntimeError, match="two"):
        _run(monkeypatch, observed, cache)
    assert observed.events == ["one", "two"]
    assert cache == {"one": observed.tracks["one"]}


def test_original_future_record_without_caller_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain original default cache lifetime for one invocation.

    Args:
        monkeypatch: Original read substitution.
    """
    observed = Reads({"two": (_track(),)})
    assert _run(monkeypatch, observed) == _release("two")
    assert observed.events == ["one", "two"]
