"""Protect original lookup tie rules with pure identity observations."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.domain import lookup_selection as selection
from spotify_manager.domain.lookup_seasons import season_window
from spotify_manager.domain.lookup_values import AlbumNotFoundError
from spotify_manager.domain.lookup_values import AmbiguousAlbumError
from spotify_manager.domain.lookup_values import AmbiguousArtistError
from spotify_manager.domain.lookup_values import AmbiguousTrackError
from spotify_manager.domain.lookup_values import ArtistNotFoundError
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import TrackNotFoundError


@dataclass(frozen=True)
class Album:
    """Supply pure saved-album facts independently of Pydantic and files.

    Args:
        spotify_id: Original album identity.
        album: Original display title.
        artist: Original primary artist.
    """

    spotify_id: str
    album: str
    artist: str


def track(
    identifier: str, name: str = "Song", artist: str = "Artist", popularity: int = 50
) -> ResolvedTrack:
    """Track.

    Args:
        identifier: Original requested identity.
        name: Original optional exact display name.
        artist: Original optional primary artist constraint.
        popularity: Original integer popularity used only for representative selection.

    Returns:
        Original track result.
    """
    return ResolvedTrack(identifier, name, artist, None, popularity)


@pytest.mark.parametrize("name", ["Artist", " ARTIST "])
def test_artist_pair_deduplication(name: str) -> None:
    """Retain exact full-pair deduplication without accent folding.

    Args:
        name: Original exact reference.
    """
    assert selection.artist(
        [("id", "Artist"), ("id", "Artist"), ("other", "Ártist")], name
    ) == ("id", "Artist")


def test_artist_ambiguity_keeps_distinct_pairs_at_the_same_id() -> None:
    """Retain full-pair uniqueness even when IDs are shared."""
    with pytest.raises(AmbiguousArtistError) as error:
        selection.artist([("id", "Artist"), ("id", "ARTIST")], "Artist")
    assert error.value.candidates == [
        {"artist": "Artist", "id": "id"},
        {"artist": "ARTIST", "id": "id"},
    ]


def test_artist_has_no_popularity_or_fuzzy_fallback() -> None:
    """Reject similar and accented names under the original exact rule."""
    with pytest.raises(ArtistNotFoundError):
        selection.artist([("id", "Ártist")], "Artist")


@pytest.mark.parametrize(
    "identifier,expected",
    [("one", ("one", "Album", "First")), ("missing", ("missing", None, None))],
)
def test_local_direct_id_takes_precedence(
    identifier: str, expected: tuple[str, str | None, str | None]
) -> None:
    """Retain first direct matches and unsaved-ID evaluation.

    Args:
        identifier: Original direct identity.
        expected: Original display facts or absent facts.
    """
    albums = [Album("one", "Album", "First"), Album("one", "Album", "Last")]
    assert selection.local_album(albums, "Unknown", identifier, "Ignored") == expected


def test_local_name_tie_uses_last_value_at_first_identity_position() -> None:
    """Retain last-value behavior for repeated saved identities."""
    albums = [Album("one", "Album", "First"), Album("one", "Album", "Last")]
    assert selection.local_album(albums, "album", None, None) == (
        "one",
        "Album",
        "Last",
    )


def test_local_artist_filter_preserves_exact_matching() -> None:
    """Apply the primary-artist filter after matching the original album name."""
    albums = [
        Album("one", "Album", "First"),
        Album("two", "Album", "Second"),
        Album("skip", "Other", "Second"),
    ]
    assert selection.local_album(albums, " Album ", None, " second ") == (
        "two",
        "Album",
        "Second",
    )
    with pytest.raises(AlbumNotFoundError, match="by 'Unknown'"):
        selection.local_album(albums, "Album", None, "Unknown")


def test_local_name_ambiguity_retains_candidate_order() -> None:
    """Preserve every distinct saved identity in its first encounter position."""
    albums = [Album("one", "Album", "First"), Album("two", "Album", "Second")]
    with pytest.raises(AmbiguousAlbumError) as error:
        selection.local_album(albums, "Album", None, None)
    assert error.value.candidates == [
        {"album": "Album", "artist": "First", "id": "one"},
        {"album": "Album", "artist": "Second", "id": "two"},
    ]


def test_local_missing_reference_and_name_remain_errors() -> None:
    """Retain the original absent-reference and no-match failures."""
    with pytest.raises(ValueError):
        selection.local_album([], None, None, None)
    with pytest.raises(AlbumNotFoundError):
        selection.local_album([], "Album", None, None)


def test_track_prefers_exact_titles_before_edition_popularity() -> None:
    """Keep a quiet exact title ahead of a popular remastered edition."""
    candidates = [
        track("edition", "Song - Remaster", popularity=100),
        track("exact", popularity=1),
    ]
    assert selection.track(candidates, "Song").spotify_id == "exact"


def test_track_edition_fallback_keeps_first_popularity_tie() -> None:
    """Retain accent-normalized primary artist groups and first max ties."""
    candidates = [
        track("first", "Song - Remaster", "Ártist"),
        track("tie", "Song - Remaster", "ARTIST"),
        track("quiet", "Song - Remaster", popularity=1),
    ]
    assert selection.track(candidates, "Song").spotify_id == "first"


def test_track_chooses_highest_popularity_in_the_same_artist_group() -> None:
    """Retain the highest popularity within a normalized primary artist."""
    assert (
        selection.track(
            [track("quiet", popularity=1), track("popular", popularity=100)], "Song"
        ).spotify_id
        == "popular"
    )


def test_track_missing_and_artist_ambiguity() -> None:
    """Reject unrelated titles and retain complete cross-artist candidates."""
    with pytest.raises(TrackNotFoundError):
        selection.track([track("other", "Other")], "Song")
    with pytest.raises(AmbiguousTrackError) as error:
        selection.track([track("one"), track("two", artist="Other")], "Song")
    assert error.value.candidates == [
        {"track": "Song", "artist": "Artist", "album": "", "id": "one"},
        {"track": "Song", "artist": "Other", "album": "", "id": "two"},
    ]


@pytest.mark.parametrize(
    "credit,expected",
    [(None, False), ("other", False), ("artist", True), ("ARTIST", False)],
)
def test_primary_credit_is_identity_exact(credit: str | None, expected: bool) -> None:
    """Retain exact primary-credit qualification without name normalization.

    Args:
        credit: Original first credit.
        expected: Original qualification.
    """
    assert selection.is_primary_credit(credit, "artist") is expected


def test_live_name_ties_retain_last_metadata() -> None:
    """Keep the last matching value and filter missing or guest identities."""
    candidates = [
        LiveAlbumCandidate("one", "Album", "Artist", "Artist"),
        LiveAlbumCandidate("skip", "Other", "Artist", "Artist"),
        LiveAlbumCandidate("", "Album", "Artist", "Artist"),
        LiveAlbumCandidate("guest", "Album", "Other", "Other"),
        LiveAlbumCandidate("one", "ALBUM", "Artist", " Artist "),
    ]
    selected = selection.live_album(candidates, "album", "artist")
    assert selected.name == "ALBUM"
    assert selected.display_artist == " Artist "


def test_live_missing_and_ambiguity_preserve_original_messages() -> None:
    """Retain optional-artist error text and untrimmed candidate display names."""
    with pytest.raises(AlbumNotFoundError, match="by 'Artist'"):
        selection.live_album([], "Album", "Artist")
    with pytest.raises(AlbumNotFoundError, match="'Album' was found"):
        selection.live_album([], "Album", None)
    candidates = [
        LiveAlbumCandidate("one", " Album ", "Artist", " Artist "),
        LiveAlbumCandidate("two", "ALBUM", None, ""),
    ]
    with pytest.raises(AmbiguousAlbumError) as error:
        selection.live_album(candidates, "Album", None)
    assert error.value.candidates == [
        {"album": " Album ", "artist": " Artist ", "id": "one"},
        {"album": "ALBUM", "artist": "", "id": "two"},
    ]


def test_live_empty_normalized_names_retain_reference_display() -> None:
    """Preserve original whitespace references and empty ambiguity names."""
    candidates = [
        LiveAlbumCandidate("one", "", None, ""),
        LiveAlbumCandidate("two", "", None, ""),
    ]
    with pytest.raises(AmbiguousAlbumError) as error:
        selection.live_album(candidates, " ", None)
    assert [candidate["album"] for candidate in error.value.candidates] == [" ", " "]


@pytest.mark.parametrize(
    "month,label",
    [
        (1, "Winter 2025/2026"),
        (2, "Winter 2025/2026"),
        (3, "Spring 2026"),
        (5, "Spring 2026"),
        (6, "Summer 2026"),
        (8, "Summer 2026"),
        (9, "Autumn 2026"),
        (11, "Autumn 2026"),
        (12, "Winter 2026/2027"),
    ],
)
def test_original_local_seasons(month: int, label: str) -> None:
    """Retain all original meteorological month boundaries.

    Args:
        month: Original Berlin-local month.
        label: Original season label.
    """
    timezone = ZoneInfo("Europe/Berlin")
    when = datetime(2026, month, 1, tzinfo=timezone)
    season = season_window(when, timezone)
    assert season.label == label
    assert season.start <= when < season.end
    assert season.start.tzinfo is timezone


def test_utc_observation_crosses_the_original_local_season_boundary() -> None:
    """Retain Berlin conversion before classifying a UTC midnight boundary."""
    assert (
        season_window(
            datetime(2026, 2, 28, 23, tzinfo=UTC), ZoneInfo("Europe/Berlin")
        ).label
        == "Spring 2026"
    )
