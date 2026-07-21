"""Tests for restart-safe artist review and queue placement."""

import json
from pathlib import Path

from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import review_artists


def artist(artist_id: str, name: str | None = None) -> YourLibraryArtist:
    return YourLibraryArtist(
        name=name or f"Artist {artist_id}",
        uri=f"spotify:artist:{artist_id}",
    )


def liked_tracks(item: YourLibraryArtist, count: int) -> list[YourLibraryTrack]:
    return [
        YourLibraryTrack(
            artist=item.name,
            album=f"Liked album {index}",
            track=f"Liked track {index}",
            uri=f"spotify:track:liked-{item.spotify_id}-{index}",
        )
        for index in range(count)
    ]


def spotify_track(
    track_id: str,
    primary_artist_id: str,
    *,
    target_artist_id: str | None = None,
    name: str | None = None,
    popularity: int | None = None,
) -> dict:
    raw_artists = [{"id": primary_artist_id, "name": f"Artist {primary_artist_id}"}]
    if target_artist_id and target_artist_id != primary_artist_id:
        raw_artists.append(
            {"id": target_artist_id, "name": f"Artist {target_artist_id}"}
        )
    result = {
        "id": track_id,
        "name": name or f"Track {track_id}",
        "uri": f"spotify:track:{track_id}",
        "artists": raw_artists,
        "album": {"name": f"Release {track_id}"},
    }
    if popularity is not None:
        result["popularity"] = popularity
    return result


def spotify_release(
    release_id: str,
    artist_id: str,
    *,
    album_type: str = "album",
    release_date: str = "2020-01-01",
    total_tracks: int = 10,
) -> dict:
    return {
        "id": release_id,
        "name": f"Release {release_id}",
        "uri": f"spotify:album:{release_id}",
        "album_type": album_type,
        "release_date": release_date,
        "total_tracks": total_tracks,
        "artists": [{"id": artist_id, "name": f"Artist {artist_id}"}],
    }


def stats_report(total_artists: int) -> StatsReport:
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=20,
            removed_albums=0,
            added_albums=0,
            growth=0,
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=total_artists,
            removed_artists=0,
            added_artists=0,
            growth=0,
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=50,
            removed_tracks=0,
            added_tracks=0,
            growth=0,
        ),
        avg_albums_per_artists=20 // max(1, total_artists),
        avg_liked_tracks_per_artists=50 // max(1, total_artists),
    )


def write_models(path: Path, models: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([model.model_dump() for model in models]))


def prepare_paths(
    tmp_path: Path,
    artists: list[YourLibraryArtist],
    tracks: list[YourLibraryTrack] | None = None,
) -> review_artists.ArtistReviewPaths:
    paths = review_artists.ArtistReviewPaths.for_files_dir(tmp_path)
    write_models(paths.artists, artists)
    write_models(paths.liked_tracks, tracks or [])
    paths.stats_history.write_text(
        json.dumps({"2026.07.01": stats_report(len(artists)).model_dump()})
    )
    return paths


class FakeSpotify:
    """Small Spotify stand-in that records every endpoint touched."""

    def __init__(self) -> None:
        self.search_results: dict[tuple[str, str], list[dict]] = {}
        self.playlists: dict[str, list[dict]] = {}
        self.discographies: dict[str, list[dict]] = {}
        self.first_tracks: dict[str, list[dict]] = {}
        self.search_calls: list[tuple[str, str, int, int]] = []
        self.playlist_get_calls: list[str] = []
        self.playlist_post_calls: list[tuple[str, dict]] = []
        self.library_delete_calls: list[tuple[str, dict]] = []
        self.playlist_delete_calls: list[tuple[str, dict]] = []
        self.artist_album_calls: list[tuple[str, int, int]] = []
        self.album_track_calls: list[str] = []

    def set_search(
        self,
        item: YourLibraryArtist,
        search_type: str,
        results: list[dict],
    ) -> None:
        query = review_artists.spotify_search_query(item.name)
        self.search_results[(search_type, query)] = results

    def search(self, q: str, limit: int, offset: int, **kwargs: str) -> dict:
        search_type = kwargs["type"]
        self.search_calls.append((search_type, q, limit, offset))
        results = self.search_results.get((search_type, q), [])
        items = results[offset : offset + limit]
        return {
            f"{search_type}s": {
                "items": items,
                "next": "next" if offset + len(items) < len(results) else None,
                "total": len(results),
            }
        }

    def _get(self, path: str, limit: int, offset: int) -> dict:
        playlist_id = path.split("/")[1]
        self.playlist_get_calls.append(playlist_id)
        tracks = self.playlists.get(playlist_id, [])
        items = [{"item": track} for track in tracks[offset : offset + limit]]
        return {
            "items": items,
            "next": "next" if offset + len(items) < len(tracks) else None,
            "total": len(tracks),
        }

    def _post(self, path: str, payload: dict) -> dict:
        playlist_id = path.split("/")[1]
        self.playlist_post_calls.append((playlist_id, payload))
        return {"snapshot_id": "snapshot"}

    def _delete(self, path: str, payload: dict | None = None, **kwargs) -> None:
        if path.startswith("playlists/"):
            assert payload is not None
            playlist_id = path.split("/")[1]
            self.playlist_delete_calls.append((playlist_id, payload))
            return
        assert payload is None
        self.library_delete_calls.append((path, kwargs))

    def artist_albums(
        self,
        artist_id: str,
        include_groups: str,
        limit: int,
        offset: int,
    ) -> dict:
        assert include_groups == "album,single,compilation"
        self.artist_album_calls.append((artist_id, limit, offset))
        releases = self.discographies.get(artist_id, [])
        items = releases[offset : offset + limit]
        return {
            "items": items,
            "next": "next" if offset + len(items) < len(releases) else None,
            "total": len(releases),
        }

    def album_tracks(self, album_id: str, limit: int, offset: int) -> dict:
        assert (limit, offset) == (1, 0)
        self.album_track_calls.append(album_id)
        return {"items": self.first_tracks.get(album_id, [])[:1]}


