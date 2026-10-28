"""Tests for the New Wine from Old Bottles flush."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

import pytest

from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.interfaces.requests.new_wine import NewWineCallbacks
from spotify_manager.interfaces.requests.new_wine import NewWineStorage
from spotify_manager.routines import new_wine
from tests.support.runtime_resources import Answer
from tests.support.runtime_resources import DiscardMessages
from tests.support.runtime_resources import UnexpectedInteraction


@dataclass(frozen=True)
class ReleaseAnswer:
    """Record offered release identities before returning the scripted answer.

    Args:
        answer: Original chosen control or release identity.
        offered: Original offered-candidate observation list.
    """

    answer: str
    offered: list[tuple[str, ...]]

    async def choose_release(
        self,
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
    ) -> str:
        """Record the original candidate order and return the original choice.

        Args:
            source: Original playlist marker.
            candidates: Original eligible release editions.

        Returns:
            Original scripted answer.
        """
        self.offered.append(tuple(item.spotify_id for item in candidates))
        return self.answer


@dataclass(frozen=True)
class EndpointAnswer:
    """Record the original endpoint prompt before choosing its control.

    Args:
        answer: Original endpoint control.
        offered: Original track-count and current-position observations.
    """

    answer: str
    offered: list[tuple[int, int]]

    async def choose_endpoint(
        self,
        source: new_wine.PlaylistTrack,
        tracks: tuple[new_wine.ReleaseTrack, ...],
        current_index: int,
    ) -> str:
        """Record the complete original endpoint prompt context.

        Args:
            source: Original playlist marker.
            tracks: Original ordered release tracks.
            current_index: Original marker position.

        Returns:
            Original scripted endpoint answer.
        """
        self.offered.append((len(tracks), current_index))
        return self.answer


def raw_release(
    release_id: str,
    name: str,
    *,
    artist_id: str,
    artist_name: str = "Artist",
    album_type: str = "album",
    total_tracks: int = 4,
    release_date: str = "2026-01-01",
) -> dict[str, object]:
    """Build one Spotify release response."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name,
        "album_type": album_type,
        "total_tracks": total_tracks,
        "release_date": release_date,
        "artists": [{"id": artist_id, "name": artist_name}],
    }


def raw_track(
    track_id: str,
    name: str,
    release: dict[str, object],
    *,
    artist_id: str,
    artist_name: str = "Artist",
    track_number: int | str = 1,
) -> dict[str, object]:
    """Build one Spotify track response."""
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "disc_number": 1,
        "track_number": track_number,
        "artists": [{"id": artist_id, "name": artist_name}],
        "album": release,
    }


class FakeSpotify:
    """Small mutable Spotify API simulation for playlist flushes."""

    def __init__(self) -> None:
        self.playlists: dict[str, list[dict[str, object]]] = {
            "new": [],
            "sauv": [],
        }
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.artist_releases: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.saved_album_ids: set[str] = set()
        self.mutations: list[tuple[str, str, str]] = []
        self.liked_contains_calls: list[list[str]] = []
        self.album_contains_calls: list[list[str]] = []
        self.fail_next_delete = False

    async def _get(self, path: str, *, limit: int, offset: int):
        playlist_id = path.split("/")[1]
        tracks = self.playlists[playlist_id]
        page = tracks[offset : offset + limit]
        return {
            "items": [{"item": track} for track in page],
            "total": len(tracks),
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    async def _post(self, path: str, *, payload: dict[str, object]):
        playlist_id = path.split("/")[1]
        uri = str(payload["uris"][0])  # type: ignore[index]
        track_id = uri.split("spotify:track:")[-1]
        track = next(
            track
            for tracks in self.release_tracks.values()
            for track in tracks
            if track["id"] == track_id
        )
        self.playlists[playlist_id].append(track)
        self.mutations.append(("add", playlist_id, track_id))
        return {}

    async def _delete(self, path: str, *, payload: dict[str, object]):
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise RuntimeError("interrupted after add")
        playlist_id = path.split("/")[1]
        uri = str(payload["items"][0]["uri"])  # type: ignore[index]
        track_id = uri.split("spotify:track:")[-1]
        self.playlists[playlist_id] = [
            track for track in self.playlists[playlist_id] if track["id"] != track_id
        ]
        self.mutations.append(("remove", playlist_id, track_id))
        return {}

    async def album_tracks(self, album_id: str, *, limit: int, offset: int):
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    async def artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ):
        assert include_groups == "album,single"
        releases = self.artist_releases.get(artist_id, [])
        page = releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(releases) else None,
        }

    async def current_user_saved_tracks_contains(self, track_ids: list[str]):
        self.liked_contains_calls.append(list(track_ids))
        return [track_id in self.liked_ids for track_id in track_ids]

    async def current_user_saved_albums_contains(self, album_ids: list[str]):
        self.album_contains_calls.append(list(album_ids))
        return [album_id in self.saved_album_ids for album_id in album_ids]

    async def current_user_saved_albums_add(self, album_ids: list[str]):
        for album_id in album_ids:
            self.saved_album_ids.add(album_id)
            self.mutations.append(("save", "library", album_id))
        return None

    async def current_user_saved_albums_delete(self, album_ids: list[str]):
        for album_id in album_ids:
            self.saved_album_ids.discard(album_id)
            self.mutations.append(("unsave", "library", album_id))
        return None


