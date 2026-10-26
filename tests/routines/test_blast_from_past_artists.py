"""Tests for alphabetic dormant-artist recovery."""

import json
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from functools import partial
from functools import partialmethod
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from spotify_manager.application.dormant_tracks import DormantLikedTrack
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import blast_from_past_artists
from spotify_manager.routines import new_kids
from spotify_manager.routines import release_check
from tests.support.direct_dependencies import dormant_track
from tests.support.runtime_resources import DiscardMessages
from tests.support.runtime_resources import ProgressDetails
from tests.support.runtime_resources import UnexpectedCall


def _timestamp(year: int) -> int:
    return int(
        datetime(year, 6, 15, 12, tzinfo=blast_from_past.SCROBBLE_TIMEZONE).timestamp()
        * 1000
    )


def _write_history(path: Path, artists_by_year: dict[int, tuple[str, ...]]) -> None:
    scrobbles = [
        {
            "artist": artist,
            "track": f"{artist} track",
            "album": "Album",
            "date": _timestamp(year),
        }
        for year, artists in artists_by_year.items()
        for artist in artists
    ]
    path.write_text(json.dumps({"scrobbles": scrobbles}), encoding="utf-8")


def _track(
    spotify_id: str,
    artist_id: str,
    artist: str,
    popularity: int,
) -> new_kids.CatalogTrack:
    return new_kids.CatalogTrack(
        spotify_id=spotify_id,
        uri=f"spotify:track:{spotify_id}",
        name=f"Track {spotify_id}",
        disc_number=1,
        track_number=1,
        primary_artist_id=artist_id,
        primary_artist_name=artist,
        popularity=popularity,
    )


