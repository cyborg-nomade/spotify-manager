"""Discovery release classification and composer mapping keep original precedence."""

from dataclasses import replace

import pytest

from spotify_manager.domain.discovery_progression import composer_release
from spotify_manager.domain.discovery_progression import composer_source_index
from spotify_manager.domain.discovery_progression import composer_track
from spotify_manager.domain.discovery_progression import release_kind
from spotify_manager.domain.discovery_progression import source_release
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))


@pytest.mark.parametrize(
    "kind,count,title,expected",
    [
        ("compilation", 12, "Live Album", ("Compilation", 3)),
        ("album", 12, "Live Album", ("Live", 2)),
        ("ALBUM", 12, "Album", ("Album", 0)),
        ("ep", 2, "Album", ("EP", 0)),
        ("single", 4, "Album", ("EP", 0)),
        ("single", 3, "Album", ("Single", 1)),
        (None, 12, "Album", ("Single", 1)),
        (" album ", 12, "Album", ("Single", 1)),
    ],
)
def test_release_classification_keeps_original_precedence(
    kind: object, count: int, title: str, expected: tuple[str, int]
) -> None:
    """Compilations override live titles; unknown classifications remain singles.

    Args:
        kind: Raw classification.
        count: Observed track count.
        title: Observed release name.
        expected: Existing display kind and tier.
    """
    assert release_kind(kind, count, title) == expected


def test_source_release_uses_track_credit_and_logical_composer_overrides() -> None:
    """Source adaptation retains title classification while replacing only credits."""
    decorated = replace(
        SOURCE.release, name="Album (Deluxe)", primary_artist_id="album-credit"
    )
    source = replace(SOURCE, release=decorated)
    release = source_release(source)
    assert release.primary_artist_id == SOURCE.primary_artist_id
    assert release.identity == "album" and not release.plain and not release.saved
    assert release.popularity is release.top_track_rank is None
    composer = composer_release(source, "composer", "Composer")
    assert composer == replace(
        release, primary_artist_id="composer", primary_artist_name="Composer"
    )
    marker = composer_track(source, "composer", "Composer")
    assert (
        marker.spotify_id,
        marker.primary_artist_id,
        marker.disc_number,
        marker.track_number,
    ) == ("source", "composer", 1, 1)


def test_composer_mapping_prefers_first_id_over_ambiguous_normalized_titles() -> None:
    """ID duplicates choose their first position; title duplicates are ambiguous."""
    other = replace(SOURCE, spotify_id="other", name="SOURCE!")
    assert composer_source_index(SOURCE, (other, SOURCE, SOURCE)) == 1
    assert composer_source_index(SOURCE, (other,)) == 0
    assert composer_source_index(SOURCE, (other, other)) is None
    assert composer_source_index(SOURCE, (replace(other, name="Different"),)) is None
    assert composer_source_index(SOURCE, ()) is None