def paths(tmp_path: Path) -> dict[str, Path]:
    """Return isolated runtime paths."""
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
        "albums_path": tmp_path / "albums.json",
        "removed_albums_log_path": tmp_path / "removed.jsonl",
    }


async def test_flush_advances_every_snapshotted_album_track(tmp_path: Path) -> None:
    """Flush advances every snapshotted album track.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    first_release = raw_release("r1", "First", artist_id="a1")
    second_release = raw_release("r2", "Second", artist_id="a2")
    first_tracks = [
        raw_track("t1", "One", first_release, artist_id="a1", track_number=1),
        raw_track("t2", "Two", first_release, artist_id="a1", track_number=2),
    ]
    second_tracks = [
        raw_track("u1", "Alpha", second_release, artist_id="a2", track_number=1),
        raw_track("u2", "Beta", second_release, artist_id="a2", track_number=2),
    ]
    spotify.release_tracks = {"r1": first_tracks, "r2": second_tracks}
    spotify.playlists["new"] = [first_tracks[0], second_tracks[0]]

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("album tracks should not prompt")
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.processed == 2
    assert summary.advanced == 2
    assert [track["id"] for track in spotify.playlists["new"]] == ["t2", "u2"]
    assert spotify.mutations == [
        ("add", "new", "t2"),
        ("remove", "new", "t1"),
        ("add", "new", "u2"),
        ("remove", "new", "u1"),
    ]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run"]["status"] == "completed"
    assert state["track_progress"]["t2"]["prior_unliked_streak"] == 1


async def test_canonical_cutoff_completes_album_and_offers_follow_up(
    tmp_path: Path,
) -> None:
    """Canonical cutoff completes album and offers follow up.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release(
        "album", "Canonical Album", artist_id="artist", total_tracks=5
    )
    follow_up = raw_release(
        "follow-up",
        "Next Release",
        artist_id="artist",
        release_date="2026-06-01",
    )
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 6)
    ]
    spotify.release_tracks = {
        "album": tracks,
        "follow-up": [
            raw_track("f1", "Follow-up Opener", follow_up, artist_id="artist")
        ],
    }
    spotify.artist_releases["artist"] = [release, follow_up]
    spotify.playlists["new"] = [tracks[1]]
    spotify.liked_ids = {"t2"}
    endpoint_calls: list[tuple[int, int]] = []
    release_calls: list[tuple[str, ...]] = []

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            endpoint_mode=True,
            cellar=None,
            no_discovery=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=ReleaseAnswer(new_wine.CHOICE_FINISH, release_calls),
            endpoint=EndpointAnswer(new_wine.CHOICE_CUTOFF, endpoint_calls),
        ),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    result = summary.results[0]
    assert endpoint_calls == [(5, 1)]
    assert release_calls == [("follow-up",)]
    assert result.action == "sauvignon"
    assert result.canonical_track_count == 2
    assert result.canonical_cutoff_track == "Track 2"
    assert [track["id"] for track in spotify.playlists["sauv"]] == ["t1"]
    assert spotify.saved_album_ids == {"album"}
    assert json.loads((tmp_path / "albums.json").read_text()) == [
        {
            "artist": "Artist",
            "album": "Canonical Album",
            "uri": "spotify:album:album",
        }
    ]
    assert spotify.playlists["new"] == []


async def test_canonical_cutoff_governs_drop_evaluation_and_unsaving(
    tmp_path: Path,
) -> None:
    """Canonical cutoff governs drop evaluation and unsaving.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Deluxe Album", artist_id="artist", total_tracks=6)
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 7)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["new"] = [tracks[3]]
    spotify.liked_ids = {"t1", "t5", "t6"}
    spotify.saved_album_ids = {"album"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            endpoint_mode=True,
            cellar=None,
            no_discovery=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("no follow-up should be offered"),
            endpoint=Answer(new_wine.CHOICE_CUTOFF),
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.album_liked_tracks == 1
    assert result.album_total_tracks == 4
    assert result.canonical_track_count == 4
    assert result.canonical_cutoff_track == "Track 4"
    assert result.album_unsaved is True
    assert ("unsave", "library", "album") in spotify.mutations
    assert not ({"t5", "t6"} & set(spotify.liked_contains_calls[-1]))


async def test_canonical_endpoint_review_can_skip_one_entry(tmp_path: Path) -> None:
    """Canonical endpoint review can skip one entry.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Album", artist_id="artist")
    track = raw_track("t1", "Track", release, artist_id="artist")
    spotify.release_tracks["album"] = [track]
    spotify.playlists["new"] = [track]

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            endpoint_mode=True,
            cellar=None,
            no_discovery=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("skipped entries do not continue"),
            endpoint=Answer(new_wine.CHOICE_SKIP),
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.skipped == 1
    assert summary.results[0].action == "skip"
    assert [item["id"] for item in spotify.playlists["new"]] == ["t1"]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run"]["entries"][0]["status"] == "skipped"