PLAYLISTS = review_artists.QueuePlaylists("queue-1", "queue-2", "queue-3")


def run_review(
    sp: FakeSpotify,
    paths: review_artists.ArtistReviewPaths,
    **kwargs,
) -> review_artists.ArtistReviewSummary:
    return review_artists.review_artists(
        sp,
        PLAYLISTS,
        paths=paths,
        echo=lambda _line: None,
        sleep=lambda _seconds: None,
        **kwargs,
    )


def test_zero_liked_uses_only_the_first_five_ranked_tracks(tmp_path: Path) -> None:
    removed = artist("removed")
    kept = artist("kept")
    paths = prepare_paths(tmp_path, [removed, kept])
    sp = FakeSpotify()
    sp.set_search(
        removed,
        "track",
        [
            spotify_track(
                f"secondary-{index}",
                "other",
                target_artist_id=removed.spotify_id,
            )
            for index in range(5)
        ]
        + [spotify_track("rank-six", removed.spotify_id)],
    )
    sp.set_search(kept, "track", [spotify_track("primary", kept.spotify_id)])

    summary = run_review(sp, paths)

    assert summary.reviewed == 2
    assert summary.unfollowed == 1
    assert sp.playlist_get_calls == []
    assert sp.library_delete_calls == [
        ("me/library", {"uris": "spotify:artist:removed"})
    ]
    saved = json.loads(paths.artists.read_text())
    assert [item["uri"] for item in saved] == ["spotify:artist:kept"]
    history = json.loads(paths.stats_history.read_text())
    latest = next(reversed(history.values()))
    assert latest["artists_stats"]["total_followed_artists"] == 1
    assert latest["artists_stats"]["removed_artists"] == 1


def test_low_tier_adds_only_to_queue_one_and_uses_an_unliked_track(
    tmp_path: Path,
) -> None:
    item = artist("low")
    local_likes = liked_tracks(item, 1)
    paths = prepare_paths(tmp_path, [item], local_likes)
    sp = FakeSpotify()
    sp.set_search(
        item,
        "track",
        [
            spotify_track(local_likes[0].spotify_id, item.spotify_id),
            spotify_track("unliked", item.spotify_id),
        ],
    )

    summary = run_review(sp, paths)

    assert summary.queued == 1
    assert sp.playlist_get_calls == ["queue-1", "queue-2", "queue-3"]
    assert sp.playlist_post_calls == [("queue-1", {"uris": ["spotify:track:unliked"]})]


def test_existing_tier_queue_entry_avoids_catalog_requests(tmp_path: Path) -> None:
    item = artist("present")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 3))
    sp = FakeSpotify()
    sp.playlists["queue-1"] = [spotify_track("queued", item.spotify_id)]

    summary = run_review(sp, paths)

    assert summary.already_queued == 1
    assert sp.playlist_get_calls == ["queue-1"]
    assert sp.search_calls == []
    assert sp.playlist_post_calls == []


