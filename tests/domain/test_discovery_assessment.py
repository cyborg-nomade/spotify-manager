"""Artist marker selection and qualification keep the existing discovery policies."""

from dataclasses import replace

from spotify_manager.domain.discovery_assessment import first_liked
from spotify_manager.domain.discovery_assessment import popular_liked_track
from spotify_manager.domain.discovery_assessment import qualification_reasons
from spotify_manager.domain.discovery_assessment import representative_track
from tests.support.discovery_values import release
from tests.support.discovery_values import track


def test_reasons_keep_album_only_universal_test_and_all_observed_saved_counts() -> None:
    """Extra saved statuses count; EPs do not participate in the all-albums rule."""
    album = release("album")
    ep = replace(release("ep"), release_type="EP")
    assert qualification_reasons(
        (album, album, ep), {"album": True}, liked_tracks=0, total_tracks=1
    ) == ("all albums saved",)
    assert qualification_reasons(
        (ep,),
        {"one": True, "two": True, "three": True},
        liked_tracks=18,
        total_tracks=18,
    ) == (
        "18 liked tracks",
        "3 saved releases",
        "all tracks liked",
    )
    assert qualification_reasons((album,), {}, liked_tracks=0, total_tracks=0) == ()


def test_representative_prefers_studio_then_chronology_then_title() -> None:
    """An older fallback cannot displace an eligible studio marker."""
    fallback = replace(release("fallback"), tier=1, release_date="1990")
    latest = replace(release("latest"), release_date="2021")
    first = release("first")
    guest = replace(track("guest"), primary_artist_id="guest")
    tracks = {
        "fallback": (track("fallback"),),
        "latest": (track("latest"),),
        "first": (guest, track("first")),
    }
    assert representative_track("artist", (fallback, latest, first), tracks) == track(
        "first"
    )
    assert representative_track("absent", (fallback, latest, first), tracks) is None
    assert representative_track("artist", (first,), {}) is None


def test_empty_or_foreign_studio_can_fall_back_to_another_release() -> None:
    """A release without eligible primary credits is skipped during marker choice."""
    first, second = release("first"), release("second")
    assert representative_track(
        "artist", (first, second), {"second": (track("second"),)}
    ) == track("second")


def test_top_track_selection_preserves_response_order() -> None:
    """The first liked response wins regardless of its attached popularity field."""
    first, second = track("first"), replace(track("second"), popularity=100)
    assert first_liked((first, second), {"second": True}) == second
    assert first_liked((first, second), {"first": True, "second": True}) == first
    assert first_liked((first,), {}) is None


def test_popularity_fallback_retains_title_ties_and_first_exact_tie() -> None:
    """Missing popularity ranks below known values and ties sort by casefolded title."""
    alpha, zulu = track("Alpha"), track("Zulu")
    duplicate = replace(zulu, spotify_id="duplicate")
    assert popular_liked_track([alpha, zulu], {"Alpha": 1}) == alpha
    assert popular_liked_track([zulu, alpha], {}) == zulu
    assert popular_liked_track([alpha, zulu, duplicate], {}) == zulu
    assert popular_liked_track([], {}) is None