async def test_canonical_endpoint_review_can_continue_the_full_tracklist(
    tmp_path: Path,
) -> None:
    """Canonical endpoint review can continue the full tracklist.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Album", artist_id="artist")
    tracks = [
        raw_track("t1", "Current", release, artist_id="artist", track_number=1),
        raw_track("t2", "Next", release, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[0]]

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            endpoint_mode=True,
            cellar=None,
            no_discovery=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("the release is not complete"),
            endpoint=Answer(new_wine.CHOICE_CONTINUE),
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.results[0].action == "advance"
    assert summary.results[0].target_track == "Next"
    assert summary.results[0].canonical_track_count is None
    assert [item["id"] for item in spotify.playlists["new"]] == ["t2"]


async def test_canonical_endpoint_mode_requires_an_interactive_reader(
    tmp_path: Path,
) -> None:
    """Canonical endpoint mode requires an interactive reader.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Album", artist_id="artist")
    track = raw_track("t1", "Track", release, artist_id="artist")
    spotify.release_tracks["album"] = [track]
    spotify.playlists["new"] = [track]

    with pytest.raises(new_wine.NewWineConfigError, match="choice reader"):
        (
            new_wine.flush_new_wine(
                spotify,
                NewWineOptions(
                    destination="new",
                    sauvignon="sauv",
                    endpoint_mode=True,
                    cellar=None,
                    no_discovery=False,
                    dry_run=False,
                ),
                NewWineCallbacks(choose=Answer(new_wine.CHOICE_FINISH)),
                storage=NewWineStorage(**paths(tmp_path)),
            )
        )


async def test_flush_refills_new_wine_to_ten_from_top_of_wine_cellar(
    tmp_path: Path,
) -> None:
    """Flush refills new wine to ten from top of wine cellar.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release(
        "cellar-release",
        "Cellar Release",
        artist_id="artist",
        total_tracks=12,
    )
    tracks = [
        raw_track(
            f"c{index}",
            f"Cellar Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 13)
    ]
    spotify.release_tracks["cellar-release"] = tracks
    spotify.playlists["wine"] = list(tracks)

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar="wine",
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("empty flush should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.refill is not None
    assert summary.refill.before == 0
    assert summary.refill.after == 10
    assert summary.refill.added == 10
    assert summary.refill.removed_from_cellar == 10
    assert [track["id"] for track in spotify.playlists["new"]] == [
        f"c{index}" for index in range(1, 11)
    ]
    assert [track["id"] for track in spotify.playlists["wine"]] == ["c11", "c12"]
    assert spotify.mutations[:4] == [
        ("add", "new", "c1"),
        ("remove", "wine", "c1"),
        ("add", "new", "c2"),
        ("remove", "wine", "c2"),
    ]


async def test_no_discovery_refill_keeps_ineligible_tracks_in_cellar_order(
    tmp_path: Path,
) -> None:
    """No discovery refill keeps ineligible tracks in cellar order.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release(
        "cellar-release",
        "Cellar Release",
        artist_id="various",
        total_tracks=3,
    )
    tracks = [
        raw_track("low", "Low", release, artist_id="low", artist_name="Low"),
        raw_track(
            "albums",
            "Album Rich",
            release,
            artist_id="albums",
            artist_name="Album Rich",
            track_number=2,
        ),
        raw_track(
            "likes",
            "Track Rich",
            release,
            artist_id="likes",
            artist_name="Track Rich",
            track_number=3,
        ),
    ]
    spotify.release_tracks["cellar-release"] = tracks
    spotify.playlists["wine"] = list(tracks)
    spotify.liked_ids = {f"tr{index}" for index in range(18)}
    spotify.saved_album_ids = {f"a{index}" for index in range(3)}
    liked_tracks_path = tmp_path / "liked.json"
    liked_tracks_path.write_text(
        json.dumps(
            [
                {
                    "artist": "track rich",
                    "album": "Liked",
                    "track": f"Liked {index}",
                    "uri": f"spotify:track:tr{index}",
                }
                for index in range(18)
            ]
            + [
                {
                    "artist": "Low",
                    "album": "Stale",
                    "track": f"Stale {index}",
                    "uri": f"spotify:track:low{index}",
                }
                for index in range(18)
            ]
        )
    )
    albums_path = tmp_path / "albums.json"
    albums_path.write_text(
        json.dumps(
            [
                {
                    "artist": "ALBUM RICH",
                    "album": f"Saved {index}",
                    "uri": f"spotify:album:a{index}",
                }
                for index in range(3)
            ]
        )
    )

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar="wine",
            no_discovery=True,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("empty flush should not prompt")),
        storage=NewWineStorage(
            liked_tracks_path=liked_tracks_path,
            albums_path=albums_path,
            **{
                key: value
                for key, value in paths(tmp_path).items()
                if key != "albums_path"
            },
        ),
    )

    assert summary.refill is not None
    assert summary.refill.after == 2
    assert summary.refill.added == 2
    assert summary.refill.ineligible == 1
    assert [result.action for result in summary.refill.results] == [
        "ineligible",
        "moved",
        "moved",
    ]
    assert [track["id"] for track in spotify.playlists["new"]] == [
        "albums",
        "likes",
    ]
    assert [track["id"] for track in spotify.playlists["wine"]] == ["low"]
    assert spotify.album_contains_calls == [["a0", "a1", "a2"]]
    assert spotify.liked_contains_calls == [
        [f"low{index}" for index in range(10)],
        [f"low{index}" for index in range(10, 18)],
        [f"tr{index}" for index in range(10)],
        [f"tr{index}" for index in range(10, 18)],
    ]


