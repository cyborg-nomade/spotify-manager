"""Protect original Golden Oldies exact mappings and ordered marker recipes."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import cast

import pytest

from spotify_manager.application import golden_selection as selection
from spotify_manager.application.something_old_values import SomethingOldSpotifyError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_oldies import LastFmTrackStat
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.infrastructure import golden_records
from tests.support.golden_selection import CatalogResponse
from tests.support.golden_selection import cases
from tests.support.golden_selection import original_outcome
from tests.support.something_old_run import ARTIST
from tests.support.something_old_run import RELEASE


@dataclass
class MarkerReads:
    """Supply typed title matches and observe the original final liked read.

    Args:
        groups: Original configured match observations in title order.
        liked_ids: Original live liked membership.
        trace: Original matching and membership read order.
    """

    groups: tuple[tuple[SpotifyTrackMatch, ...], ...]
    liked_ids: set[str]
    trace: list[str] = field(default_factory=list)

    def matches(self, title: LastFmTrackStat) -> tuple[SpotifyTrackMatch, ...]:
        """Read matches for the next original ranked title.

        Args:
            title: Original title facts.

        Returns:
            Complete configured original matches.
        """
        index = len(self.trace)
        self.trace.append(title.track)
        return self.groups[index]

    def liked(self, groups: list[tuple[SpotifyTrackMatch, ...]]) -> set[str]:
        """Observe membership only after every original title read.

        Args:
            groups: Complete gathered observations.

        Returns:
            Original live liked identities.
        """
        assert tuple(groups) == self.groups
        self.trace.append("liked")
        return self.liked_ids


@dataclass(frozen=True)
class ReleaseReads:
    """Supply original album choice and full-tracklist facts.

    Args:
        choice: Configured original release choice.
        tracks: Configured original release tracklist.
    """

    choice: str
    tracks: tuple[ReleaseTrack, ...]

    def choose(
        self, artist: GoldenOldieArtist, releases: tuple[DiscographyRelease, ...]
    ) -> str:
        """Return the original interaction choice.

        Args:
            artist: Selected history artist.
            releases: Original available studio releases.

        Returns:
            Configured original choice.
        """
        assert artist.artist and releases
        return self.choice

    def read(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read only the accepted release.

        Args:
            release: Original selected release.

        Returns:
            Complete original ordered tracklist.
        """
        assert release == RELEASE
        return self.tracks


def _selection(case: dict[str, object]) -> object:
    edge = CatalogResponse(case["payload"], cast(str, case["choice"]))
    if case["kind"] == "artist":
        choose = None if edge.choice == "absent" else edge.choose
        result = selection.resolve_artist(
            "Artist", golden_records.artist_search(edge.response, "Artist"), choose
        )
        return asdict(result) if result is not None else None
    tracks = selection.select_popular(
        ARTIST, golden_records.popular_tracks(edge.response, ARTIST)
    )
    return [asdict(track) for track in tracks]


def _outcome(case: dict[str, object]) -> object:
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _selection(case)
    except SomethingOldSpotifyError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    return json.loads(json.dumps(outcome))


@pytest.mark.parametrize("case", cases())
def test_original_golden_mapping_and_popular_recipes(case: dict[str, object]) -> None:
    """Retain immutable original raw parsing, exact matching and cap outcomes.

    Args:
        case: Original raw boundary inputs and observed result.
    """
    assert original_outcome(case) == case["outcome"]
    assert _outcome(case) == case["outcome"]


def _artist(titles: tuple[LastFmTrackStat, ...] = ()) -> GoldenOldieArtist:
    return GoldenOldieArtist("Artist", 50, 100, 0, 200, titles)


def _match(identity: str, album_similarity: float | None = None) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        identity,
        f"track:{identity}",
        identity,
        ("Artist",),
        "Album",
        1,
        1.0,
        album_similarity,
        50,
    )


def test_lastfm_recipe_reads_all_titles_before_liked_and_deduplicates() -> None:
    """Prefer liked versions, skip unsafe titles and retain first distinct markers."""
    titles = (
        LastFmTrackStat("first", 30, 200),
        LastFmTrackStat("duplicate", 20, 150),
        LastFmTrackStat("unsafe", 10, 100),
        LastFmTrackStat("empty", 5, 50),
    )
    edge = MarkerReads(
        (
            (_match("plain"), _match("liked", 0.1)),
            (_match("liked"),),
            (_match("unsafe", 0.1),),
            (),
        ),
        {"liked"},
    )
    result = selection.select_lastfm(_artist(titles), edge.matches, edge.liked)
    assert edge.trace == ["first", "duplicate", "unsafe", "empty", "liked"]
    assert len(result) == 1
    assert result[0].spotify_id == "liked"
    assert result[0].lastfm_scrobbles == 30
    assert result[0].source == "Last.fm top tracks"


@pytest.mark.parametrize("titles", [(), (LastFmTrackStat("missing", 50, 200),)])
def test_lastfm_recipe_reads_liked_before_empty_selection_error(
    titles: tuple[LastFmTrackStat, ...],
) -> None:
    """Retain the original liked read even when no title can produce a marker.

    Args:
        titles: Empty or unmatched original history titles.
    """
    edge = MarkerReads(tuple(() for _title in titles), set())
    with pytest.raises(SomethingOldSpotifyError, match="matched Spotify safely"):
        selection.select_lastfm(_artist(titles), edge.matches, edge.liked)
    assert edge.trace[-1] == "liked"


@pytest.mark.parametrize(
    "choice,available,error",
    [
        ("quit", True, None),
        ("release", True, None),
        ("missing", True, "invalid"),
        ("quit", False, "No studio"),
        ("empty", True, "no playable"),
    ],
)
def test_album_recipe_preserves_choice_and_complete_tracklist(
    choice: str,
    available: bool,
    error: str | None,
) -> None:
    """Protect cancellation, catalog guards and complete uncapped album projection.

    Args:
        choice: Original configured release choice.
        available: Whether the original catalog has an eligible studio release.
        error: Original expected error fragment.
    """
    tracks = (
        () if choice == "empty" else (ReleaseTrack("one", "track:one", "One", 1, 1),)
    )
    edge = ReleaseReads("release" if choice == "empty" else choice, tracks)
    releases = (RELEASE,) if available else ()
    if error is not None:
        with pytest.raises(SomethingOldSpotifyError, match=error):
            selection.select_album(_artist(), ARTIST, releases, edge.choose, edge.read)
        return
    release, selected = selection.select_album(
        _artist(), ARTIST, releases, edge.choose, edge.read
    )
    if choice == "quit":
        assert release is None and selected == ()
        return
    assert release == RELEASE
    assert selected[0].track == "One"
    assert selected[0].artists == (ARTIST.name,)
    assert selected[0].source == "Album: Release"
