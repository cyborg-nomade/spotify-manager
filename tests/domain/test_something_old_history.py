"""Keep mode history attached to exact Spotify identities rather than labels."""

from dataclasses import replace
from datetime import timedelta
from datetime import timezone

from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import choice_identity
from spotify_manager.domain.something_old_history import previous_modes
from tests.support.queue_neighbors import NOW


def recorded_choice() -> ArtistChoice:
    """Build completed evidence with stable identity and an original display label.

    Returns:
        One explicit prior Spotify-track selection.
    """
    return ArtistChoice(
        "artist",
        "Original Name",
        "History label",
        "spotify_top_tracks",
        NOW,
        "destination",
        ("track",),
    )


def test_renames_preserve_history_while_same_name_artists_stay_separate() -> None:
    """Only the accepted Spotify identity joins prior events to the current prompt."""
    first = recorded_choice()
    renamed = replace(first, artist_name="New Name", chosen_at=NOW + timedelta(days=1))
    homonym = replace(
        first, artist_id="other-artist", artist_name="New Name", mode="album"
    )
    ledger = ChoiceLedger(
        choices={
            choice_identity(first): first,
            choice_identity(renamed): renamed,
            choice_identity(homonym): homonym,
        }
    )
    history = previous_modes(ledger, "artist")
    assert [entry.count for entry in history] == [0, 2, 0]
    assert history[1].last_chosen_at == renamed.chosen_at
    assert [entry.count for entry in previous_modes(ledger, "other-artist")] == [
        0,
        0,
        1,
    ]


def test_modes_count_only_completed_events_and_keep_the_latest_album() -> None:
    """Unconfirmed intents cannot appear as a chosen source."""
    first = recorded_choice()
    album = replace(
        first,
        mode="album",
        release_name="Selected Album",
        release_id="release",
        chosen_at=NOW + timedelta(days=2),
        provenance="recovered",
    )
    ledger = ChoiceLedger(
        choices={choice_identity(first): first, choice_identity(album): album},
        pending={"destination": replace(first, mode="lastfm_top_tracks")},
    )
    history = previous_modes(ledger, "artist")
    assert [entry.count for entry in history] == [0, 1, 1]
    assert history[2].release_name == "Selected Album"
    assert history[2].provenance == "recovered"


def test_event_identity_ignores_labels_provenance_and_equivalent_timezones() -> None:
    """The original append and its audit import resolve to one stable event."""
    choice = recorded_choice()
    imported = replace(
        choice,
        artist_name="Renamed",
        lastfm_artist="Different label",
        provenance="audit",
        chosen_at=NOW.astimezone(timezone(timedelta(hours=2))),
    )
    assert choice_identity(imported) == choice_identity(choice)
    assert choice_identity(replace(choice, artist_id="another")) != choice_identity(
        choice
    )


def test_empty_history_uses_absence_of_records_labels() -> None:
    """Unavailable past evidence is not described as a never-chosen mode."""
    history = previous_modes(ChoiceLedger(), "artist")
    assert len(history) == 3 and all(entry.count == 0 for entry in history)