async def test_refill_resumes_between_add_and_cellar_removal(tmp_path: Path) -> None:
    """Refill resumes between add and cellar removal.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("cellar-release", "Cellar", artist_id="artist")
    track = raw_track("c1", "Cellar Track", release, artist_id="artist")
    spotify.release_tracks["cellar-release"] = [track]
    spotify.playlists["wine"] = [track]
    spotify.fail_next_delete = True

    with pytest.raises(RuntimeError, match="interrupted after add"):
        (
            new_wine.flush_new_wine(
                spotify,
                NewWineOptions(
                    destination="new",
                    sauvignon="sauv",
                    cellar="wine",
                    no_discovery=False,
                    endpoint_mode=False,
                    dry_run=False,
                ),
                NewWineCallbacks(
                    choose=UnexpectedInteraction("empty flush should not prompt")
                ),
                storage=NewWineStorage(**paths(tmp_path)),
            )
        )

    interrupted_state = json.loads((tmp_path / "state.json").read_text())
    assert interrupted_state["active_run"]["refill_pending"]["source"][
        "spotify_id"
    ] == ("c1")
    assert [track["id"] for track in spotify.playlists["new"]] == ["c1"]
    assert [track["id"] for track in spotify.playlists["wine"]] == ["c1"]

    resumed = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar="wine",
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("resumed refill should not prompt")
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert resumed.resumed is True
    assert resumed.refill is not None
    assert resumed.refill.added == 0
    assert resumed.refill.removed_from_cellar == 1
    assert spotify.mutations == [
        ("add", "new", "c1"),
        ("remove", "wine", "c1"),
    ]
    completed_state = json.loads((tmp_path / "state.json").read_text())
    assert completed_state["active_run"]["refill_pending"] is None
    assert completed_state["active_run"]["status"] == "completed"


async def test_refill_dry_run_simulates_ten_without_mutation(tmp_path: Path) -> None:
    """Refill dry run simulates ten without mutation.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release(
        "cellar-release",
        "Cellar Release",
        artist_id="artist",
        total_tracks=10,
    )
    tracks = [
        raw_track(
            f"c{index}",
            f"Cellar Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 11)
    ]
    spotify.release_tracks["cellar-release"] = tracks
    spotify.playlists["wine"] = list(tracks)

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar="wine",
            dry_run=True,
            no_discovery=False,
            endpoint_mode=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("empty flush should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.refill is not None
    assert summary.refill.after == 10
    assert summary.refill.added == 10
    assert spotify.playlists["new"] == []
    assert [track["id"] for track in spotify.playlists["wine"]] == [
        f"c{index}" for index in range(1, 11)
    ]
    assert spotify.mutations == []
    assert not (tmp_path / "state.json").exists()


async def test_refill_dry_run_uses_projected_post_flush_capacity(
    tmp_path: Path,
) -> None:
    """Refill dry run uses projected post flush capacity.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    dropped_release = raw_release("drop", "Drop", artist_id="drop-artist")
    dropped_tracks = [
        raw_track(
            f"d{index}",
            f"Drop {index}",
            dropped_release,
            artist_id="drop-artist",
            track_number=index,
        )
        for index in range(1, 4)
    ]
    cellar_release = raw_release(
        "cellar-release",
        "Cellar",
        artist_id="cellar-artist",
        total_tracks=10,
    )
    cellar_tracks = [
        raw_track(
            f"c{index}",
            f"Cellar {index}",
            cellar_release,
            artist_id="cellar-artist",
            track_number=index,
        )
        for index in range(1, 11)
    ]
    spotify.release_tracks = {
        "drop": dropped_tracks,
        "cellar-release": cellar_tracks,
    }
    spotify.playlists["new"] = [dropped_tracks[2]]
    spotify.playlists["wine"] = list(cellar_tracks)

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar="wine",
            dry_run=True,
            no_discovery=False,
            endpoint_mode=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("drop should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.results[0].action == "drop"
    assert summary.refill is not None
    assert summary.refill.before == 0
    assert summary.refill.after == 10
    assert summary.refill.added == 10
    assert [track["id"] for track in spotify.playlists["new"]] == ["d3"]
    assert [track["id"] for track in spotify.playlists["wine"]] == [
        f"c{index}" for index in range(1, 11)
    ]


async def test_full_new_wine_does_not_query_wine_cellar(tmp_path: Path) -> None:
    """Full new wine does not query wine cellar.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()

    summary = await new_wine._refill_new_wine(
        spotify,
        "new",
        "not-configured-in-fake",
        no_discovery=True,
        dry_run=True,
        retry_call=NoRetry(),
        state={},
        run={"run_id": "run", "refill_pending": None},
        storage=NewWineStorage(
            state_path=tmp_path / "state.json",
            log_path=tmp_path / "log.jsonl",
            liked_tracks_path=tmp_path / "missing-liked.json",
            albums_path=tmp_path / "missing-albums.json",
        ),
        echo=DiscardMessages(),
        projected_new_wine_ids={f"track-{index}" for index in range(10)},
    )

    assert summary.before == 10
    assert summary.after == 10
    assert summary.results == ()


async def test_three_consecutive_unliked_tracks_jump_to_next_liked_track(
    tmp_path: Path,
) -> None:
    """Three consecutive unliked tracks jump to next liked track.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Drop Me", artist_id="artist")
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.liked_ids = {"t4"}
    spotify.saved_album_ids = {"album"}
    (tmp_path / "albums.json").write_text(
        json.dumps(
            [
                {
                    "artist": "Artist",
                    "album": "Drop Me",
                    "uri": "spotify:album:album",
                }
            ]
        )
    )

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("drop should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    result = summary.results[0]
    assert result.action == "advance"
    assert result.consecutive_unliked == 3
    assert result.target_track == "Track 4"
    assert result.advance_reason == "next_liked_track"
    assert result.album_liked_tracks is None
    assert result.album_unsaved is False
    assert spotify.saved_album_ids == {"album"}
    assert [track["id"] for track in spotify.playlists["new"]] == ["t4"]
    assert spotify.mutations == [
        ("add", "new", "t4"),
        ("remove", "new", "t3"),
    ]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["track_progress"]["t4"]["prior_unliked_streak"] == 0
    assert json.loads((tmp_path / "albums.json").read_text()) != []
    assert not (tmp_path / "removed.jsonl").exists()


async def test_three_unliked_tracks_after_last_like_drop_and_unsave_album(
    tmp_path: Path,
) -> None:
    """Three unliked tracks after last like drop and unsave album.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Drop Me", artist_id="artist")
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[3]]
    spotify.liked_ids = {"t1"}
    spotify.saved_album_ids = {"album"}
    (tmp_path / "albums.json").write_text(
        json.dumps(
            [
                {
                    "artist": "Artist",
                    "album": "Drop Me",
                    "uri": "spotify:album:album",
                }
            ]
        )
    )

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("drop should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.consecutive_unliked == 3
    assert result.album_liked_tracks == 1
    assert result.album_total_tracks == 4
    assert result.album_unsaved is True
    assert spotify.saved_album_ids == set()
    assert spotify.playlists["new"] == []
    assert json.loads((tmp_path / "albums.json").read_text()) == []
    removed = json.loads((tmp_path / "removed.jsonl").read_text())
    assert removed["action"] == "new_wine_three_consecutive_unliked"


async def test_live_like_breaks_the_consecutive_streak(tmp_path: Path) -> None:
    """Live like breaks the consecutive streak.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Keep Moving", artist_id="artist")
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.liked_ids = {"t2"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("album tracks should not prompt")
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.results[0].action == "advance"
    assert summary.results[0].consecutive_unliked == 1
    assert [track["id"] for track in spotify.playlists["new"]] == ["t4"]


async def test_dropped_album_remains_saved_when_it_meets_keep_rule(
    tmp_path: Path,
) -> None:
    """Dropped album remains saved when it meets keep rule.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release(
        "album",
        "Still Worth Keeping",
        artist_id="artist",
        total_tracks=6,
    )
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 7)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[5]]
    spotify.liked_ids = {"t1", "t2", "t3"}
    spotify.saved_album_ids = {"album"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("drop should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.album_liked_tracks == 3
    assert result.album_total_tracks == 6
    assert result.album_unsaved is False
    assert spotify.saved_album_ids == {"album"}
    assert not (tmp_path / "removed.jsonl").exists()


async def test_last_album_track_sends_first_track_to_sauvignon(
    tmp_path: Path,
) -> None:
    """Last album track sends first track to sauvignon.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Finished", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Last", release, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["album"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["new"] = [tracks[1]]
    spotify.liked_ids = {"t2"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("album tracks should not prompt")
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.sent_to_sauvignon == 1
    assert spotify.playlists["new"] == []
    assert [track["id"] for track in spotify.playlists["sauv"]] == ["t1"]
    assert spotify.saved_album_ids == {"album"}
    assert summary.results[0].album_liked_tracks == 1
    assert summary.results[0].album_total_tracks == 2
    assert spotify.mutations == [
        ("save", "library", "album"),
        ("add", "sauv", "t1"),
        ("remove", "new", "t2"),
    ]


async def test_sauvignon_does_not_save_album_below_keep_threshold(
    tmp_path: Path,
) -> None:
    """Sauvignon does not save album below keep threshold.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release(
        "album",
        "Still Discovering",
        artist_id="artist",
        total_tracks=6,
    )
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 7)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["new"] = [tracks[-1]]
    spotify.liked_ids = {"t1", "t5"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("album tracks should not prompt")
        ),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    result = summary.results[0]
    assert result.action == "sauvignon"
    assert result.album_liked_tracks == 2
    assert result.album_total_tracks == 6
    assert spotify.saved_album_ids == set()
    assert spotify.mutations == [
        ("add", "sauv", "t1"),
        ("remove", "new", "t6"),
    ]


async def test_legacy_sauvignon_plan_saves_after_source_was_removed(
    tmp_path: Path,
) -> None:
    """Legacy sauvignon plan saves after source was removed.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Interrupted", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Last", release, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[1]]
    spotify.playlists["sauv"] = [tracks[0]]
    spotify.liked_ids = {"t2"}
    source = (
        new_wine.load_playlist_tracks(
            spotify,
            "new",
            NoRetry(),
        )
    )[0]
    target = (
        new_wine.load_release_tracks(
            spotify,
            source.release,
            NoRetry(),
        )
    )[0]
    state = new_wine._default_state()
    run = new_wine._new_run("new", (source,), None, False, False)
    entry = run["entries"][0]  # type: ignore[index]
    assert isinstance(entry, dict)
    entry["plan"] = {
        "action": "sauvignon",
        "release": asdict(source.release),
        "target": asdict(target),
        "current_liked": True,
        "consecutive_unliked": 0,
        "next_prior_unliked_streak": 0,
        "album_liked_tracks": None,
        "album_total_tracks": None,
        "should_unsave": False,
        "album_unsaved": False,
        "advance_reason": None,
        "drop_reason": None,
    }
    state["active_run"] = run
    new_wine.save_state(state, tmp_path / "state.json")
    spotify.playlists["new"] = []

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("saved plans do not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.resumed is True
    assert spotify.saved_album_ids == {"album"}
    assert spotify.mutations == [("save", "library", "album")]


async def test_album_endpoint_can_start_another_current_year_release(
    tmp_path: Path,
) -> None:
    """Album endpoint can start another current year release.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Finished", artist_id="artist")
    follow_up = raw_release(
        "follow-up",
        "Another Release",
        artist_id="artist",
        release_date="2026-06-01",
    )
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Last", release, artist_id="artist", track_number=2),
    ]
    follow_up_tracks = [
        raw_track(
            "f1",
            "New Opener",
            follow_up,
            artist_id="artist",
            track_number=1,
        )
    ]
    spotify.release_tracks = {
        "album": tracks,
        "follow-up": follow_up_tracks,
    }
    spotify.artist_releases["artist"] = [release, follow_up]
    spotify.playlists["new"] = [tracks[1]]
    spotify.liked_ids = {"t2"}
    offered: list[tuple[str, ...]] = []

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=ReleaseAnswer("follow-up", offered)),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    result = summary.results[0]
    assert offered == [("follow-up",)]
    assert result.action == "sauvignon"
    assert result.continuation_release == "Another Release"
    assert result.continuation_track == "New Opener"
    assert [track["id"] for track in spotify.playlists["sauv"]] == ["t1"]
    assert [track["id"] for track in spotify.playlists["new"]] == ["f1"]
    assert spotify.mutations == [
        ("save", "library", "album"),
        ("add", "sauv", "t1"),
        ("add", "new", "f1"),
        ("remove", "new", "t2"),
    ]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["track_progress"]["f1"]["prior_unliked_streak"] == 0


