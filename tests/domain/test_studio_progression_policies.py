"""Pure studio chronology grouping and edition track mapping."""

from dataclasses import replace

from spotify_manager.domain.slow_listening import date_groups
from spotify_manager.domain.slow_listening import track_index
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


def test_track_mapping_prefers_id_then_unique_title() -> None:
    """Exact IDs win over ambiguous titles; title fallback requires a single match."""
    release = studio_release("r", "Release")
    source = playlist_track("source", release)
    first = release_track("first")
    same_title = replace(first, name=source.name)
    exact = replace(first, spotify_id="source")
    assert track_index((same_title, exact), source) == 1
    assert track_index((first, same_title), source) == 1
    assert track_index((same_title, same_title), source) is None
    assert track_index((first,), source) is None
    assert track_index((), source) is None


def test_edition_suffixes_do_not_prevent_unique_title_mapping() -> None:
    """Track mapping retains the shared edition-neutral title policy."""
    source = playlist_track("source", studio_release("r", "Release"))
    track = replace(release_track("other"), name="source (Remastered)")
    assert track_index((track,), source) == 0


def test_date_groups_sort_dates_but_keep_catalog_order_inside_ties() -> None:
    """Date grouping leaves operator ordering undecided."""
    first = studio_release("first", "First", "2020")
    second = studio_release("second", "Second", "2021")
    tied = replace(first, spotify_id="tied")
    assert date_groups((second, tied, first)) == ((tied, first), (second,))
    assert date_groups(()) == ()
