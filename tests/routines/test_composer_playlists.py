"""Tests for conservative owned composer-playlist matching."""

from spotify_manager.routines import composer_playlists


def playlist(
    spotify_id: str,
    name: str,
) -> composer_playlists.OwnedPlaylist:
    """Build one compact owned-playlist candidate."""
    return composer_playlists.OwnedPlaylist(spotify_id, name, 10)


def test_generic_band_suffix_is_not_treated_as_a_personal_surname() -> None:
    """The .357 String Band must not match an unrelated Band playlist."""
    candidates = composer_playlists.composer_playlist_candidates(
        "The .357 String Band",
        (
            playlist(
                "dave",
                "2010.10.10_4 - Dave Matthews Band Setlist - Fazenda Maeda",
            ),
        ),
        excluded_playlist_ids=frozenset(),
    )

    assert candidates == ()


def test_personal_surname_still_matches_a_composer_playlist() -> None:
    """Meaningful composer surnames retain the convenient short match."""
    bach = playlist("bach", "Complete chronological Bach works")

    candidates = composer_playlists.composer_playlist_candidates(
        "Johann Sebastian Bach",
        (bach,),
        excluded_playlist_ids=frozenset(),
    )

    assert candidates == (bach,)


def test_full_name_match_does_not_depend_on_surname_fallback() -> None:
    """An exact token sequence remains valid even for an ensemble-style name."""
    string_band = playlist("string-band", "The .357 String Band chronology")

    candidates = composer_playlists.composer_playlist_candidates(
        "The .357 String Band",
        (string_band,),
        excluded_playlist_ids=frozenset(),
    )

    assert candidates == (string_band,)
