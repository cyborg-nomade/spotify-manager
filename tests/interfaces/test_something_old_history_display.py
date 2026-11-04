"""Keep history labels factual while the current mode remains an explicit choice."""

from datetime import timedelta

from spotify_manager.domain.something_old_history import PreviousMode
from spotify_manager.interfaces.presenters.something_old_history import (
    latest_choice_label,
)
from spotify_manager.interfaces.presenters.something_old_history import (
    mode_history_label,
)
from tests.support.queue_neighbors import NOW


def test_unrecorded_modes_are_not_described_as_never_chosen() -> None:
    """Incomplete historical evidence must not claim an option was never used."""
    assert mode_history_label(None) == "No recorded use"
    assert mode_history_label(PreviousMode("album", 0)) == "No recorded use"
    assert latest_choice_label(()) == "No recorded choices for this Spotify artist."


def test_labels_include_counts_dates_album_and_recovery_provenance() -> None:
    """Per-option evidence includes enough detail to judge the past choice."""
    album = PreviousMode("album", 3, NOW, "Selected Album", "recovered")
    label = mode_history_label(album)
    assert "Chosen 3 times" in label and NOW.date().isoformat() in label
    assert "Selected Album" in label and "recovered after interruption" in label
    audit = PreviousMode("lastfm_top_tracks", 1, NOW, provenance="audit")
    assert "imported audit" in mode_history_label(audit)
    assert "Chosen 1 time ·" in mode_history_label(audit)


def test_latest_choice_uses_dates_across_all_modes() -> None:
    """The most recent mode is not inferred from option order or usage count."""
    lastfm = PreviousMode("lastfm_top_tracks", 1, NOW + timedelta(days=2))
    popular = PreviousMode("spotify_top_tracks", 10, NOW)
    album = PreviousMode("album", 2, NOW + timedelta(days=1))
    assert "Last.fm top tracks" in latest_choice_label((lastfm, popular, album))