async def test_drop_endpoint_can_finish_without_a_follow_up_release(
    tmp_path: Path,
) -> None:
    """Drop endpoint can finish without a follow up release.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Drop Me", artist_id="artist")
    follow_up = raw_release(
        "follow-up",
        "Another Release",
        artist_id="artist",
        release_date="2026-06-01",
    )
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks = {
        "album": tracks,
        "follow-up": [raw_track("f1", "New Opener", follow_up, artist_id="artist")],
    }
    spotify.artist_releases["artist"] = [release, follow_up]
    spotify.playlists["new"] = [tracks[3]]
    spotify.liked_ids = {"t1"}
    spotify.saved_album_ids = {"album"}
    offered: list[tuple[str, ...]] = []

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=ReleaseAnswer(new_wine.CHOICE_FINISH, offered)),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    result = summary.results[0]
    assert offered == [("follow-up",)]
    assert result.action == "drop"
    assert result.continuation_release is None
    assert result.continuation_track is None
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []
    assert spotify.mutations == [
        ("unsave", "library", "album"),
        ("remove", "new", "t4"),
    ]


async def test_drop_endpoint_can_start_another_current_year_release(
    tmp_path: Path,
) -> None:
    """Drop endpoint can start another current year release.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Drop Me", artist_id="artist")
    follow_up = raw_release(
        "follow-up",
        "Another Release",
        artist_id="artist",
        release_date="2026-06-01",
    )
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks = {
        "album": tracks,
        "follow-up": [raw_track("f1", "New Opener", follow_up, artist_id="artist")],
    }
    spotify.artist_releases["artist"] = [release, follow_up]
    spotify.playlists["new"] = [tracks[3]]
    spotify.liked_ids = {"t1"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=Answer("follow-up")),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.continuation_release == "Another Release"
    assert result.continuation_track == "New Opener"
    assert [track["id"] for track in spotify.playlists["new"]] == ["f1"]
    assert spotify.mutations == [
        ("add", "new", "f1"),
        ("remove", "new", "t4"),
    ]


