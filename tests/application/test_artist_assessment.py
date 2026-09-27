"""Independent artist completion observes memberships, caches and marker precedence."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.artist_assessment import assess_artist
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from tests.support.discovery_values import release
from tests.support.discovery_values import track


@dataclass
class Catalog:
    """Script catalog facts while recording every application boundary.

    Args:
        releases: Release tracks supplied on demand.
        albums: Live saved membership observations.
        likes: Live liked membership observations.
        top: Eligible top-track response.
        popularity: Fallback live popularities.
        events: Ordered requested observations.
    """

    releases: dict[str, tuple[CatalogTrack, ...]] = field(default_factory=dict)
    albums: dict[str, bool] = field(default_factory=dict)
    likes: dict[str, bool] = field(default_factory=dict)
    top: tuple[CatalogTrack, ...] = ()
    popularity: dict[str, int] = field(default_factory=dict)
    events: list[tuple[str, object]] = field(default_factory=list)

    def saved(self, ids: list[str]) -> dict[str, bool]:
        """Read scripted album memberships.

        Args:
            ids: Requested catalog IDs, retaining duplicates.

        Returns:
            Detached accepted observations.
        """
        self.events.append(("saved", ids))
        return dict(self.albums)

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read tracks for one previously unobserved release.

        Args:
            release: Requested catalog entry.

        Returns:
            Scripted response, including empty releases.
        """
        self.events.append(("tracks", release.spotify_id))
        return self.releases.get(release.spotify_id, ())

    def liked(self, ids: list[str], *, top: bool = False) -> dict[str, bool]:
        """Read scripted likes at the requested context boundary.

        Args:
            ids: Requested unique catalog IDs or ordered top-track IDs.
            top: Whether the request belongs to top-track selection.

        Returns:
            Detached observed memberships.
        """
        self.events.append(("top_likes" if top else "likes", ids))
        return dict(self.likes)

    def top_tracks(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Observe artist top tracks after catalog assessment.

        Args:
            artist_id: Artist being assessed.

        Returns:
            Original-order scripted response.
        """
        self.events.append(("top", artist_id))
        return self.top

    def popularities(self, ids: list[str]) -> dict[str, int]:
        """Observe fallback popularity only when needed.

        Args:
            ids: Unique liked primary-artist tracks.

        Returns:
            Detached scripted popularities.
        """
        self.events.append(("popularity", ids))
        return dict(self.popularity)


def test_assessment_retains_exact_observation_order_and_shared_cache() -> None:
    """Duplicate releases count as entries but tracks and likes count unique IDs."""
    first, second = track("first"), track("second")
    guest = replace(track("guest"), primary_artist_id="guest")
    catalog = Catalog(
        releases={"album": (first, second, guest)},
        likes={"first": True},
        albums={"album": True},
        top=(second, first),
    )
    cache: dict[str, tuple[CatalogTrack, ...]] = {}
    result = assess_artist(
        catalog, "artist", (release("album"), release("album")), cache
    )
    assert catalog.events == [
        ("saved", ["album", "album"]),
        ("tracks", "album"),
        ("likes", ["first", "second"]),
        ("top", "artist"),
        ("top_likes", ["second", "first"]),
    ]
    assert (
        result.total_releases,
        result.saved_releases,
        result.total_primary_tracks,
        result.liked_tracks,
    ) == (2, 1, 2, 1)
    assert result.reasons == ("all albums saved",) and result.qualifies
    assert result.representative_track == result.top_liked_track == first
    assert cache == {"album": (first, second, guest)}


def test_existing_empty_cache_is_used_without_catalog_refetch() -> None:
    """An empty cached release is an accepted observation."""
    catalog = Catalog(releases={"album": (track("unobserved"),)})
    result = assess_artist(catalog, "artist", (release("album"),), {"album": ()})
    assert result.total_primary_tracks == 0 and result.representative_track is None
    assert catalog.events == [
        ("saved", ["album"]),
        ("likes", []),
        ("top", "artist"),
        ("top_likes", []),
    ]


def test_repeated_tracks_keep_first_encountered_catalog_facts() -> None:
    """Primary-credit filtering happens before ID deduplication."""
    original = track("same")
    other = replace(original, name="Another edition")
    guest = replace(track("guest"), primary_artist_id="guest")
    primary = replace(guest, primary_artist_id="artist")
    catalog = Catalog(
        releases={"a": (original, guest), "b": (other, primary)},
        likes={"same": True},
        top=(),
    )
    result = assess_artist(catalog, "artist", (release("a"), release("b")), {})
    assert result.total_primary_tracks == 2
    assert result.top_liked_track == original
    assert ("likes", ["same", "guest"]) in catalog.events


@pytest.mark.parametrize("top_liked", [False, True])
def test_top_likes_precede_popularity_fallback(top_liked: bool) -> None:
    """Fallback popularity is requested only if artist top tracks have no liked marker.

    Args:
        top_liked: Whether the top-track response contains a liked marker.
    """
    first, second = track("first"), track("second")
    catalog = Catalog(
        releases={"album": (first, second)},
        likes={"first": True, "second": True},
        top=(first,) if top_liked else (),
        popularity={"second": 100},
    )
    result = assess_artist(catalog, "artist", (release("album"),), {})
    assert result.top_liked_track == (first if top_liked else second)
    assert (("popularity", ["first", "second"]) in catalog.events) == (not top_liked)


def test_empty_catalog_can_still_supply_a_liked_top_marker() -> None:
    """Catalog qualification does not short-circuit the later top-track observation."""
    marker = track("top")
    catalog = Catalog(top=(marker,), likes={"top": True})
    result = assess_artist(catalog, "artist", (), {})
    assert result.top_liked_track == marker and result.representative_track is None
    assert result.liked_tracks == result.total_releases == 0 and not result.qualifies
    assert catalog.events == [
        ("saved", []),
        ("likes", []),
        ("top", "artist"),
        ("top_likes", ["top"]),
    ]
