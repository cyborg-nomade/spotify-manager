"""Original Found Art matching, batch observations and failure boundaries."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import found_art
from tests.routines.test_found_art import candidate


EMPTY_PLAYLIST = blast.PlaylistState(0, frozenset())
type MatchEvent = tuple[str, str | tuple[tuple[blast.SpotifyTrackMatch, ...], ...]]


def _match(identity: str, similarity: float = 1.0) -> blast.SpotifyTrackMatch:
    return blast.SpotifyTrackMatch(
        identity,
        f"spotify:track:{identity}",
        "Song",
        ("Artist",),
        "Album",
        1,
        similarity,
        None,
        50,
    )


@dataclass
class MatchingSteps:
    """Record original complete-batch reads before candidate projection.

    Args:
        groups: Search observations keyed by original candidate title.
        liked_ids: Live liked identities.
        failure: Optional observation to fail after recording it.
        events: Ordered search and liked observations.
        messages: Original visible progress.
    """

    groups: dict[str, tuple[blast.SpotifyTrackMatch, ...]] = field(default_factory=dict)
    liked_ids: set[str] = field(default_factory=set)
    failure: str = ""
    events: list[MatchEvent] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def search(
        self, sp: Spotify, play: blast.Scrobble
    ) -> tuple[blast.SpotifyTrackMatch, ...]:
        """Read one original search observation.

        Args:
            sp: Unused caller-owned client.
            play: Original candidate converted to an album-free play.

        Returns:
            Configured ordered matches.

        Raises:
            OSError: The configured observation fails.
        """
        assert play.album == "" and play.timestamp_ms == 0
        self.events.append(("search", play.track))
        if self.failure == play.track:
            raise OSError(play.track)
        return self.groups.get(play.track, ())

    def liked(
        self, sp: Spotify, groups: list[tuple[blast.SpotifyTrackMatch, ...]]
    ) -> set[str]:
        """Read liked status once for a fully observed batch, including empty groups.

        Args:
            sp: Unused caller-owned client.
            groups: Ordered search groups.

        Returns:
            Original live liked identities.

        Raises:
            OSError: The configured liked observation fails.
        """
        self.events.append(("liked", tuple(groups)))
        if self.failure == "liked":
            raise OSError("liked")
        return self.liked_ids


def _install(steps: MatchingSteps, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blast, "search_spotify_matches", steps.search)
    monkeypatch.setattr(blast, "liked_spotify_track_ids", steps.liked)


def _resolve(
    candidates: tuple[found_art.FoundArtCandidate, ...],
    steps: MatchingSteps,
    count: int = 1,
    playlist: blast.PlaylistState = EMPTY_PLAYLIST,
    dry_run: bool = False,
) -> tuple[tuple[found_art.FoundArtResult, ...], tuple[blast.SpotifyTrackMatch, ...]]:
    return found_art.resolve_spotify_candidates(
        cast(Spotify, object()),
        candidates,
        playlist,
        count=count,
        dry_run=dry_run,
        progress_callback=steps.messages.append,
    )


@pytest.mark.parametrize("dry_run", [False, True])
def test_batch_is_fully_observed_before_artist_and_capacity_decisions(
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    """Keep skipped outcomes after capacity until the next eligible addition.

    Args:
        monkeypatch: Isolated original boundary patches.
        dry_run: Original action presentation mode.
    """
    steps = MatchingSteps(
        {
            "One": (_match("one"),),
            "Two": (_match("two"),),
            "Liked": (_match("liked"),),
            "Stop": (_match("stop"),),
        },
        {"liked"},
    )
    _install(steps, monkeypatch)
    candidates = (
        candidate("Same", "One", 1),
        candidate("Same", "Two", 1),
        candidate("Liked", "Liked", 1),
        candidate("Missing", "Missing", 1),
        candidate("Stop", "Stop", 1),
        candidate("Later", "Later", 1),
    )
    results, pending = _resolve(candidates, steps, dry_run=dry_run)
    assert [result.action for result in results] == [
        "would add" if dry_run else "added",
        "artist already selected",
        "liked",
        "no Spotify match",
    ]
    assert [item.spotify_id for item in pending] == ["one"]
    assert steps.events[:-1] == [("search", item.track) for item in candidates]
    assert steps.events[-1][0] == "liked"
    assert len(steps.messages) == 7


def test_liked_identity_wins_over_playlist_membership_and_rank_ignores_album(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Liked matches suppress additions even when present or weaker than unliked ones.

    Args:
        monkeypatch: Isolated original boundary patches.
    """
    low_album = replace(_match("liked-low"), album_similarity=0.1, popularity=90)
    high_album = replace(_match("liked-high"), album_similarity=1.0, popularity=80)
    steps = MatchingSteps(
        {"Song": (high_album, low_album, _match("unliked"))},
        {"liked-low", "liked-high"},
    )
    _install(steps, monkeypatch)
    results, pending = _resolve(
        (candidate("Artist", "Song", 1),),
        steps,
        playlist=blast.PlaylistState(1, frozenset({"liked-low"})),
    )
    assert pending == ()
    assert results[0].action == "liked"
    assert results[0].match == replace(low_album, liked=True)