async def test_single_prompts_for_current_year_release_and_starts_at_first_track(
    tmp_path: Path,
) -> None:
    """Single prompts for current year release and starts at first track.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Lead Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    album = raw_release("album", "New Album", artist_id="artist")
    old = raw_release(
        "old",
        "Old Album",
        artist_id="artist",
        release_date="2025-01-01",
    )
    single_track = raw_track("s1", "Lead", single, artist_id="artist")
    album_tracks = [
        raw_track("a1", "Opening", album, artist_id="artist", track_number=1),
        raw_track("a2", "Second", album, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks = {
        "single": [single_track],
        "album": album_tracks,
    }
    spotify.artist_releases["artist"] = [album, single, old]
    spotify.playlists["new"] = [single_track]
    offered: list[tuple[str, ...]] = []

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=ReleaseAnswer("album", offered)),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    assert offered == [("album", "single")]
    assert summary.results[0].target_track == "Opening"
    assert [track["id"] for track in spotify.playlists["new"]] == ["a1"]
    assert (
        json.loads((tmp_path / "state.json").read_text())["track_progress"]["a1"][
            "prior_unliked_streak"
        ]
        == 1
    )

    second = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=UnexpectedInteraction("album tracks should not prompt")
        ),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )
    assert second.results[0].consecutive_unliked == 2
    assert [track["id"] for track in spotify.playlists["new"]] == ["a2"]

    endpoint_offered: list[tuple[str, ...]] = []
    third = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(
            choose=ReleaseAnswer(new_wine.CHOICE_FINISH, endpoint_offered)
        ),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )
    assert endpoint_offered == [("single",)]
    assert third.results[0].action == "drop"
    assert third.results[0].consecutive_unliked == 3
    assert spotify.playlists["new"] == []


async def test_selected_release_uses_track_number_not_alphabetical_response(
    tmp_path: Path,
) -> None:
    """Selected release uses track number not alphabetical response.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Lead Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    album = raw_release("album", "New Album", artist_id="artist")
    single_track = raw_track("s1", "Lead", single, artist_id="artist")
    album_tracks = [
        raw_track(
            "a2",
            "Alphabetical but second",
            album,
            artist_id="artist",
            track_number="2",
        ),
        raw_track(
            "a1",
            "Zebra opener",
            album,
            artist_id="artist",
            track_number="1",
        ),
    ]
    spotify.release_tracks = {
        "single": [single_track],
        "album": album_tracks,
    }
    spotify.artist_releases["artist"] = [single, album]
    spotify.playlists["new"] = [single_track]

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=Answer("album")),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    assert summary.results[0].target_track == "Zebra opener"
    assert [track["id"] for track in spotify.playlists["new"]] == ["a1"]


