import json
from datetime import UTC
from datetime import datetime
from functools import partialmethod
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldResources
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import something_old
from tests.support.framework_stubs import empty_object
from tests.support.history_dependencies import something_old_history
from tests.support.runtime_resources import Answer
from tests.support.runtime_resources import UnexpectedInteraction


class FakeSpotify:
    def __init__(self, playlist_items: list[dict[str, object]] | None = None) -> None:
        self.playlist_items = playlist_items or []
        self.playlist_calls = 0
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def _get(self, path: str, **_kwargs: object) -> dict[str, object]:
        assert path.startswith("playlists/")
        self.playlist_calls += 1
        return {
            "items": list(self.playlist_items),
            "total": len(self.playlist_items),
            "next": None,
        }

    async def _post(self, path: str, payload: dict[str, object]) -> None:
        self.posts.append((path, payload))

    async def search(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["type"] == "artist"
        return {
            "artists": {
                "items": [
                    {
                        "id": "old-id",
                        "uri": "spotify:artist:old-id",
                        "name": "Old Artist",
                        "popularity": 42,
                        "followers": {"total": 1000},
                    }
                ]
            }
        }

    async def artist_top_tracks(self, artist_id: str) -> dict[str, object]:
        assert artist_id == "old-id"
        return {
            "tracks": [
                raw_spotify_track("top-1", "Popular One", "First Album"),
                raw_spotify_track("top-2", "Popular Two", "Second Album"),
            ]
        }


def raw_spotify_track(
    spotify_id: str,
    name: str,
    album: str,
) -> dict[str, object]:
    return {
        "id": spotify_id,
        "uri": f"spotify:track:{spotify_id}",
        "name": name,
        "artists": [{"id": "old-id", "name": "Old Artist"}],
        "album": {"name": album},
        "popularity": 50,
    }


def history_summary(*, dry_run: bool) -> scrobble_history.ScrobbleHistorySummary:
    history = tuple(
        blast_from_past.Scrobble(
            artist="Old Artist",
            track=f"Old Track {index % 10}",
            album="Old Album",
            timestamp_ms=1_000 + index,
        )
        for index in range(50)
    ) + tuple(
        blast_from_past.Scrobble(
            artist="New Artist",
            track=f"New Track {index % 10}",
            album="New Album",
            timestamp_ms=10_000 + index,
        )
        for index in range(50)
    )
    return scrobble_history.ScrobbleHistorySummary(
        checked_at=datetime(2026, 8, 4, tzinfo=UTC),
        username="man-et-arms",
        history=history,
        export_scrobbles=len(history),
        legacy_scrobbles_added=0,
        live_scrobbles_added=0,
        dry_run=dry_run,
        persisted=False,
        backup_path=None,
    )


def patch_history_refresh(
    monkeypatch: pytest.MonkeyPatch,
    received: dict[str, object] | None = None,
) -> None:
    def refresh(*_args: object, **kwargs: object):
        if received is not None:
            received.update(kwargs)
        return history_summary(dry_run=bool(kwargs["dry_run"]))

    monkeypatch.setattr(
        HistoryRefresh,
        "run",
        partialmethod(something_old_history, refresh),
    )


def test_golden_oldies_requires_fifty_and_sorts_by_average() -> None:
    summary = history_summary(dry_run=True)
    too_small = tuple(
        blast_from_past.Scrobble("Track", "Small", "", 0) for _ in range(49)
    )

    ranking = something_old.rank_golden_oldies(summary.history + too_small)

    assert [artist.artist for artist in ranking] == ["Old Artist", "New Artist"]
    assert ranking[0].scrobbles == 50
    assert len(ranking[0].top_tracks) == 10
    assert all(track.scrobbles == 5 for track in ranking[0].top_tracks)


async def test_nonempty_playlist_stops_before_refresh_or_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nonempty playlist stops before refresh or prompt.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    spotify = FakeSpotify(
        [
            {
                "item": raw_spotify_track(
                    "existing",
                    "Existing",
                    "Existing Album",
                )
            }
        ]
    )
    monkeypatch.setattr(
        HistoryRefresh,
        "run",
        partialmethod(
            something_old_history,
            UnexpectedInteraction("history should not refresh"),
        ),
    )

    summary = something_old.run_something_old(
        spotify,
        object(),
        SomethingOldOptions(playlist_id="playlist", expected_username="man-et-arms"),
        SomethingOldCallbacks(
            mode_reader=UnexpectedInteraction("should not prompt"),
            album_choice_reader=UnexpectedInteraction("should not prompt"),
        ),
        SomethingOldResources(),
    )

    assert summary.action == "playlist not empty"
    assert spotify.playlist_calls == 1
    assert spotify.posts == []


async def test_dry_run_uses_fresh_oldest_artist_without_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry run uses fresh oldest artist without mutating.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    spotify = FakeSpotify()
    received: dict[str, object] = {}
    patch_history_refresh(monkeypatch, received)

    summary = something_old.run_something_old(
        spotify,
        object(),
        SomethingOldOptions(
            playlist_id="playlist", expected_username="man-et-arms", dry_run=True
        ),
        SomethingOldCallbacks(
            mode_reader=Answer("spotify_top_tracks"),
            album_choice_reader=UnexpectedInteraction("album prompt is not needed"),
        ),
        SomethingOldResources(),
    )

    assert received["dry_run"] is True
    assert summary.action == "would add"
    assert summary.artist is not None
    assert summary.artist.artist == "Old Artist"
    assert [track.track for track in summary.tracks] == ["Popular One", "Popular Two"]
    assert spotify.playlist_calls == 1
    assert spotify.posts == []


async def test_real_run_rechecks_empty_playlist_then_logs_exact_addition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real run rechecks empty playlist then logs exact addition.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    patch_history_refresh(monkeypatch)
    log_path = tmp_path / "something-old.jsonl"

    summary = something_old.run_something_old(
        spotify,
        object(),
        SomethingOldOptions(playlist_id="playlist", expected_username="man-et-arms"),
        SomethingOldCallbacks(
            mode_reader=Answer("spotify_top_tracks"),
            album_choice_reader=UnexpectedInteraction("album prompt is not needed"),
        ),
        SomethingOldResources(log_path=log_path),
    )

    assert summary.action == "added"
    assert spotify.playlist_calls == 2
    assert spotify.posts == [
        (
            "playlists/playlist/items",
            {"uris": ["spotify:track:top-1", "spotify:track:top-2"]},
        )
    ]
    audit = json.loads(log_path.read_text(encoding="utf-8"))
    assert audit["artist"]["artist"] == "Old Artist"
    assert [track["track"] for track in audit["tracks"]] == [
        "Popular One",
        "Popular Two",
    ]


async def test_real_run_refuses_to_add_if_playlist_fills_during_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real run refuses to add if playlist fills during selection.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    spotify = PlaylistFillsSpotify()
    patch_history_refresh(monkeypatch)
    log_path = tmp_path / "something-old.jsonl"

    with pytest.raises(something_old.SomethingOldError, match="changed"):
        (
            something_old.run_something_old(
                spotify,
                object(),
                SomethingOldOptions(
                    playlist_id="playlist", expected_username="man-et-arms"
                ),
                SomethingOldCallbacks(
                    mode_reader=Answer("spotify_top_tracks"),
                    album_choice_reader=UnexpectedInteraction(
                        "album prompt is not needed"
                    ),
                ),
                SomethingOldResources(log_path=log_path),
            )
        )

    assert spotify.playlist_calls == 2
    assert spotify.posts == []
    assert not log_path.exists()


async def test_album_mode_adds_the_complete_chronological_release_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Album mode adds the complete chronological release choice.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    spotify = FakeSpotify()
    patch_history_refresh(monkeypatch)
    release = slow_listening.DiscographyRelease(
        spotify_id="release-id",
        uri="spotify:album:release-id",
        name="Plain EP",
        release_type="EP",
        release_date="2010-01-01",
        chronology_date="2010-01-01",
        total_tracks=2,
        primary_artist_id="old-id",
        primary_artist_name="Old Artist",
        identity="plain ep",
        saved=True,
        plain=True,
        edition_rank=0,
    )
    monkeypatch.setattr(
        something_old.slow_listening,
        "async_load_discography",
        AsyncMock(side_effect=Mock(return_value=(release,))),
    )
    monkeypatch.setattr(
        something_old.slow_listening,
        "async_load_release_tracks",
        AsyncMock(
            side_effect=Mock(
                return_value=(
                    something_old.slow_listening.new_wine.ReleaseTrack(
                        "track-1", "spotify:track:track-1", "First", 1, 1
                    ),
                    something_old.slow_listening.new_wine.ReleaseTrack(
                        "track-2", "spotify:track:track-2", "Second", 1, 2
                    ),
                )
            )
        ),
    )

    summary = something_old.run_something_old(
        spotify,
        object(),
        SomethingOldOptions(
            playlist_id="playlist", expected_username="man-et-arms", dry_run=True
        ),
        SomethingOldCallbacks(
            mode_reader=Answer("album"),
            album_choice_reader=FirstAlbumChoice(),
        ),
        SomethingOldResources(),
    )

    assert summary.release == release
    assert [track.track for track in summary.tracks] == ["First", "Second"]


async def test_lastfm_top_tracks_use_strict_spotify_matching() -> None:
    """Lastfm top tracks use strict spotify matching."""
    artist = something_old.GoldenOldieArtist(
        artist="Old Artist",
        scrobbles=50,
        average_scrobble_ms=1000,
        first_scrobble_ms=1,
        last_scrobble_ms=2000,
        top_tracks=(
            something_old.LastFmTrackStat("Most Played", 30, 2000),
            something_old.LastFmTrackStat("Second Played", 20, 1900),
        ),
    )

    tracks = something_old.select_lastfm_top_tracks(
        TrackSearchSpotify(),
        artist,
        NoRetry(),
    )

    assert [track.track for track in tracks] == ["Most Played", "Second Played"]
    assert [track.lastfm_scrobbles for track in tracks] == [30, 20]


def spotify_artist(spotify_id: str, name: str = "Old Artist") -> dict[str, object]:
    return {
        "id": spotify_id,
        "uri": f"spotify:artist:{spotify_id}",
        "name": name,
        "popularity": 50,
        "followers": {"total": 100},
    }


@pytest.mark.parametrize("response", [None, {}, {"artists": {}}])
async def test_artist_resolution_rejects_malformed_search_responses(
    response: object,
) -> None:
    """Artist resolution rejects malformed search responses.

    Args:
        response: Original response.
    """
    spotify = type(
        "SearchSpotify",
        (),
        {"search": AsyncMock(return_value=response)},
    )()
    with pytest.raises(something_old.SomethingOldSpotifyError, match="invalid"):
        (
            something_old.resolve_spotify_artist(
                spotify,  # type: ignore[arg-type]
                "Old Artist",
                None,
                NoRetry(),
            )
        )


async def test_artist_resolution_handles_missing_ambiguous_and_selected_matches() -> (
    None
):
    """Artist resolution handles missing ambiguous and selected matches."""
    spotify = ArtistSearchSpotify()
    spotify.items = [None, spotify_artist("other", "Other Artist")]
    with pytest.raises(something_old.SomethingOldSpotifyError, match="No exact"):
        (
            something_old.resolve_spotify_artist(
                spotify,  # type: ignore[arg-type]
                "Old Artist",
                None,
                NoRetry(),
            )
        )

    spotify.items = [spotify_artist("one"), spotify_artist("two")]
    with pytest.raises(something_old.SomethingOldSpotifyError, match="2 exact"):
        (
            something_old.resolve_spotify_artist(
                spotify,  # type: ignore[arg-type]
                "Old Artist",
                None,
                NoRetry(),
            )
        )

    assert (
        something_old.resolve_spotify_artist(
            spotify,  # type: ignore[arg-type]
            "Old Artist",
            Answer("quit"),
            NoRetry(),
        )
    ) is None
    with pytest.raises(something_old.SomethingOldSpotifyError, match="selected"):
        (
            something_old.resolve_spotify_artist(
                spotify,  # type: ignore[arg-type]
                "Old Artist",
                Answer("missing"),
                NoRetry(),
            )
        )

    selected = something_old.resolve_spotify_artist(
        spotify,  # type: ignore[arg-type]
        "Old Artist",
        Answer("two"),
        NoRetry(),
    )
    assert selected is not None
    assert selected.spotify_id == "two"


async def test_spotify_top_tracks_validate_payload_and_usable_tracks() -> None:
    """Spotify top tracks validate payload and usable tracks."""
    artist = something_old.SpotifyArtistCandidate(
        spotify_id="old-id",
        name="Old Artist",
        uri="spotify:artist:old-id",
        popularity=50,
        followers=100,
        search_rank=1,
    )

    malformed = type(
        "TopSpotify",
        (),
        {"artist_top_tracks": AsyncMock(side_effect=empty_object)},
    )()
    with pytest.raises(something_old.SomethingOldSpotifyError, match="invalid"):
        (
            something_old.select_spotify_top_tracks(
                malformed,  # type: ignore[arg-type]
                artist,
                NoRetry(),
            )
        )

    unusable = type(
        "TopSpotify",
        (),
        {"artist_top_tracks": AsyncMock(return_value={"tracks": [None, {"id": "x"}]})},
    )()
    with pytest.raises(something_old.SomethingOldSpotifyError, match="no usable"):
        (
            something_old.select_spotify_top_tracks(
                unusable,  # type: ignore[arg-type]
                artist,
                NoRetry(),
            )
        )


async def test_album_selection_handles_empty_cancelled_and_invalid_catalogs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Album selection handles empty cancelled and invalid catalogs.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    artist = something_old.GoldenOldieArtist(
        artist="Old Artist",
        scrobbles=50,
        average_scrobble_ms=1,
        first_scrobble_ms=1,
        last_scrobble_ms=1,
        top_tracks=(),
    )
    spotify_artist_candidate = something_old.SpotifyArtistCandidate(
        spotify_id="old-id",
        name="Old Artist",
        uri="spotify:artist:old-id",
        popularity=50,
        followers=100,
        search_rank=1,
    )

    monkeypatch.setattr(
        something_old.slow_listening,
        "async_load_discography",
        AsyncMock(side_effect=Mock(return_value=())),
    )
    with pytest.raises(something_old.SomethingOldSpotifyError, match="No studio"):
        (
            something_old.select_album_tracks(
                object(),  # type: ignore[arg-type]
                artist,
                spotify_artist_candidate,
                Answer("quit"),
                NoRetry(),
            )
        )

    release = SimpleNamespace(
        spotify_id="release",
        name="Album",
        release_type="Album",
    )
    monkeypatch.setattr(
        something_old.slow_listening,
        "async_load_discography",
        AsyncMock(side_effect=Mock(return_value=(release,))),
    )
    assert (
        something_old.select_album_tracks(
            object(),  # type: ignore[arg-type]
            artist,
            spotify_artist_candidate,
            Answer("quit"),
            NoRetry(),
        )
    ) == (None, ())
    with pytest.raises(something_old.SomethingOldSpotifyError, match="selected"):
        (
            something_old.select_album_tracks(
                object(),  # type: ignore[arg-type]
                artist,
                spotify_artist_candidate,
                Answer("missing"),
                NoRetry(),
            )
        )


@pytest.mark.parametrize("track_failure", ["error", "empty"])
async def test_album_selection_translates_tracklist_failures(
    monkeypatch: pytest.MonkeyPatch,
    track_failure: str,
) -> None:
    """Album selection translates tracklist failures.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        track_failure: Original track failure.
    """
    artist = something_old.GoldenOldieArtist(
        artist="Old Artist",
        scrobbles=50,
        average_scrobble_ms=1,
        first_scrobble_ms=1,
        last_scrobble_ms=1,
        top_tracks=(),
    )
    spotify_artist_candidate = something_old.SpotifyArtistCandidate(
        spotify_id="old-id",
        name="Old Artist",
        uri="spotify:artist:old-id",
        popularity=None,
        followers=None,
        search_rank=1,
    )
    release = SimpleNamespace(
        spotify_id="release",
        name="Album",
        release_type="Album",
    )
    monkeypatch.setattr(
        something_old.slow_listening,
        "async_load_discography",
        AsyncMock(side_effect=Mock(return_value=(release,))),
    )
    if track_failure == "error":
        monkeypatch.setattr(
            something_old.slow_listening,
            "async_load_release_tracks",
            AsyncMock(
                side_effect=Mock(
                    side_effect=slow_listening.SlowListeningError("tracks failed")
                )
            ),
        )
        message = "tracks failed"
    else:
        monkeypatch.setattr(
            something_old.slow_listening,
            "async_load_release_tracks",
            AsyncMock(side_effect=Mock(return_value=())),
        )
        message = "no playable"

    with pytest.raises(something_old.SomethingOldSpotifyError, match=message):
        (
            something_old.select_album_tracks(
                object(),  # type: ignore[arg-type]
                artist,
                spotify_artist_candidate,
                Answer("release"),
                NoRetry(),
            )
        )


class FirstAlbumChoice:
    """Choose the original first eligible chronological album."""

    async def choose_album(
        self,
        artist: something_old.GoldenOldieArtist,
        releases: tuple[something_old.slow_listening.DiscographyRelease, ...],
    ) -> str:
        """Accept the original first offered edition.

        Args:
            artist: Original selected history artist.
            releases: Original chronological eligible releases.

        Returns:
            Original first release identity.
        """
        return releases[0].spotify_id


class PlaylistFillsSpotify(FakeSpotify):
    """Retain the original playlistfills spotify boundary fixture."""

    async def _get(self, path: str, **_kwargs: object) -> dict[str, object]:
        assert path.startswith("playlists/")
        self.playlist_calls += 1
        items = (
            []
            if self.playlist_calls == 1
            else [
                {
                    "item": raw_spotify_track(
                        "new-existing",
                        "New Existing",
                        "New Existing Album",
                    )
                }
            ]
        )
        return {"items": items, "total": len(items), "next": None}


class TrackSearchSpotify:
    """Retain the original tracksearch spotify boundary fixture."""

    async def search(self, **kwargs: object) -> dict[str, object]:
        """Retain the original search fixture observation.

        Args:
            kwargs: Original kwargs value.

        Returns:
            Original fixture result.
        """
        query = str(kwargs["q"])
        name = "Most Played" if "Most Played" in query else "Second Played"
        return {"tracks": {"items": [raw_spotify_track(name, name, "Album")]}}

    async def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
        """Report that none of the requested tracks are liked.

        Args:
            ids: Requested track identities.

        Returns:
            One false membership flag per track.
        """
        return [False] * len(ids)


class ArtistSearchSpotify:
    """Retain the original artistsearch spotify boundary fixture."""

    items: list[object] = []

    async def search(self, **_kwargs: object) -> dict[str, object]:
        """Return the configured artist search observations.

        Args:
            **_kwargs: External SDK keyword options.

        Returns:
            Original artist search response.
        """
        return {"artists": {"items": self.items}}
