"""Tests for Last.fm-style Sauvignon album recommendations."""

import json
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from spotify_manager.application import sauvignon_run as sauvignon_integration
from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.infrastructure.legacy.sauvignon import LegacySauvignon
from spotify_manager.interfaces.requests.sauvignon import SauvignonCallbacks
from spotify_manager.interfaces.requests.sauvignon import SauvignonOptions
from spotify_manager.interfaces.requests.sauvignon import SauvignonResources
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art
from spotify_manager.routines import sauvignon
from tests.support.framework_stubs import empty_object
from tests.support.runtime_resources import Answer


def track_candidate(
    artist: str = "New Artist",
    track: str = "New Track",
    score: float = 1.0,
) -> found_art.FoundArtCandidate:
    """Return one compact Last.fm track recommendation."""
    return found_art.FoundArtCandidate(
        artist=artist,
        track=track,
        key=found_art.canonical_track_key(artist, track),
        score=score,
        best_match=0.95,
        supporting_seeds=("Seed Artist - Seed Track",),
    )


def album_option(
    *,
    spotify_id: str = "album-id",
    artist: str = "New Artist",
    album: str = "New Album",
    release_date: str = "2024-01-01",
    total_tracks: int = 10,
    search_rank: int = 1,
) -> sauvignon.SpotifyAlbumOption:
    """Return one eligible Spotify album option."""
    return sauvignon.SpotifyAlbumOption(
        spotify_id=spotify_id,
        uri=f"spotify:album:{spotify_id}",
        artist_id=f"{artist}-id",
        artist=artist,
        album=album,
        release_type="Album",
        release_date=release_date,
        total_tracks=total_tracks,
        source_track="New Track",
        source_track_id=f"track-{spotify_id}",
        search_rank=search_rank,
        track_similarity=1.0,
        track_popularity=50,
    )


def recommendation(
    *,
    artist: str = "New Artist",
    album: str = "New Album",
    options: tuple[sauvignon.SpotifyAlbumOption, ...] | None = None,
) -> sauvignon.AlbumRecommendation:
    """Return one ranked album recommendation."""
    return sauvignon.AlbumRecommendation(
        artist=artist,
        album=album,
        key=sauvignon.canonical_album_key(artist, album),
        score=2.0,
        best_match=0.95,
        supporting_tracks=(f"{artist} - New Track",),
        options=options or (album_option(artist=artist, album=album),),
        base_rank=1,
        weekly_rank=0.9,
    )


def raw_spotify_track(
    *,
    artist: str = "New Artist",
    artist_id: str = "artist-id",
    track: str = "New Track",
    track_id: str = "track-id",
    album: str = "New Album",
    album_id: str = "album-id",
    album_type: str = "album",
    total_tracks: int = 10,
    album_artist: str | None = None,
) -> dict[str, object]:
    """Return a Spotify search result with complete album metadata."""
    album_artist_name = album_artist or artist
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": track,
        "artists": [{"id": artist_id, "name": artist}],
        "album": {
            "id": album_id,
            "uri": f"spotify:album:{album_id}",
            "name": album,
            "artists": [{"id": f"{album_artist_name}-id", "name": album_artist_name}],
            "album_type": album_type,
            "release_date": "2024-01-01",
            "total_tracks": total_tracks,
        },
        "popularity": 55,
    }