def test_medium_tier_prompts_with_album_and_ep_and_adds_only_to_queue_two(
    tmp_path: Path,
) -> None:
    item = artist("medium")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 6))
    sp = FakeSpotify()
    sp.set_search(
        item,
        "album",
        [
            spotify_release("album", item.spotify_id),
            spotify_release(
                "single",
                item.spotify_id,
                album_type="single",
                total_tracks=1,
            ),
            spotify_release(
                "ep",
                item.spotify_id,
                album_type="single",
                total_tracks=4,
            ),
            spotify_release("comp", item.spotify_id, album_type="compilation"),
        ],
    )
    sp.first_tracks["album"] = [spotify_track("album-first", "other")]
    sp.first_tracks["ep"] = [spotify_track("ep-first", item.spotify_id)]
    prompted: list[tuple[tuple[review_artists.ReleaseCandidate, ...], bool]] = []

    def choose_release(
        _artist: YourLibraryArtist,
        candidates: tuple[review_artists.ReleaseCandidate, ...],
        allow_decline: bool,
    ) -> str:
        prompted.append((candidates, allow_decline))
        return "ep"

    summary = run_review(sp, paths, release_choice_reader=choose_release)

    assert summary.queued == 1
    assert sp.playlist_get_calls == ["queue-2", "queue-3", "queue-1"]
    assert sp.playlist_post_calls == [("queue-2", {"uris": ["spotify:track:ep-first"]})]
    candidates, allow_decline = prompted[0]
    assert not allow_decline
    assert [candidate.release_type for candidate in candidates] == ["Album", "EP"]
    assert [candidate.is_eligible_for(item.spotify_id) for candidate in candidates] == [
        False,
        True,
    ]


def test_high_tier_can_decline_or_choose_from_earliest_releases_and_resumes(
    tmp_path: Path,
) -> None:
    declined = artist("declined")
    queued = artist("queued")
    paths = prepare_paths(
        tmp_path,
        [declined, queued],
        [*liked_tracks(declined, 18), *liked_tracks(queued, 18)],
    )
    sp = FakeSpotify()
    sp.discographies[declined.spotify_id] = [
        spotify_release("decline-release", declined.spotify_id)
    ]
    sp.first_tracks["decline-release"] = [
        spotify_track("decline-first", declined.spotify_id)
    ]
    sp.discographies[queued.spotify_id] = [
        spotify_release("new", queued.spotify_id, release_date="2020-01-01"),
        spotify_release(
            "old",
            queued.spotify_id,
            album_type="compilation",
            release_date="1990",
        ),
    ]
    sp.first_tracks["new"] = [spotify_track("new-first", queued.spotify_id)]
    sp.first_tracks["old"] = [spotify_track("old-first", queued.spotify_id)]
    seen_dates: list[list[str]] = []

    def choose_release(
        item: YourLibraryArtist,
        candidates: tuple[review_artists.ReleaseCandidate, ...],
        allow_decline: bool,
    ) -> str:
        assert allow_decline
        if item.spotify_id == declined.spotify_id:
            return review_artists.CHOICE_DECLINE
        seen_dates.append([candidate.release_date for candidate in candidates])
        return candidates[0].spotify_id

    summary = run_review(sp, paths, release_choice_reader=choose_release)

    assert summary.declined == 1
    assert summary.queued == 1
    assert seen_dates == [["1990", "2020-01-01"]]
    assert sp.playlist_get_calls == ["queue-2", "queue-3", "queue-1"]
    assert sp.playlist_post_calls == [
        ("queue-3", {"uris": ["spotify:track:old-first"]})
    ]

    resumed_sp = FakeSpotify()
    resumed = run_review(resumed_sp, paths)
    assert resumed.total_pending_at_start == 0
    assert resumed_sp.playlist_get_calls == []
    assert resumed_sp.artist_album_calls == []


def test_queue_two_placement_is_sticky_after_artist_reaches_high_tier(
    tmp_path: Path,
) -> None:
    item = artist("sticky-medium")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 18))
    sp = FakeSpotify()
    sp.playlists["queue-2"] = [spotify_track("existing", item.spotify_id)]

    summary = run_review(sp, paths)

    assert summary.already_queued == 1
    assert sp.playlist_get_calls == ["queue-2"]
    assert sp.playlist_post_calls == []
    assert sp.artist_album_calls == []


def test_queue_three_placement_is_sticky_when_liked_count_drops(tmp_path: Path) -> None:
    item = artist("sticky-high")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 3))
    sp = FakeSpotify()
    sp.playlists["queue-3"] = [spotify_track("existing", item.spotify_id)]

    summary = run_review(sp, paths)

    assert summary.already_queued == 1
    assert sp.playlist_get_calls == ["queue-1", "queue-2", "queue-3"]
    assert sp.playlist_post_calls == []
    assert sp.search_calls == []