async def test_switching_from_single_to_album_starts_at_album_opener(
    tmp_path: Path,
) -> None:
    """Switching from single to album starts at album opener.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Cryogen",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    album = raw_release("album", "The Wow! Signal", artist_id="artist")
    single_track = raw_track("s1", "Cryogen", single, artist_id="artist")
    album_tracks = [
        raw_track(
            "b1",
            "Be With You",
            album,
            artist_id="artist",
            track_number=3,
        ),
        raw_track(
            "s1",
            "Cryogen",
            album,
            artist_id="artist",
            track_number=2,
        ),
        raw_track(
            "a1",
            "The Dark Forest",
            album,
            artist_id="artist",
            track_number=1,
        ),
    ]
    spotify.release_tracks = {
        "single": [single_track],
        "album": album_tracks,
    }
    spotify.artist_releases["artist"] = [single, album]
    spotify.playlists["new"] = [single_track]

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=Answer("album")),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    assert summary.results[0].target_track == "The Dark Forest"
    assert [track["id"] for track in spotify.playlists["new"]] == ["a1"]


async def test_current_year_release_scan_exhausts_non_chronological_pages() -> None:
    """Current year release scan exhausts non chronological pages."""
    spotify = FakeSpotify()
    older = [
        raw_release(
            f"old-{index}",
            f"Old {index}",
            artist_id="artist",
            release_date=f"20{index:02d}-01-01",
        )
        for index in range(10)
    ]
    current = [
        raw_release(
            "current-1",
            "Current One",
            artist_id="artist",
            album_type="single",
            total_tracks=1,
            release_date="2026-04-17",
        ),
        raw_release(
            "current-2",
            "Current Two",
            artist_id="artist",
            album_type="single",
            total_tracks=1,
            release_date="2026-05-07",
        ),
    ]
    spotify.artist_releases["artist"] = [*older, *current]

    releases = new_wine.current_year_releases(
        spotify,
        "artist",
        2026,
        NoRetry(),
    )

    assert [release.spotify_id for release in releases] == [
        "current-1",
        "current-2",
    ]


async def test_single_release_prompt_can_drop_current_release(tmp_path: Path) -> None:
    """Single release prompt can drop current release.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Current Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    alternative = raw_release(
        "alternative",
        "Alternative Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
        release_date="2026-02-01",
    )
    track = raw_track("s1", "Current", single, artist_id="artist")
    spotify.release_tracks["single"] = [track]
    spotify.artist_releases["artist"] = [single, alternative]
    spotify.playlists["new"] = [track]
    spotify.liked_ids = {"s1"}
    spotify.saved_album_ids = {"single"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=Answer(new_wine.CHOICE_DROP)),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    assert summary.results[0].action == "drop"
    assert summary.results[0].drop_reason == "manual_selection"
    assert summary.results[0].album_unsaved is False
    assert spotify.saved_album_ids == {"single"}
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []


