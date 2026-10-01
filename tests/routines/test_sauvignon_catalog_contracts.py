"""Original Sauvignon catalog parsing, coercion and first-track response contracts."""

from dataclasses import dataclass
from dataclasses import field
from typing import Literal
from unittest.mock import Mock

import pytest

from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import sauvignon
from tests.routines.test_sauvignon import album_option
from tests.routines.test_sauvignon import immediate
from tests.routines.test_sauvignon import raw_spotify_track
from tests.routines.test_sauvignon import track_candidate


MATCH = blast.SpotifyTrackMatch(
    "track", "uri", "Track", ("New Artist",), "Album", 7, 0.9, None, 50
)


@dataclass
class MatchSteps:
    """Observe mandatory artist/title qualification before album-shape validation.

    Args:
        accepted: Whether the original mandatory qualification succeeds.
        calls: Original play, raw observation and search rank.
    """

    accepted: bool = True
    calls: list[tuple[blast.Scrobble, object, int]] = field(default_factory=list)

    def match(
        self, play: blast.Scrobble, raw: object, rank: int
    ) -> blast.SpotifyTrackMatch | None:
        """Observe the original mandatory matching boundary.

        Args:
            play: Album-free original candidate metadata.
            raw: Original raw search observation.
            rank: Original one-based search position.

        Returns:
            Configured original mandatory match or no match.
        """
        self.calls.append((play, raw, rank))
        return MATCH if self.accepted else None


def _album(raw: dict[str, object]) -> dict[str, object]:
    album = raw["album"]
    assert isinstance(album, dict)
    return album


@pytest.mark.parametrize(
    "scope,key,value,eligible",
    [
        ("track", "artists", None, False),
        ("track", "artists", [], False),
        (
            "track",
            "artists",
            [{"id": "other", "name": "Other"}, {"id": "artist", "name": "New Artist"}],
            False,
        ),
        ("track", "album", None, False),
        ("album", "artists", [], False),
        ("album", "artists", [{"id": "other", "name": "Other"}], False),
        ("album", "id", " ", False),
        ("album", "uri", None, False),
        ("album", "name", " ", False),
        ("album", "total_tracks", True, True),
        ("album", "total_tracks", -1, True),
        ("album", "total_tracks", "10", True),
        ("album", "album_type", "compilation", False),
        ("album", "name", "New Album Live", False),
        ("album", "name", "New Album (Deluxe)", False),
        ("album", "release_date", None, True),
    ],
)
def test_original_album_shape_and_coercion(
    monkeypatch: pytest.MonkeyPatch,
    scope: Literal["track", "album"],
    key: str,
    value: object,
    eligible: bool,
) -> None:
    """Retain exact primary credits and original eligible metadata tolerance.

    Args:
        monkeypatch: Scoped original mandatory match observation.
        scope: Raw track or embedded album fields to alter.
        key: Original metadata field.
        value: Original permissive or rejected metadata value.
        eligible: Whether the original parser accepts the observation.
    """
    steps = MatchSteps()
    monkeypatch.setattr(blast, "matching_spotify_track", steps.match)
    raw = raw_spotify_track()
    target = raw if scope == "track" else _album(raw)
    target[key] = value
    option = sauvignon._album_option(raw, track_candidate(), 7)
    assert (option is not None) is eligible
    assert steps.calls == [(blast.Scrobble("New Track", "New Artist", "", 0), raw, 7)]
    if option is not None:
        assert option.total_tracks == (0 if key == "total_tracks" else 10)
        assert option.release_date == (
            "Unknown" if key == "release_date" else "2024-01-01"
        )


@pytest.mark.parametrize("accepted,raw", [(False, {}), (True, None), (True, [])])
def test_original_mandatory_match_precedes_track_shape_validation(
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool,
    raw: object,
) -> None:
    """Always observe mandatory matching before rejecting raw track or album shape.

    Args:
        monkeypatch: Scoped original mandatory qualification.
        accepted: Whether mandatory matching succeeds.
        raw: Original search observation.
    """
    steps = MatchSteps(accepted)
    monkeypatch.setattr(blast, "matching_spotify_track", steps.match)
    assert sauvignon._album_option(raw, track_candidate(), 7) is None
    assert len(steps.calls) == 1


def test_original_artist_pair_fallback_and_whitespace_tolerance() -> None:
    """Keep ID fallback before stripping, skipping invalid rows and blank names."""
    assert sauvignon._artist_pairs(None) == ()
    assert sauvignon._artist_pairs(
        [None, {}, {"id": " x ", "name": " "}, {"id": "y", "name": ""}, {"id": 9}]
    ) == (("y", "y"), ("9", "9"))


@pytest.mark.parametrize(
    "raw,expected", [(True, 0), (-1, 0), ("10", 0), (None, 0), (0, 0), (4, 4)]
)
def test_original_nonnegative_track_count_coercion(raw: object, expected: int) -> None:
    """Boolean and string counts retain the original zero fallback.

    Args:
        raw: Original metadata count.
        expected: Original accepted count.
    """
    assert sauvignon._positive_int(raw) == expected


@pytest.mark.parametrize(
    "response,message",
    [
        (None, "invalid tracks"),
        ({"items": "bad"}, "invalid tracks"),
        ({"items": []}, "No playable"),
        ({"items": [None, {"id": "x", "uri": " ", "name": "Title"}]}, "No playable"),
    ],
)
def test_original_first_track_failure_responses(response: object, message: str) -> None:
    """Retain invalid-response and no-playable-track errors without changing order.

    Args:
        response: Original raw album-track response.
        message: Original error fragment.
    """
    spotify = Mock()
    spotify.album_tracks.return_value = response
    with pytest.raises(sauvignon.SauvignonSpotifyError, match=message):
        sauvignon.load_first_track(spotify, album_option(), immediate)
    spotify.album_tracks.assert_called_once_with("album-id", limit=50, offset=0)
