"""Historical release completion retains prefiltering, observation order and caches."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.release_history import played_releases
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from tests.support.discovery_values import release
from tests.support.discovery_values import track


@dataclass
class Catalog:
    """Serve completion observations while recording requested reads.

    Args:
        releases: Scripted release track responses.
        liked: Live memberships keyed by track ID.
        events: Ordered requested observations.
        fail_likes: Whether to interrupt the next liked-status request.
    """

    releases: dict[str, tuple[CatalogTrack, ...]] = field(default_factory=dict)
    liked: dict[str, bool] = field(default_factory=dict)
    events: list[tuple[str, object]] = field(default_factory=list)
    fail_likes: bool = False

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read one release that passed the inexpensive history prefilter.

        Args:
            release: Candidate catalog entry.

        Returns:
            Original ordered scripted tracks.
        """
        self.events.append(("tracks", release.spotify_id))
        return self.releases.get(release.spotify_id, ())

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Populate missing statuses without overwriting accepted cached observations.

        Args:
            ids: Requested identifiers, retaining duplicates.
            cache: Shared mutable live-membership cache.

        Raises:
            RuntimeError: The scripted membership interruption occurs.
        """
        self.events.append(("likes", ids))
        if self.fail_likes:
            self.fail_likes = False
            raise RuntimeError("likes interrupted")
        for spotify_id in ids:
            cache.setdefault(spotify_id, self.liked.get(spotify_id, False))


def test_insufficient_history_never_reads_tracks_or_membership() -> None:
    """Studio minimum applies before any live observation."""
    catalog = Catalog()
    history = {("artist", "album"): frozenset({"one", "two"})}
    assert played_releases(catalog, (release("album"),), history, {}, {}) == ()
    assert catalog.events == []


def test_prefilter_can_pass_other_artist_titles_but_final_matching_rejects_them() -> (
    None
):
    """The cheap prefilter deliberately ignores credits; the full decision does not."""
    tracks = (track("one"), track("two"), track("three"))
    catalog = Catalog(releases={"album": tracks})
    history = {("other artist", "album"): frozenset({"one", "two", "three"})}
    assert played_releases(catalog, (release("album"),), history, {}, {}) == ()
    assert catalog.events == [("tracks", "album"), ("likes", ["one", "two", "three"])]


def test_duplicate_releases_keep_result_order_and_share_observed_tracks() -> None:
    """A duplicate entry remains a result while its track read is reused."""
    album = release("album")
    tracks = (track("one"), track("two"), track("three"))
    catalog = Catalog(releases={"album": tracks})
    history = {("artist", "album"): frozenset({"one", "two", "three"})}
    track_cache: dict[str, tuple[CatalogTrack, ...]] = {}
    liked: dict[str, bool] = {}
    assert played_releases(catalog, (album, album), history, track_cache, liked) == (
        album,
        album,
    )
    assert catalog.events == [
        ("tracks", "album"),
        ("likes", ["one", "two", "three"]),
        ("likes", ["one", "two", "three"]),
    ]
    assert track_cache == {"album": tracks} and liked == {
        "one": False,
        "two": False,
        "three": False,
    }


def test_track_observation_survives_a_later_membership_failure() -> None:
    """Shared accepted tracks remain cached even if subsequent membership fails."""
    album = replace(release("album"), tier=1)
    catalog = Catalog(releases={"album": (track("one"),)}, fail_likes=True)
    history = {("artist", "album"): frozenset({"one"})}
    cache: dict[str, tuple[CatalogTrack, ...]] = {}
    with pytest.raises(RuntimeError, match="likes interrupted"):
        played_releases(catalog, (album,), history, cache, {})
    assert cache == {"album": (track("one"),)}
    assert played_releases(catalog, (album,), history, cache, {}) == (album,)
    assert catalog.events == [
        ("tracks", "album"),
        ("likes", ["one"]),
        ("likes", ["one"]),
    ]


def test_cached_empty_tracks_and_existing_likes_are_retained() -> None:
    """Accepted cache contents are never refreshed by the completion use case."""
    album = replace(release("album"), tier=1)
    catalog = Catalog(releases={"album": (track("one"),)}, liked={"one": False})
    history = {("artist", "album"): frozenset({"one"})}
    likes = {"one": True}
    assert played_releases(catalog, (album,), history, {"album": ()}, likes) == ()
    assert catalog.events == [("likes", [])]
    assert likes == {"one": True}


def test_configured_limits_filter_fallback_catalog_and_apply_studio_minimum() -> None:
    """Existing caller-owned thresholds continue to control observation eligibility."""
    album, single = release("album"), replace(release("single"), tier=1)
    catalog = Catalog(releases={"album": (track("one"),), "single": (track("single"),)})
    history = {
        ("artist", "album"): frozenset({"one"}),
        ("artist", "single"): frozenset({"single"}),
    }
    assert played_releases(
        catalog, (single, album), history, {}, {}, release_limit=1, studio_minimum=1
    ) == (album,)
    assert catalog.events == [("tracks", "album"), ("likes", ["one"])]