def test_queue_one_artist_with_six_or_more_likes_moves_only_to_queue_two(
    tmp_path: Path,
) -> None:
    item = artist("promoted")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 18))
    sp = FakeSpotify()
    sp.playlists["queue-1"] = [spotify_track("old-queue-track", item.spotify_id)]
    sp.set_search(
        item,
        "album",
        [spotify_release("promotion-release", item.spotify_id)],
    )
    sp.first_tracks["promotion-release"] = [
        spotify_track("promotion-track", item.spotify_id)
    ]
    prompt_flags: list[bool] = []

    def choose_release(
        _artist: YourLibraryArtist,
        candidates: tuple[review_artists.ReleaseCandidate, ...],
        allow_decline: bool,
    ) -> str:
        prompt_flags.append(allow_decline)
        return candidates[0].spotify_id

    summary = run_review(sp, paths, release_choice_reader=choose_release)

    assert summary.moved == 1
    assert summary.queued == 0
    assert prompt_flags == [False]
    assert sp.playlist_get_calls == ["queue-2", "queue-3", "queue-1"]
    assert sp.playlist_post_calls == [
        ("queue-2", {"uris": ["spotify:track:promotion-track"]})
    ]
    assert sp.playlist_delete_calls == [
        (
            "queue-1",
            {"items": [{"uri": "spotify:track:old-queue-track"}]},
        )
    ]
    assert sp.artist_album_calls == []


def test_skip_is_run_only_and_cached_search_is_reused(tmp_path: Path) -> None:
    item = artist("ambiguous")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 2))
    first_sp = FakeSpotify()
    first_sp.set_search(
        item,
        "track",
        [
            spotify_track("version-a", item.spotify_id, name="Popular"),
            spotify_track("version-b", item.spotify_id, name="Popular"),
        ],
    )

    first = run_review(
        first_sp,
        paths,
        track_choice_reader=lambda _artist, _candidates: review_artists.CHOICE_SKIP,
    )
    assert first.skipped == 1
    assert first.reviewed == 0

    resumed_sp = FakeSpotify()
    resumed = run_review(
        resumed_sp,
        paths,
        track_choice_reader=lambda _artist, _candidates: "version-b",
    )
    assert resumed.queued == 1
    assert resumed_sp.search_calls == []
    assert resumed_sp.playlist_post_calls == [
        ("queue-1", {"uris": ["spotify:track:version-b"]})
    ]


def test_pending_unfollow_is_finished_before_new_catalog_work(tmp_path: Path) -> None:
    item = artist("pending")
    paths = prepare_paths(tmp_path, [item])
    paths.log.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-15T00:00:00+00:00",
                "run_id": "old-run",
                "event": "unfollow_planned",
                "artist_id": item.spotify_id,
                "artist": item.name,
                "liked_tracks": 0,
                "reason": "no_ranked_tracks",
            }
        )
        + "\n"
    )
    sp = FakeSpotify()

    summary = run_review(sp, paths)

    assert summary.total_pending_at_start == 1
    assert summary.unfollowed == 1
    assert sp.search_calls == []
    assert sp.library_delete_calls == [
        ("me/library", {"uris": "spotify:artist:pending"})
    ]


def test_pending_queue_move_finishes_without_adding_a_duplicate(tmp_path: Path) -> None:
    item = artist("pending-move")
    paths = prepare_paths(tmp_path, [item], liked_tracks(item, 8))
    paths.log.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-15T00:00:00+00:00",
                "run_id": "old-run",
                "event": "queue_move_planned",
                "artist_id": item.spotify_id,
                "artist": item.name,
                "liked_tracks": 8,
                "source_playlist_id": "queue-1",
                "target_playlist_id": "queue-2",
                "source_track_uris": ["spotify:track:old-track"],
                "selected_track_id": "new-track",
                "selected_track_uri": "spotify:track:new-track",
                "selected_track_name": "New track",
            }
        )
        + "\n"
    )
    sp = FakeSpotify()
    sp.playlists["queue-1"] = [spotify_track("old-track", item.spotify_id)]
    sp.playlists["queue-2"] = [spotify_track("new-track", item.spotify_id)]

    summary = run_review(sp, paths)

    assert summary.total_pending_at_start == 1
    assert summary.moved == 1
    assert sp.playlist_post_calls == []
    assert sp.playlist_delete_calls == [
        ("queue-1", {"items": [{"uri": "spotify:track:old-track"}]})
    ]
    assert sp.search_calls == []


def test_playlist_references_and_tiers_map_to_exactly_one_queue() -> None:
    playlists = review_artists.QueuePlaylists.from_references(
        "https://open.spotify.com/playlist/first?si=abc",
        "spotify:playlist:second",
        "third",
    )

    assert playlists.for_liked_count(1) == "first"
    assert playlists.for_liked_count(5) == "first"
    assert playlists.for_liked_count(6) == "second"
    assert playlists.for_liked_count(17) == "second"
    assert playlists.for_liked_count(18) == "third"