class FakeSpotify:
    """Minimal Spotify source for album searches and playlist writes."""

    def __init__(self) -> None:
        self.search_items: list[dict[str, object]] = []
        self.album_items: dict[str, list[dict[str, object]]] = {}
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def search(self, **_kwargs: object) -> dict[str, object]:
        return {"tracks": {"items": self.search_items}}

    async def album_tracks(
        self,
        album_id: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        assert limit == 50
        assert offset == 0
        return {"items": self.album_items.get(album_id, [])}

    async def _post(self, path: str, payload: dict[str, object]) -> None:
        self.posts.append((path, payload))


def immediate(operation: object, _description: str) -> object:
    """Execute one retry-wrapped callable immediately."""
    assert callable(operation)
    return operation()


def test_configuration_and_album_identity_rules() -> None:
    assert sauvignon.parse_playlist_id("spotify:playlist:sauv") == "sauv"
    with pytest.raises(sauvignon.SauvignonConfigError, match="not configured"):
        sauvignon.parse_playlist_id(None)

    assert sauvignon.canonical_album_key(
        "Beyoncé",
        "Album (Deluxe Edition)",
    ) == sauvignon.canonical_album_key("Beyonce", "Album")
    history = [
        blast_from_past.Scrobble("Track", "Artist", "Album", 1),
        blast_from_past.Scrobble("Loose Track", "Artist", "", 2),
    ]
    assert sauvignon.heard_album_keys(history) == {
        sauvignon.canonical_album_key("Artist", "Album")
    }


async def test_previous_additions_are_loaded_and_corruption_is_not_masked(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "sauvignon.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "action": "added",
                        "album": {"artist": "Artist", "album": "Album"},
                    },
                    {
                        "action": "would add",
                        "album": {"artist": "Other", "album": "Dry"},
                    },
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert (sauvignon.previously_added_album_keys(log_path)) == {
        sauvignon.canonical_album_key("Artist", "Album")
    }
    assert (sauvignon.previously_added_album_keys(tmp_path / "missing")) == set()

    log_path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(sauvignon.SauvignonStateError, match="line 1"):
        (sauvignon.previously_added_album_keys(log_path))


@pytest.mark.parametrize(
    ("changes", "eligible"),
    [
        ({}, True),
        ({"album_type": "single", "total_tracks": 1}, False),
        ({"album_type": "compilation"}, False),
        ({"album": "New Album (Live)"}, False),
        ({"album": "New Album Deluxe Edition"}, False),
        ({"album_artist": "Different Artist"}, False),
        ({"artist": "Featured Artist"}, False),
    ],
)
def test_album_option_keeps_only_plain_primary_artist_albums_and_eps(
    changes: dict[str, object],
    eligible: bool,
) -> None:
    raw = raw_spotify_track(**changes)  # type: ignore[arg-type]
    parsed = sauvignon._album_option(raw, track_candidate(), 1)
    assert (parsed is not None) is eligible

    if parsed is not None:
        assert parsed.album == "New Album"
        assert parsed.release_type == "Album"


def test_album_option_accepts_spotify_eps() -> None:
    parsed = sauvignon._album_option(
        raw_spotify_track(album_type="single", total_tracks=4),
        track_candidate(),
        1,
    )
    assert parsed is not None
    assert parsed.release_type == "EP"


async def test_search_candidate_albums_deduplicates_and_validates_responses() -> None:
    """Search candidate albums deduplicates and validates responses."""
    spotify = FakeSpotify()
    spotify.search_items = [raw_spotify_track(), raw_spotify_track()]
    options = sauvignon.search_candidate_albums(
        spotify,
        track_candidate(),
        NoRetry(),
    )
    assert [option.spotify_id for option in options] == ["album-id"]

    spotify.search = AsyncMock(side_effect=empty_object)  # type: ignore[method-assign]
    with pytest.raises(sauvignon.SauvignonSpotifyError, match="invalid search"):
        (sauvignon.search_candidate_albums(spotify, track_candidate(), NoRetry()))


async def test_album_recommendations_aggregate_evidence_and_apply_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Album recommendations aggregate evidence and apply exclusions.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    candidates = (
        track_candidate(track="First", score=2.0),
        track_candidate(track="Second", score=1.0),
        track_candidate(artist="Heard", track="Third", score=4.0),
    )
    options = {
        "First": (album_option(spotify_id="album-a"),),
        "Second": (
            album_option(spotify_id="album-a", search_rank=2),
            album_option(spotify_id="album-b", album="Second Album"),
        ),
        "Third": (album_option(artist="Heard", album="Known Album"),),
    }
    monkeypatch.setattr(
        sauvignon,
        "async_search_candidate_albums",
        AsyncMock(side_effect=partial(_candidate_options, options)),
    )

    ranked = sauvignon.gather_album_recommendations(
        object(),  # type: ignore[arg-type]
        candidates,
        {sauvignon.canonical_album_key("Heard", "Known Album")},
        {"album-b"},
        maximum_candidates=3,
        week_start=date(2026, 8, 7),
        retry_call=NoRetry(),
    )

    assert len(ranked) == 1
    assert ranked[0].key == sauvignon.canonical_album_key(
        "New Artist",
        "New Album",
    )
    assert ranked[0].score == pytest.approx((2.0 + 1.0) * 1.15)
    assert ranked[0].supporting_tracks == (
        "New Artist - First",
        "New Artist - Second",
    )
    assert ranked[0].base_rank == 1
    assert ranked[0].weekly_rank > 0


async def test_album_choice_prompts_only_for_materially_different_editions() -> None:
    """Album choice prompts only for materially different editions."""
    same = recommendation(
        options=(album_option(spotify_id="one"), album_option(spotify_id="two"))
    )
    called = False
    scenario = AlbumChoicePromptsOnlyForMateriallyDifferentEditionsScenario(
        called=called
    )
    assert (sauvignon.choose_album_option(same, scenario)).spotify_id == "one"
    assert scenario.called is False
    ambiguous = recommendation(
        options=(
            album_option(spotify_id="one"),
            album_option(spotify_id="two", release_date="2025-01-01"),
        )
    )
    selected = sauvignon.choose_album_option(ambiguous, Answer("two"))
    assert isinstance(selected, sauvignon.SpotifyAlbumOption)
    assert selected.spotify_id == "two"
    assert (sauvignon.choose_album_option(ambiguous, None)) == "skip"
    assert (
        sauvignon.choose_album_option(ambiguous, Answer(sauvignon.CHOICE_SKIP))
    ) == "skip"
    assert (
        sauvignon.choose_album_option(ambiguous, Answer(sauvignon.CHOICE_QUIT))
    ) == "quit"


async def test_first_track_uses_spotify_order_and_reports_invalid_data() -> None:
    """First track uses spotify order and reports invalid data."""
    spotify = FakeSpotify()
    spotify.album_items["album-id"] = [
        {"id": None},
        {"id": "first", "uri": "spotify:track:first", "name": "Opening"},
        {"id": "second", "uri": "spotify:track:second", "name": "Next"},
    ]
    selected = sauvignon.load_first_track(spotify, album_option(), NoRetry())
    assert selected.name == "Opening"

    spotify.album_tracks = AsyncMock(side_effect=empty_object)  # type: ignore[method-assign]
    with pytest.raises(sauvignon.SauvignonSpotifyError, match="invalid tracks"):
        (sauvignon.load_first_track(spotify, album_option(), NoRetry()))

    spotify.album_tracks = (  # type: ignore[method-assign]
        AsyncMock(return_value={"items": [{"id": None}]})
    )
    with pytest.raises(sauvignon.SauvignonSpotifyError, match="No playable"):
        (sauvignon.load_first_track(spotify, album_option(), NoRetry()))


async def test_fill_sauvignon_adds_first_track_and_logs_completed_album(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fill sauvignon adds first track and logs completed album.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    seed = found_art.FoundArtSeed(
        artist="Seed",
        track="Seed Track",
        key=("seed", "seed track"),
        source="recent",
        play_count=5,
        source_play_count=5,
        weight=1.0,
    )
    candidate = track_candidate()
    album = album_option()
    album_recommendation = recommendation(options=(album,))
    first = sauvignon.FirstTrack("first", "spotify:track:first", "Opening")
    scrobbles = [blast_from_past.Scrobble("Known", "Known Artist", "Known Album", 1)]
    monkeypatch.setattr(
        LegacySauvignon,
        "refresh",
        AsyncMock(side_effect=Mock(return_value=(scrobbles, 2))),
    )
    monkeypatch.setattr(
        sauvignon_integration,
        "aggregate_track_history",
        Mock(
            return_value=(
                found_art.TrackHistory("Seed", "Seed Track", seed.key, 5, 5, 5, 1),
            )
        ),
    )
    monkeypatch.setattr(RecommendationSeeds, "run", Mock(return_value=(seed,)))
    monkeypatch.setattr(
        CandidateGathering,
        "run",
        AsyncMock(side_effect=Mock(return_value=(candidate,))),
    )
    monkeypatch.setattr(
        sauvignon.new_wine,
        "async_load_playlist_tracks",
        AsyncMock(side_effect=Mock(return_value=())),
    )
    monkeypatch.setattr(
        AlbumGathering,
        "run",
        AsyncMock(side_effect=Mock(return_value=(album_recommendation,))),
    )
    monkeypatch.setattr(
        sauvignon,
        "async_load_first_track",
        AsyncMock(side_effect=Mock(return_value=first)),
    )

    summary = sauvignon.fill_sauvignon_from_lastfm(
        spotify,
        object(),
        SauvignonOptions(playlist_id="sauvignon", count=1, max_playlist_length=None),
        SauvignonCallbacks(choice_reader=None, retry_call=NoRetry()),
        SauvignonResources(
            export_path=tmp_path / "history.json",
            recent_path=tmp_path / "recent.jsonl",
            log_path=tmp_path / "sauvignon.jsonl",
        ),
    )

    assert summary.selected == 1
    assert summary.playlist_length_after == 1
    assert summary.live_scrobbles_added == 2
    assert spotify.posts == [
        (
            "playlists/sauvignon/items",
            {"uris": ["spotify:track:first"]},
        )
    ]
    assert (sauvignon.previously_added_album_keys(tmp_path / "sauvignon.jsonl")) == {
        album_recommendation.key
    }


async def test_fill_sauvignon_dry_run_enforces_one_album_per_artist_and_can_pause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fill sauvignon dry run enforces one album per artist and can pause.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    first_option = album_option(spotify_id="one", album="First Album")
    second_option = album_option(spotify_id="two", album="Second Album")
    third_option = album_option(
        spotify_id="three",
        artist="Other Artist",
        album="Third Album",
    )
    recommendations = (
        recommendation(album="First Album", options=(first_option,)),
        recommendation(album="Second Album", options=(second_option,)),
        recommendation(
            artist="Other Artist",
            album="Third Album",
            options=(
                third_option,
                album_option(
                    spotify_id="four",
                    artist="Other Artist",
                    album="Third Album",
                    release_date="2025-01-01",
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        LegacySauvignon,
        "refresh",
        AsyncMock(
            side_effect=Mock(
                return_value=(
                    [blast_from_past.Scrobble("Seed", "Seed", "Seed Album", 1)],
                    0,
                )
            )
        ),
    )
    monkeypatch.setattr(
        sauvignon_integration,
        "aggregate_track_history",
        Mock(
            return_value=(
                found_art.TrackHistory("Seed", "Seed", ("seed", "seed"), 1, 1, 1, 1),
            )
        ),
    )
    monkeypatch.setattr(
        RecommendationSeeds,
        "run",
        Mock(
            return_value=(
                found_art.FoundArtSeed(
                    "Seed", "Seed", ("seed", "seed"), "recent", 1, 1, 1.0
                ),
            )
        ),
    )
    monkeypatch.setattr(
        CandidateGathering,
        "run",
        AsyncMock(side_effect=Mock(return_value=(track_candidate(),))),
    )
    monkeypatch.setattr(
        sauvignon.new_wine,
        "async_load_playlist_tracks",
        AsyncMock(side_effect=Mock(return_value=())),
    )
    monkeypatch.setattr(
        AlbumGathering, "run", AsyncMock(side_effect=Mock(return_value=recommendations))
    )
    monkeypatch.setattr(
        sauvignon,
        "async_load_first_track",
        AsyncMock(side_effect=_fixture_first_track),
    )

    summary = sauvignon.fill_sauvignon_from_lastfm(
        spotify,
        object(),
        SauvignonOptions(
            playlist_id="sauvignon", count=3, max_playlist_length=None, dry_run=True
        ),
        SauvignonCallbacks(choice_reader=Answer(sauvignon.CHOICE_QUIT)),
        SauvignonResources(log_path=tmp_path / "dry.jsonl"),
    )

    assert [result.action for result in summary.results] == [
        "would add",
        "artist already selected",
        "quit",
    ]
    assert summary.paused is True
    assert summary.selected == 1
    assert spotify.posts == []
    assert (sauvignon.previously_added_album_keys(tmp_path / "dry.jsonl")) == set()


async def test_fill_sauvignon_full_playlist_and_invalid_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        LegacySauvignon,
        "refresh",
        AsyncMock(side_effect=lambda *_args, **_kwargs: ([], 0)),
    )
    monkeypatch.setattr(
        sauvignon.new_wine,
        "async_load_playlist_tracks",
        AsyncMock(
            side_effect=lambda *_args, **_kwargs: tuple(object() for _ in range(20))
        ),
    )
    summary = sauvignon.fill_sauvignon_from_lastfm(
        object(),
        object(),
        SauvignonOptions(playlist_id="sauvignon"),
        SauvignonCallbacks(choice_reader=None),
        SauvignonResources(log_path=tmp_path / "full.jsonl"),
    )
    assert summary.requested_count == 0
    assert summary.results == ()

    for kwargs in (
        {"count": 1, "max_playlist_length": 20},
        {"count": 0, "max_playlist_length": None},
        {"count": None, "max_playlist_length": 0},
        {"seed_count": 0},
    ):
        with pytest.raises(sauvignon.SauvignonConfigError):
            (
                sauvignon.fill_sauvignon_from_lastfm(
                    object(),
                    object(),
                    SauvignonOptions(playlist_id="sauvignon", **kwargs),
                    SauvignonCallbacks(choice_reader=None),
                    SauvignonResources(log_path=tmp_path / "invalid.jsonl"),
                )
            )


@dataclass
class AlbumChoicePromptsOnlyForMateriallyDifferentEditionsScenario:
    """Retain the original album choice prompts only for materially different editions
    fixture.

    Args:
        called: Original called observation or resource.
    """

    called: bool

    async def choose_album(self, *_args: object) -> str:
        """Execute the original should not prompt mock boundary.

        Args:
            _args: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.called = True
        return "two"


def _candidate_options(
    options: dict[str, tuple[sauvignon.SpotifyAlbumOption, ...]],
    spotify: object,
    candidate: found_art.FoundArtCandidate,
    retry: object,
) -> tuple[sauvignon.SpotifyAlbumOption, ...]:
    return options[candidate.track]


def _fixture_first_track(
    spotify: object, album: sauvignon.SpotifyAlbumOption, retry: object
) -> sauvignon.FirstTrack:
    return sauvignon.FirstTrack(
        f"track-{album.spotify_id}", f"spotify:track:{album.spotify_id}", "Opening"
    )
