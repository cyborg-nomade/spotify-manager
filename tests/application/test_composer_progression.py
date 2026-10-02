"""Works progression retains limits, durable layouts and completion routing priority."""

from dataclasses import asdict
from dataclasses import replace

import pytest

from spotify_manager.application.composer_progression import composer_plan
from spotify_manager.application.composer_progression import composer_step
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.composers import OwnedPlaylist
from tests.support.discovery_values import track
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
NEXT = replace(SOURCE, spotify_id="next", name="Next")
PLAYLIST = OwnedPlaylist("works", "[CD] Bach works", 100)


def test_empty_works_playlist_retains_original_application_error() -> None:
    """No decision can be made without an observed works marker."""
    with pytest.raises(NewKidsError, match="works playlist is empty"):
        composer_step(SOURCE, ())


def test_unmapped_marker_starts_at_first_work_and_mapped_marker_advances() -> None:
    """Unmapped markers do not contribute to the completed count."""
    assert composer_step(SOURCE, (NEXT,)) == (0, NEXT)
    assert composer_step(SOURCE, (SOURCE, NEXT)) == (1, NEXT)
    assert composer_step(NEXT, (SOURCE, NEXT)) == (2, None)


def test_fortieth_work_completes_even_when_more_tracks_remain() -> None:
    """The completion cap follows the original stored playlist positions."""
    tracks = tuple(
        replace(SOURCE, spotify_id=str(index), name=str(index)) for index in range(41)
    )
    assert composer_step(tracks[39], tracks) == (40, None)
    assert composer_step(tracks[40], tracks) == (41, None)
    assert composer_step(tracks[0], tracks, limit=1) == (1, None)


def test_advance_plan_uses_logical_composer_and_resets_streak() -> None:
    """Works progression records the same durable fields as ordinary discovery plans."""
    result = composer_plan(
        SOURCE,
        "composer",
        "Bach",
        PLAYLIST,
        (SOURCE, NEXT),
        current_liked=False,
        assessment=None,
    )
    assert result["action"] == result["result_action"] == "advance"
    assert result["composer_position"] == 1 and result["composer_limit"] == 2
    assert result["consecutive_unliked"] == result["next_prior_unliked_streak"] == 0
    expected = asdict(track("next"))
    expected.update(
        uri=NEXT.uri,
        name="Next",
        primary_artist_id="composer",
        primary_artist_name="Bach",
    )
    assert result["target"] == expected
    assert result["advance_reason"] == "next composer work"


def test_completion_requires_live_assessment() -> None:
    """A terminal work cannot be routed without the original assessment."""
    with pytest.raises(NewKidsStateError, match="lacks assessment"):
        composer_plan(
            SOURCE,
            "composer",
            "Bach",
            PLAYLIST,
            (SOURCE,),
            current_liked=True,
            assessment=None,
        )


@pytest.mark.parametrize(
    "qualifies,top,action",
    [
        (True, False, "unfollowed"),
        (False, False, "unfollowed"),
        (True, True, "great discovery"),
        (False, True, "unlucky"),
    ],
)
def test_completion_prioritizes_top_like_absence_over_qualification(
    qualifies: bool, top: bool, action: str
) -> None:
    """The original zero-top-like route wins even when an album criterion qualifies.

    Args:
        qualifies: Existing promotion criterion result.
        top: Whether assessment supplied a liked top marker.
        action: Original expected destination action.
    """
    assessment = ArtistAssessment(
        1, 3, 3, 1, 10, qualifies, (), None, track("top") if top else None
    )
    result = composer_plan(
        NEXT,
        "composer",
        "Bach",
        PLAYLIST,
        (SOURCE, NEXT),
        current_liked=True,
        assessment=assessment,
    )
    assert result["action"] == "finish" and result["result_action"] == action
    assert result["assessment"] == asdict(assessment)
    assert result["target"] is result["target_release"] is None
    assert result["composer_destination_track"] == {
        "spotify_id": SOURCE.spotify_id,
        "uri": SOURCE.uri,
        "name": SOURCE.name,
        "disc_number": 1,
        "track_number": 1,
        "primary_artist_id": "composer",
        "primary_artist_name": "Bach",
        "popularity": None,
    }