def test_dormant_artists_requires_every_prior_year_and_excludes_current_year(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    _write_history(
        path,
        {
            2021: ("Outside",),
            2022: ("Always", "Always", "Missing 2024", "Current too"),
            2023: ("Always", "Missing 2024", "Current too"),
            2024: ("Always", "Current too"),
            2025: ("Always", "Missing 2024", "Current too", "Only once"),
            2026: ("Current too",),
        },
    )

    artists = blast_from_past_artists.dormant_artists(
        path,
        today=date(2026, 8, 27),
    )

    assert [(artist.name, artist.scrobbles) for artist in artists] == [("Always", 5)]


def test_dormant_artists_rolls_the_four_year_intersection_forward(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    _write_history(
        path,
        {
            2022: ("Too old",),
            2023: ("Returns in 2027", "Current in 2027"),
            2024: ("Returns in 2027", "Current in 2027", "Missing 2025"),
            2025: ("Returns in 2027", "Current in 2027"),
            2026: ("Returns in 2027", "Current in 2027", "Missing 2025"),
            2027: ("Current in 2027",),
        },
    )

    artists = blast_from_past_artists.dormant_artists(
        path,
        today=date(2027, 1, 2),
    )

    assert [(artist.name, artist.scrobbles) for artist in artists] == [
        ("Returns in 2027", 4)
    ]


def test_most_popular_liked_track_prefers_liked_spotify_top_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most popular liked track prefers liked spotify top track.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    tracks = (
        _track("popular-unliked", "artist-id", "Artist", 90),
        _track("popular-liked", "artist-id", "Artist", 80),
        _track("less-popular-liked", "artist-id", "Artist", 70),
    )

    monkeypatch.setattr(
        new_kids,
        "load_top_track_data",
        Mock(return_value=({}, tracks)),
    )
    monkeypatch.setattr(
        blast_from_past_artists,
        "_catalog_tracks",
        UnexpectedCall("catalog fallback should not be needed"),
    )

    selected = blast_from_past_artists.most_popular_liked_track(
        LikedTopTracksSpotify(),  # type: ignore[arg-type]
        "artist-id",
        NoRetry(),
    )

    assert selected == tracks[1]


def test_most_popular_liked_track_falls_back_to_full_primary_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most popular liked track falls back to full primary catalog.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    top_track = _track("top-unliked", "artist-id", "Artist", 90)
    lower = _track("catalog-lower", "artist-id", "Artist", 1)
    higher = _track("catalog-higher", "artist-id", "Artist", 1)
    secondary = _track("secondary", "other-id", "Other", 99)

    monkeypatch.setattr(
        new_kids,
        "load_top_track_data",
        Mock(return_value=({}, (top_track,))),
    )
    monkeypatch.setattr(
        new_kids,
        "load_ranked_catalog",
        Mock(return_value=(object(), object())),
    )
    monkeypatch.setattr(
        new_kids,
        "load_release_tracks",
        Mock(return_value=(lower, higher, secondary, higher)),
    )

    selected = blast_from_past_artists.most_popular_liked_track(
        LikedCatalogSpotify(),  # type: ignore[arg-type]
        "artist-id",
        NoRetry(),
    )

    assert selected is not None
    assert selected.spotify_id == "catalog-higher"
    assert selected.popularity == 73


def test_spotify_response_validation_is_strict() -> None:
    """Spotify response validation is strict."""
    track = _track("track", "artist", "Artist", 1)

    with pytest.raises(
        blast_from_past_artists.BlastFromPastArtistsError,
        match="Liked Songs statuses",
    ):
        blast_from_past_artists._liked_statuses(  # noqa: SLF001
            InvalidSpotify(),  # type: ignore[arg-type]
            (track,),
            NoRetry(),
        )
    with pytest.raises(
        blast_from_past_artists.BlastFromPastArtistsError,
        match="liked-track details",
    ):
        blast_from_past_artists._track_popularities(  # noqa: SLF001
            InvalidSpotify(),  # type: ignore[arg-type]
            (track,),
            NoRetry(),
        )


def test_spotify_artist_requires_one_exact_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spotify artist requires one exact mapping.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    artist = blast_from_past_artists.DormantArtist("artist", "Artist", 4)
    exact = release_check.SpotifyArtistCandidate(
        spotify_id="exact",
        name="Artist",
        uri="spotify:artist:exact",
        popularity=50,
        followers=100,
        search_rank=1,
        exact_name=True,
    )
    inexact = release_check.SpotifyArtistCandidate(
        spotify_id="inexact",
        name="Artist Band",
        uri="spotify:artist:inexact",
        popularity=40,
        followers=50,
        search_rank=2,
        exact_name=False,
    )
    monkeypatch.setattr(
        release_check,
        "search_spotify_artists",
        Mock(return_value=(exact, inexact)),
    )

    selected = blast_from_past_artists._spotify_artist(  # noqa: SLF001
        object(),  # type: ignore[arg-type]
        artist,
        1,
        NoRetry(),
    )
    assert selected == exact

    monkeypatch.setattr(
        release_check,
        "search_spotify_artists",
        Mock(return_value=(exact, exact)),
    )
    assert (
        blast_from_past_artists._spotify_artist(  # noqa: SLF001
            object(),  # type: ignore[arg-type]
            artist,
            1,
            NoRetry(),
        )
        is None
    )


def test_fill_reports_unmapped_unliked_and_duplicate_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fill reports unmapped unliked and duplicate candidates.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    candidates = tuple(
        blast_from_past_artists.DormantArtist(name.casefold(), name, 1)
        for name in ("Alpha", "Beta", "Charlie", "Delta")
    )
    candidate_by_key = {candidate.key: candidate for candidate in candidates}
    progress: list[str] = []
    added: list[str] = []
    monkeypatch.setattr(
        blast_from_past_artists, "dormant_artists", Mock(return_value=candidates)
    )
    monkeypatch.setattr(
        blast_from_past,
        "load_playlist_state",
        Mock(
            return_value=blast_from_past.PlaylistState(
                total_items=1, track_ids=frozenset({"duplicate"})
            )
        ),
    )
    scenario = FillReportsUnmappedUnlikedAndDuplicateCandidatesScenario(
        candidate_by_key=candidate_by_key
    )
    monkeypatch.setattr(blast_from_past_artists, "_spotify_artist", scenario.mapping)
    monkeypatch.setattr(
        DormantLikedTrack, "run", partialmethod(dormant_track, scenario.liked_track)
    )
    monkeypatch.setattr(
        blast_from_past,
        "add_spotify_matches",
        partial(_record_added_tracks, added),
    )
    summary = blast_from_past_artists.add_dormant_artists_to_blast_from_past(
        object(),
        "blast",
        count=1,
        today=date(2026, 8, 27),
        echo=DiscardMessages(),
        progress_callback=ProgressDetails(progress),
    )
    assert [result.action for result in summary.results] == [
        "no mapping",
        "no liked track",
        "added",
    ]
    assert added == ["selected"]
    assert progress[-1] == "Dormant-artist recovery complete"


def test_fill_rejects_zero_count() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        blast_from_past_artists.add_dormant_artists_to_blast_from_past(
            object(),  # type: ignore[arg-type]
            "blast",
            count=0,
        )


def test_dormant_artist_fill_skips_represented_and_appends_five(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.json"
    _write_history(
        path,
        {
            year: ("Alpha", "Beta", "Charlie", "Delta", "Echo", "Foxtrot")
            for year in (2022, 2023, 2024, 2025)
        },
    )
    posted: list[str] = []

    class FakeSpotify:
        @staticmethod
        def _get(_path: str, limit: int, offset: int) -> dict[str, object]:
            items = (
                [
                    {
                        "item": {
                            "id": "existing",
                            "name": "Existing",
                            "artists": [{"name": "Alpha"}],
                        }
                    }
                ]
                if offset == 0
                else []
            )
            return {"items": items, "total": 1, "next": None}

        @staticmethod
        def _post(_path: str, payload: dict[str, object]) -> dict[str, str]:
            posted.extend(payload["uris"])  # type: ignore[arg-type]
            return {"snapshot_id": "snapshot"}

    def mapped(
        _sp: object,
        artist: blast_from_past_artists.DormantArtist,
        _rank: int,
        _retry: object,
    ) -> release_check.SpotifyArtistCandidate:
        return release_check.SpotifyArtistCandidate(
            spotify_id=f"id-{artist.key}",
            name=artist.name,
            uri=f"spotify:artist:id-{artist.key}",
            popularity=50,
            followers=100,
            search_rank=1,
            exact_name=True,
        )

    monkeypatch.setattr(blast_from_past_artists, "_spotify_artist", mapped)
    monkeypatch.setattr(
        DormantLikedTrack,
        "run",
        partialmethod(
            dormant_track,
            lambda _sp, artist_id, _retry: _track(
                f"track-{artist_id}",
                artist_id,
                artist_id.removeprefix("id-").title(),
                75,
            ),
        ),
    )

    summary = blast_from_past_artists.add_dormant_artists_to_blast_from_past(
        FakeSpotify(),  # type: ignore[arg-type]
        "blast",
        path=path,
        today=date(2026, 8, 27),
    )

    assert summary.history_years == (2022, 2023, 2024, 2025)
    assert summary.candidate_count == 6
    assert summary.represented_count == 1
    assert summary.added == 5
    assert summary.playlist_length_before == 1
    assert summary.playlist_length_after == 6
    assert [result.artist for result in summary.results] == [
        "Beta",
        "Charlie",
        "Delta",
        "Echo",
        "Foxtrot",
    ]
    assert posted == [
        "spotify:track:track-id-beta",
        "spotify:track:track-id-charlie",
        "spotify:track:track-id-delta",
        "spotify:track:track-id-echo",
        "spotify:track:track-id-foxtrot",
    ]

    posted.clear()
    preview = blast_from_past_artists.add_dormant_artists_to_blast_from_past(
        FakeSpotify(),  # type: ignore[arg-type]
        "blast",
        path=path,
        today=date(2026, 8, 27),
        dry_run=True,
    )

    assert preview.added == 5
    assert preview.playlist_length_after == preview.playlist_length_before
    assert posted == []


class LikedTopTracksSpotify:
    """Retain the original likedtoptracks spotify boundary fixture."""

    @staticmethod
    def current_user_saved_tracks_contains(ids: list[str]) -> list[bool]:
        """Retain the original current user saved tracks contains fixture observation.

        Args:
            ids: Original ids value.

        Returns:
            Original fixture result.
        """
        return [spotify_id != "popular-unliked" for spotify_id in ids]


class LikedCatalogSpotify:
    """Retain the original likedcatalog spotify boundary fixture."""

    liked = {"catalog-lower", "catalog-higher"}

    def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
        """Retain the original current user saved tracks contains fixture observation.

        Args:
            ids: Original ids value.

        Returns:
            Original fixture result.
        """
        return [spotify_id in self.liked for spotify_id in ids]

    @staticmethod
    def tracks(ids: list[str]) -> dict[str, object]:
        """Retain the original tracks fixture observation.

        Args:
            ids: Original ids value.

        Returns:
            Original fixture result.
        """
        assert ids == ["catalog-lower", "catalog-higher"]
        return {
            "tracks": [
                None,
                {"id": "unknown", "popularity": 100},
                {"id": "catalog-lower", "popularity": 42},
                {"id": "catalog-higher", "popularity": 73},
            ]
        }


class InvalidSpotify:
    """Retain the original invalid spotify boundary fixture."""

    @staticmethod
    def current_user_saved_tracks_contains(_ids: list[str]) -> dict[str, object]:
        """Return a malformed membership response.

        Args:
            _ids: Requested track identities.

        Returns:
            Invalid membership payload.
        """
        return {}

    @staticmethod
    def tracks(_ids: list[str]) -> dict[str, object]:
        """Return a malformed track response.

        Args:
            _ids: Requested track identities.

        Returns:
            Invalid track payload.
        """
        return {"tracks": "invalid"}


@dataclass
class FillReportsUnmappedUnlikedAndDuplicateCandidatesScenario:
    """Retain the original fill reports unmapped unliked and duplicate candidates
    fixture.

    Args:
        candidate_by_key: Original candidate by key observation or resource.
    """

    candidate_by_key: Any

    def mapping(
        self,
        _sp: object,
        artist: blast_from_past_artists.DormantArtist,
        _rank: int,
        _retry: object,
    ) -> release_check.SpotifyArtistCandidate | None:
        """Execute the original mapping mock boundary.

        Args:
            _sp: Original external mock argument.
            artist: Original external mock argument.
            _rank: Original external mock argument.
            _retry: Original external mock argument.

        Returns:
            Original fixture result.
        """
        if artist.key == "alpha":
            return None
        return release_check.SpotifyArtistCandidate(
            spotify_id=artist.key,
            name=artist.name,
            uri=f"spotify:artist:{artist.key}",
            popularity=1,
            followers=1,
            search_rank=1,
            exact_name=True,
        )

    def liked_track(
        self, _sp: object, artist_id: str, _retry: object
    ) -> new_kids.CatalogTrack | None:
        """Execute the original liked track mock boundary.

        Args:
            _sp: Original external mock argument.
            artist_id: Original external mock argument.
            _retry: Original external mock argument.

        Returns:
            Original fixture result.
        """
        if artist_id == "beta":
            return None
        spotify_id = "duplicate" if artist_id == "charlie" else "selected"
        artist = self.candidate_by_key[artist_id]
        return _track(spotify_id, artist_id, artist.name, 55)


def _record_added_tracks(
    added: list[str],
    spotify: object,
    playlist: str,
    matches: tuple[blast_from_past.SpotifyTrackMatch, ...],
    *args: object,
) -> None:
    added.extend(match.spotify_id for match in matches)
