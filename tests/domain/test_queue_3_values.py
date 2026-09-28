"""Queue 3 adapters preserve track credits and chronological edition facts."""

from dataclasses import replace

from spotify_manager.domain.queue_3 import ranked_release
from spotify_manager.domain.queue_3 import source_release
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


def test_source_release_uses_marker_credit_and_original_release_date() -> None:
    """Source placeholders keep their conservative unsaved/plain defaults."""
    release = studio_release("id", "Album (Deluxe Edition)", "1999")
    source = replace(playlist_track("track", release), primary_artist_id="performer")
    adapted = source_release(source)
    assert adapted.primary_artist_id == "performer"
    assert adapted.chronology_date == adapted.release_date == "1999"
    assert adapted.identity == "album" and adapted.edition_rank == 0
    assert adapted.plain is True and adapted.saved is False


def test_library_adaptation_preserves_selected_edition_without_discovery_ranking() -> (
    None
):
    """Library decisions retain observed membership and the selected title identity."""
    release = replace(studio_release("id", "Album"), saved=True, plain=False)
    adapted = ranked_release(release)
    assert adapted.spotify_id == "id" and adapted.identity == release.identity
    assert adapted.saved is True and adapted.plain is False
    assert adapted.popularity is None and adapted.top_track_rank is None
    assert adapted.tier == 0
