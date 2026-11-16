"""Exercise direct named analytical use cases with concrete independent storage."""

from datetime import date
from pathlib import Path

import pytest

from spotify_manager.application.listening import get_listening_activity
from spotify_manager.application.listening import get_listening_anniversaries
from spotify_manager.application.listening import get_listening_comparison
from spotify_manager.application.listening import get_listening_discoveries
from spotify_manager.application.listening import get_listening_entity
from spotify_manager.application.listening import get_listening_eras
from spotify_manager.application.listening import get_listening_evolution
from spotify_manager.application.listening import get_listening_overview
from spotify_manager.application.listening import get_listening_rankings
from spotify_manager.application.listening import get_listening_records
from spotify_manager.application.listening import get_listening_rediscovery
from spotify_manager.application.listening_ports import ListeningEntityError
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import EntitySelection
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.domain.listening_values import RediscoveryOptions
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening import scrobble


def test_direct_use_cases_reconcile_counts_and_lifetime_scope(tmp_path: Path) -> None:
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    index = fixture.index()
    query = ListeningQuery(date(2024, 1, 1), date(2024, 7, 1), "UTC")
    overview = get_listening_overview(index, query)
    assert overview.counts.scrobbles == 7
    assert overview.counts.artists == 3 and overview.counts.tracks == 4
    assert overview.counts.albums == 3 and overview.counts.missing_album == 1
    assert overview.counts.active_days == 6
    activity = get_listening_activity(index, query)
    assert sum(item.plays for item in activity.days) == 7
    ranking = get_listening_rankings(index, query, RankingOptions())
    assert ranking.items[0].name == "Alpha" and ranking.items[0].plays == 5
    assert get_listening_evolution(index, query).series[0].counts[0] == 4
    assert get_listening_records(index, query, RecordOptions(limit=2)).total == 7
    assert get_listening_comparison(index, query).current_total == 7
    assert get_listening_discoveries(index, query).cohorts[0].artists == 1
    old = ListeningQuery(date(2024, 3, 1), date(2024, 3, 31), "UTC")
    forgotten = get_listening_rediscovery(
        index, old, RediscoveryOptions(minimum_plays=1, minimum_gap=1)
    )
    assert forgotten.total == 3
    alpha = next(item for item in forgotten.items if item.entity.name == "Alpha")
    assert alpha.entity.plays == 4


def test_detail_keeps_lifetime_firsts_and_artist_track_identity(tmp_path: Path) -> None:
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    index = fixture.index()
    query = ListeningQuery(date(2024, 7, 1), date(2024, 7, 1), "UTC")
    selection = EntitySelection("artist", listening_identity(("Alpha",)))
    result = get_listening_entity(index, query, selection)
    assert result.lifetime.plays == 5
    assert result.overview.counts.scrobbles == 1
    assert result.related.items[0].name == "Song"
    assert (
        get_listening_records(index, query, RecordOptions(selection=selection)).total
        == 1
    )
    track = EntitySelection("track", listening_identity(("Béta", "Song")))
    assert get_listening_entity(index, query, track).overview.counts.scrobbles == 0
    with pytest.raises(ListeningEntityError):
        get_listening_entity(index, query, EntitySelection("artist", "0" * 64))


def test_time_capsule_respects_artist_dates_timezone_and_published_snapshot(
    tmp_path: Path,
) -> None:
    fixture = listening_fixture(tmp_path)
    rows = [
        scrobble("2022-01-01T23:30:00", "Alpha"),
        scrobble("2022-01-02T12:00:00", "Béta"),
        scrobble("2023-01-02T12:00:00", "Alpha"),
        scrobble("2024-01-02T12:00:00", "Alpha"),
    ]
    fixture.publish(rows)
    index = fixture.index()
    revision = fixture.service.snapshot().revision
    query = ListeningQuery(
        date(2024, 1, 1), date(2024, 1, 2), artist=listening_identity(("Alpha",))
    )
    anniversaries = get_listening_anniversaries(index, query)
    assert [item.plays for item in anniversaries.days] == [1, 1]
    assert anniversaries.days[0].top_artists[0].name == "Alpha"
    eras = get_listening_eras(index, query)
    assert eras.periods[0].plays == 1 and eras.similarities == ((1.0,),)
    fixture.source.write_text("mutable working history is deliberately invalid")
    other = ListeningQuery(date(2022, 1, 1), date(2024, 1, 2), "UTC")
    assert get_listening_anniversaries(index, other).days[0].plays == 1
    assert sum(item.plays for item in get_listening_eras(index, other).periods) == 4
    assert fixture.service.snapshot().revision == revision


def test_eras_keeps_rhythm_filters_and_new_generations_do_not_reuse_old_results(
    tmp_path: Path,
) -> None:
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    old = fixture.index()
    query = ListeningQuery(date(2024, 1, 1), date(2024, 7, 1), "UTC", hour=12)
    assert sum(item.plays for item in get_listening_eras(old, query).periods) == 7
    empty = ListeningQuery(query.start, query.end, "UTC", hour=13)
    assert sum(item.plays for item in get_listening_eras(old, empty).periods) == 0
    next_root = tmp_path / "next"
    next_root.mkdir()
    replacement = listening_fixture(next_root)
    replacement.publish([scrobble("2024-01-01T13:00:00")])
    new = replacement.index()
    assert sum(item.plays for item in get_listening_eras(new, empty).periods) == 1
    assert new.metadata.snapshot != old.metadata.snapshot