def test_key_membership_skips_search_but_retains_empty_liked_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read liked status even when every candidate key skips catalog search.

    Args:
        monkeypatch: Isolated original boundary patches.
    """
    item = candidate("Artist", "Song", 1)
    steps = MatchingSteps()
    _install(steps, monkeypatch)
    results, pending = _resolve(
        (item,),
        steps,
        playlist=blast.PlaylistState(1, frozenset(), frozenset({item.key})),
    )
    assert steps.events == [("liked", ((),))]
    assert results[0].match is None and results[0].action == "already present"
    assert pending == ()


@pytest.mark.parametrize("count", [0, -1])
def test_nonpositive_helper_count_has_no_observations(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    """Preserve helper tolerance separately from run-level positive-count validation.

    Args:
        monkeypatch: Isolated original boundary patches.
        count: Original nonpositive helper input.
    """
    steps = MatchingSteps()
    _install(steps, monkeypatch)
    assert _resolve((candidate("Artist", "Song", 1),), steps, count) == ((), ())
    assert steps.events == steps.messages == []


@pytest.mark.parametrize(
    "failure,events",
    [
        ("Two", [("search", "One"), ("search", "Two")]),
        ("liked", [("search", "One"), ("search", "Two"), ("liked", ((), ()))]),
    ],
)
def test_failed_batch_observation_prevents_projection(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    events: list[MatchEvent],
) -> None:
    """A failed search or liked read stops before any result is returned.

    Args:
        monkeypatch: Isolated original boundary patches.
        failure: Observation to fail.
        events: Original accepted observation prefix.
    """
    steps = MatchingSteps(failure=failure)
    _install(steps, monkeypatch)
    with pytest.raises(OSError, match=failure):
        _resolve((candidate("One", "One", 1), candidate("Two", "Two", 1)), steps)
    assert steps.events == events


def test_final_batch_retains_original_slice_beyond_search_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain full final slices when configured limits do not divide the batch size.

    Args:
        monkeypatch: Isolated original boundary patches.
    """
    monkeypatch.setattr(found_art, "SPOTIFY_RESOLUTION_BATCH_SIZE", 3)
    monkeypatch.setattr(found_art, "SPOTIFY_CANDIDATE_MULTIPLIER", 1)
    steps = MatchingSteps()
    _install(steps, monkeypatch)
    candidates = tuple(candidate(str(index), str(index), 1) for index in range(5))
    results, pending = _resolve(candidates, steps, count=4)
    assert len(results) == 5 and pending == ()
    assert steps.messages[-2:] == [
        "Searching Spotify candidate 5/4",
        "Checking candidates against Spotify Liked Songs",
    ]
