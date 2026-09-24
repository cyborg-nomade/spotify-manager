"""Reusable legacy fixtures; future use cases must satisfy the same recordings."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.processors import library_lookups
from spotify_manager.routines import analyse_library
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import the_queue
from tests.routines import test_analyse_library as analysis_fakes
from tests.routines import test_new_kids as kids_fakes
from tests.routines import test_new_wine as wine_fakes
from tests.routines import test_palace_of_memory as palace_fakes
from tests.routines import test_requeue_for_a_dream as requeue_fakes
from tests.routines import test_review_album_limits as album_fakes
from tests.routines import test_scrobble_history as history_fakes
from tests.routines import test_slow_listening as slow_fakes
from tests.routines import test_the_queue as queue_fakes
from tests.support.effects import Trace


@dataclass
class Scenario:
    run: Callable[[bool], object]
    remote: Callable[[], object]
    supports_dry_run: bool = True


def effects(patch, trace, spotify, module, *, audit="append_log", state="save_state"):
    for name in (
        "_post",
        "_delete",
        "current_user_saved_albums_add",
        "current_user_saved_albums_delete",
        "user_follow_artists",
    ):
        if hasattr(spotify, name):
            trace.watch(patch, spotify, name, f"spotify.{name}")
    for name, operation in ((state, "checkpoint"), (audit, "audit")):
        if hasattr(module, name):
            trace.watch(patch, module, name, operation)


def requeue(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    spotify, _, _ = requeue_fakes.configured_spotify()
    effects(patch, trace, spotify, requeue_for_a_dream, audit="_append_log")
    return Scenario(
        lambda dry: requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            dry_run=dry,
            log_path=root / "log.jsonl",
            echo=lambda message: trace.record("echo", "message", message),
        ),
        lambda: {
            "playlist": [track["id"] for track in spotify.playlist],
            "mutations": spotify.mutations,
        },
    )


def progression(patch, root, trace, *, wine):
    fixtures, module = (wine_fakes, new_wine) if wine else (slow_fakes, slow_listening)
    spotify = fixtures.FakeSpotify()
    release = fixtures.raw_release("album", "Album", artist_id="artist")
    tracks = [
        fixtures.raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 4)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["new" if wine else "slow"] = [tracks[0]]
    effects(patch, trace, spotify, module)
    options = fixtures.paths(root)

    def echo(message):
        return trace.record("echo", "message", message)

    if wine:

        def run(dry):
            return new_wine.flush_new_wine(
                spotify,
                "new",
                "sauv",
                trace.choices("choice"),
                dry_run=dry,
                echo=echo,
                **options,
            )
    else:

        def run(dry):
            return slow_listening.flush_slow_listening(
                spotify,
                "slow",
                trace.wrap("order", slow_fakes.default_order),
                completion_notifier=trace.choices("completion", None),
                dry_run=dry,
                echo=echo,
                **options,
            )

    return Scenario(
        run,
        lambda: {
            "playlists": {
                name: [t["id"] for t in tracks]
                for name, tracks in spotify.playlists.items()
            },
            "mutations": spotify.mutations,
        },
    )


def wine(patch, root, trace):
    return progression(patch, root, trace, wine=True)


def slow(patch, root, trace):
    return progression(patch, root, trace, wine=False)


def kids(patch, root, trace):
    spotify = kids_fakes.FakeSpotify()
    tracks = kids_fakes.seed_artist(
        spotify, "artist", release_count=2, tracks_per_release=3
    )
    spotify.playlists["new"] = [tracks[0][0]]
    spotify.liked_ids.add("artist-r1-t1")
    options = kids_fakes.isolated_paths(root)
    effects(patch, trace, spotify, new_kids, audit="append_event")
    return Scenario(
        lambda dry: new_kids.flush_new_kids(
            spotify,
            "new",
            "queue",
            "great",
            "unlucky",
            "newfoundland",
            trace.choices("choice"),
            year=2026,
            dry_run=dry,
            echo=lambda message: trace.record("echo", "message", message),
            **options,
        ),
        lambda: {
            "playlists": {
                name: [t["id"] for t in tracks]
                for name, tracks in spotify.playlists.items()
            },
            "mutations": spotify.mutations,
        },
    )


def queue(patch, root, trace):
    spotify = queue_fakes.FakeSpotify()
    tracks = queue_fakes.seed_artist(spotify, "artist")
    spotify.playlists["queue"] = [tracks[0]]
    effects(patch, trace, spotify, the_queue, audit="append_event")
    options = queue_fakes.isolated_paths(root)
    return Scenario(
        lambda dry: the_queue.flush_queue(
            spotify,
            queue_fakes.queue_playlists(),
            dry_run=dry,
            echo=lambda message: trace.record("echo", "message", message),
            **options,
        ),
        lambda: {
            "playlists": {
                name: [t["id"] for t in tracks]
                for name, tracks in spotify.playlists.items()
            },
            "mutations": spotify.mutations,
        },
    )


def album(patch, root, trace):
    spotify = album_fakes.FakeSpotify(
        saved_tracks={"t1"},
        album_tracks=[
            {"id": f"t{i}", "name": f"Track {i}", "uri": f"spotify:track:t{i}"}
            for i in range(1, 4)
        ],
    )
    patch.setattr(
        spotify,
        "album",
        lambda identity: {
            "id": identity,
            "name": "OK Computer",
            "artists": [{"id": "art1", "name": "Radiohead"}],
        },
    )
    trace.watch(patch, spotify, "album", "spotify.album")
    trace.watch(patch, spotify, "album_tracks", "spotify.album_tracks")
    trace.watch(
        patch, spotify, "current_user_saved_tracks_contains", "spotify.contains"
    )
    return Scenario(
        lambda dry: library_lookups.evaluate_album_live(spotify, album_id="alb1"),
        lambda: {"deleted": spotify.deleted, "followed": spotify.followed},
        supports_dry_run=False,
    )


def history(patch, root, trace):
    history_fakes.write_export(root / "lastfm.json")
    history_fakes.write_legacy_delta(root / "recent.jsonl")
    lastfm = history_fakes.FakeLastFm(
        (LastFmRecentTrack("Live Artist", "Live Track", "Live Album", 3),)
    )
    trace.watch(patch, lastfm, "recent_tracks", "lastfm.read")
    for name, operation in (
        ("_write_export_atomic", "mirror"),
        ("_append_log", "audit"),
    ):
        trace.watch(patch, scrobble_history, name, operation)
    return Scenario(
        lambda dry: scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username="man-et-arms",
            export_path=root / "lastfm.json",
            legacy_delta_path=root / "recent.jsonl",
            backup_dir=root / "backups",
            log_path=root / "log.jsonl",
            dry_run=dry,
            now=datetime(2026, 9, 24, 12, tzinfo=UTC),
        ),
        lambda: {"lastfm_calls": lastfm.calls},
    )


def palace(patch, root, trace):
    palace_fakes.write_albums(root / "albums.json")
    palace_fakes.write_history(root / "history.json")
    spotify = palace_fakes.FakeSpotify()
    # Extend the existing recording fake so reads see accepted mutations on restart.
    original = spotify._post

    def post(path, payload):
        result = original(path, payload)
        spotify.playlist_tracks.extend(
            {"id": uri.rsplit(":", 1)[-1], "uri": uri} for uri in payload["uris"]
        )
        return result

    patch.setattr(spotify, "_post", post)
    effects(patch, trace, spotify, palace_of_memory, audit="_append_log")
    trace.watch(patch, palace_of_memory, "_append_refresh_log", "mirror.audit")
    return Scenario(
        lambda dry: palace_of_memory.fill_palace_of_memory(
            spotify,
            "palace",
            today=date(2026, 8, 4),
            dry_run=dry,
            albums_path=root / "albums.json",
            scrobbles_path=root / "history.json",
            state_path=root / "state.json",
            log_path=root / "log.jsonl",
            album_backups_dir=root / "backups",
            album_refresh_log_path=root / "refresh.jsonl",
            random_index_reader=trace.wrap("random", palace_fakes.fixed_random_indexes),
            echo=lambda message: trace.record("echo", "message", message),
        ),
        lambda: {"playlist": spotify.playlist_tracks, "posts": spotify.posts},
    )


def analysis(patch, root, trace):
    spotify = analysis_fakes.FakeSpotify(
        albums=[analysis_fakes.album("a")],
        tracks=[analysis_fakes.track(str(index)) for index in range(11)],
        artists=[analysis_fakes.artist("artist")],
    )
    patch.setattr(analyse_library, "new_run_id", lambda: "fixture-run")
    for name, operation in (
        ("write_json_atomic", "checkpoint"),
        ("write_models", "mirror"),
        ("append_event", "audit"),
    ):
        trace.watch(patch, analyse_library, name, operation)
    for name in (
        "current_user_saved_albums",
        "current_user_saved_tracks",
        "current_user_followed_artists",
    ):
        trace.watch(patch, spotify, name, f"spotify.{name}")
    return Scenario(
        lambda dry: analyse_library.analyse_library_sync_routine(
            spotify,
            paths=analysis_fakes.paths_for(root, "sync"),
            echo=lambda message: trace.record("echo", "message", message),
            sleep=trace.choices("sleep"),
        ),
        lambda: {
            "album_offsets": spotify.album_calls,
            "track_offsets": spotify.track_calls,
            "artist_cursors": spotify.artist_calls,
        },
        supports_dry_run=False,
    )


FACTORIES = {
    "album": album,
    "requeue": requeue,
    "slow": slow,
    "wine": wine,
    "kids": kids,
    "queue": queue,
    "history": history,
    "palace": palace,
    "analysis": analysis,
}


def review(patch, root, trace):
    """Retain follow -> prompt -> Spotify removal -> mirror -> audit ordering."""
    import json

    from spotify_manager import loaders_savers
    from spotify_manager.routines import review_album_limits

    spotify = album_fakes.FakeSpotify(saved_tracks={"t1"})
    for name, filename, value in (
        ("TOTAL_ALBUMS_NEW_PATH", "albums.json", [album_fakes._album().model_dump()]),
        ("YOUR_LIBRARY_PATH", "library.json", album_fakes._library().model_dump()),
        ("TOTAL_ARTISTS_PATH", "artists.json", []),
        (
            "STATS_HISTORY_PATH",
            "stats.json",
            {
                review_album_limits.current_stats_history_key(): (
                    album_fakes._stats_report().model_dump()
                )
            },
        ),
    ):
        path = root / filename
        path.write_text(json.dumps(value))
        patch.setattr(loaders_savers, name, path)
    effects(
        patch,
        trace,
        spotify,
        review_album_limits,
        audit="append_removed_album_log",
        state="save_review_decisions",
    )
    for name in (
        "save_total_albums_new_file",
        "save_total_artists_file",
        "save_stats_history",
    ):
        trace.watch(patch, review_album_limits, name, f"mirror.{name}")
    answers = trace.choices("prompt", "r", "r")
    return Scenario(
        lambda dry: review_album_limits.review_album_limits(
            spotify,
            action_reader=answers,
            use_cache=False,
            echo=lambda message: trace.record("echo", "message", message),
            log_path=root / "removed.jsonl",
            decisions_path=root / "decisions.json",
        ),
        lambda: {"deleted": spotify.deleted, "followed": spotify.followed},
        supports_dry_run=False,
    )


def upload(patch, root, trace):
    from spotify_manager.routines import upload_library_files
    from tests.routines.test_upload_library_files import FakeHfApi
    from tests.routines.test_upload_library_files import write_json

    write_json(root / "YourLibrary.json", {"tracks": [], "albums": [], "artists": []})
    api = FakeHfApi()
    trace.watch(patch, api, "create_commit", "hub.commit")
    trace.watch(patch, api, "list_repo_files", "hub.list")

    def run(dry):
        plan = upload_library_files.prepare_library_files_upload(
            include_lastfm=False, files_dir=root, repo_id="fixture/space"
        )
        return plan if dry else upload_library_files.upload_library_files(plan, api=api)

    return Scenario(
        run, lambda: {"operations": api.operations, "message": api.commit_message}
    )


def release(patch, root, trace):
    from spotify_manager.routines import release_check
    from tests.routines import test_release_check as release_fakes

    artist = release_check.RankedArtist("artist", "Artist", 200, 1)
    history_dry_runs = []
    release_fakes.patch_history_and_ranking(patch, (artist,), history_dry_runs)
    trace.watch(patch, scrobble_history, "refresh_scrobble_history", "history.refresh")
    spotify = release_fakes.FakeSpotify()
    spotify.artist_results = {
        "Artist": [release_fakes.raw_artist("artist-id", "Artist")]
    }
    spotify.catalogs = {
        "artist-id": [
            release_fakes.raw_release(
                "album", "Album", "artist-id", "Artist", "2026-08-05"
            )
        ]
    }
    spotify.release_tracks = {
        "album": [release_fakes.raw_track("track", "Opener", "artist-id", "Artist")]
    }
    effects(patch, trace, spotify, release_check, audit="append_event")
    return Scenario(
        lambda dry: release_check.run_release_check(
            spotify,
            None,
            release_check.ReleaseCheckPlaylists("wine", "vintage"),
            expected_username="listener",
            dry_run=dry,
            state_path=root / "state.json",
            log_path=root / "log.jsonl",
            now=datetime(2026, 8, 6, tzinfo=UTC),
            export_path=root / "history.json",
            legacy_delta_path=root / "recent.jsonl",
            backup_dir=root / "backups",
            history_log_path=root / "history-log.jsonl",
        ),
        lambda: {
            "posts": spotify.posts,
            "puts": spotify.puts,
            "history_dry_runs": history_dry_runs,
        },
    )


FACTORIES.update(review=review, upload=upload, release=release)