async def test_lone_current_year_single_is_dropped_automatically(
    tmp_path: Path,
) -> None:
    """Lone current year single is dropped automatically.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Only Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    track = raw_track("s1", "Only Track", single, artist_id="artist")
    spotify.release_tracks["single"] = [track]
    spotify.artist_releases["artist"] = [single]
    spotify.playlists["new"] = [track]
    spotify.saved_album_ids = {"single"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("lone single should auto-drop")),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.drop_reason == "only_current_year_single"
    assert result.album_unsaved is True
    assert spotify.saved_album_ids == set()
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []
    removed = json.loads((tmp_path / "removed.jsonl").read_text())
    assert removed["action"] == "new_wine_only_current_year_single"


async def test_completed_single_is_never_added_to_sauvignon(tmp_path: Path) -> None:
    """Completed single is never added to sauvignon.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Two Track Single",
        artist_id="artist",
        album_type="single",
        total_tracks=2,
    )
    alternative = raw_release(
        "alternative",
        "Another Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
        release_date="2026-02-01",
    )
    tracks = [
        raw_track("s1", "First", single, artist_id="artist", track_number=1),
        raw_track("s2", "Last", single, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["single"] = tracks
    spotify.artist_releases["artist"] = [single, alternative]
    spotify.playlists["new"] = [tracks[1]]
    spotify.liked_ids = {"s2"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=Answer("single")),
        storage=NewWineStorage(**paths(tmp_path)),
        year=2026,
    )

    assert summary.results[0].action == "complete single"
    assert summary.completed_singles == 1
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []


async def test_dry_run_reports_unsave_without_mutating_spotify_or_state(
    tmp_path: Path,
) -> None:
    """Dry run reports unsave without mutating spotify or state.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Dry", artist_id="artist", total_tracks=3)
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 4)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.saved_album_ids = {"album"}

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            dry_run=True,
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("drop should not prompt")),
        storage=NewWineStorage(**paths(tmp_path)),
    )

    assert summary.dry_run is True
    assert summary.results[0].album_unsaved is True
    assert spotify.saved_album_ids == {"album"}
    assert [track["id"] for track in spotify.playlists["new"]] == ["t3"]
    assert spotify.mutations == []
    assert not (tmp_path / "state.json").exists()
    assert json.loads((tmp_path / "log.jsonl").read_text())["dry_run"] is True


async def test_interrupted_add_before_remove_resumes_without_double_advance(
    tmp_path: Path,
) -> None:
    """Interrupted add before remove resumes without double advance.

    Args:
        tmp_path: Isolated original fixture storage.
    """
    spotify = FakeSpotify()
    release = raw_release("album", "Resume", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Second", release, artist_id="artist", track_number=2),
        raw_track("t3", "Third", release, artist_id="artist", track_number=3),
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[0]]
    spotify.fail_next_delete = True
    options = paths(tmp_path)

    with pytest.raises(RuntimeError, match="interrupted"):
        (
            new_wine.flush_new_wine(
                spotify,
                NewWineOptions(
                    destination="new",
                    sauvignon="sauv",
                    cellar=None,
                    no_discovery=False,
                    endpoint_mode=False,
                    dry_run=False,
                ),
                NewWineCallbacks(
                    choose=UnexpectedInteraction("album tracks should not prompt")
                ),
                storage=NewWineStorage(**options),
            )
        )

    assert [track["id"] for track in spotify.playlists["new"]] == ["t1", "t2"]

    summary = new_wine.flush_new_wine(
        spotify,
        NewWineOptions(
            destination="new",
            sauvignon="sauv",
            cellar=None,
            no_discovery=False,
            endpoint_mode=False,
            dry_run=False,
        ),
        NewWineCallbacks(choose=UnexpectedInteraction("saved plan should not prompt")),
        storage=NewWineStorage(**options),
    )

    assert summary.resumed is True
    assert summary.advanced == 1
    assert [track["id"] for track in spotify.playlists["new"]] == ["t2"]
    assert spotify.mutations.count(("add", "new", "t2")) == 1
    assert ("add", "new", "t3") not in spotify.mutations
