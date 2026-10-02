"""Protect original freshly suppressed and accepted Sauvignon outcomes."""

from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_selection import SauvignonResult
from spotify_manager.domain.album_selection import accepted_results
from spotify_manager.domain.album_selection import fresh_additions
from tests.support.sauvignon_run import marker
from tests.support.sauvignon_run import option
from tests.support.sauvignon_run import recommendation


def test_fresh_proposals_preserve_order() -> None:
    """Filter represented album and track identities independently, retaining order."""
    first = FirstTrack("first", "first-uri", "First")
    second = FirstTrack("second", "second-uri", "Second")
    pending = (
        (option("one"), first),
        (option("two"), second),
        (option("three"), first),
    )
    assert fresh_additions(pending, (marker("one"), marker("other", "second"))) == [
        pending[2]
    ]


def test_accepted_projection_preserves_other_outcomes() -> None:
    """Change only originally real additions excluded from accepted proposals."""
    item = recommendation()
    track = FirstTrack("first", "uri", "First")
    kept = SauvignonResult(item, option(), track, "added")
    suppressed = SauvignonResult(item, option("other"), track, "added")
    preview = SauvignonResult(item, option("other"), track, "would add")
    absent = SauvignonResult(item, None, None, "added")
    results = accepted_results((kept, suppressed, preview, absent), [(option(), track)])
    assert [result.action for result in results] == [
        "added",
        "already represented",
        "would add",
        "added",
    ]
    assert results[0] is kept
    assert results[2] is preview
    assert results[3] is absent
