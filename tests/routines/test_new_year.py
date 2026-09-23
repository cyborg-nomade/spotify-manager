from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.routines import new_year
from spotify_manager.routines.blast_from_past import Scrobble


def play(
    artist="Artist", track="Song", album="Album", when="2025-06-01T12:00:00+02:00"
):
    return Scrobble(
        track, artist, album, int(datetime.fromisoformat(when).timestamp() * 1000)
    )


def test_rank_year_boundaries_duplicates_and_ties():
    result = new_year.rank_year(
        (
            play(when="2024-12-31T23:00:00+00:00"),
            play(artist="ARTIST"),
            play(),
            play(artist="Other", album=""),
            play(when="2025-12-31T23:00:00+00:00"),
            play(when="2024-12-31T22:59:59+00:00"),
        ),
        2025,
    )
    assert result["tracks"][0]["scrobbles"] == 3
    assert result["artists"][0]["scrobbles"] == 3
    assert len(result["albums"]) == 1
    assert result["albums"][0]["scrobbles"] == 3
    tied = new_year.rank_year((play(artist="Z"), play(artist="A")), 2025)
    assert [r["artist"] for r in tied["artists"]] == ["A", "Z"]


@pytest.fixture
def annual(monkeypatch):
    playlists = [
        SimpleNamespace(spotify_id="obs", name="Obsessions 2025"),
        SimpleNamespace(spotify_id="discoveries", name="Great Discoveries 2025"),
    ]
    contents = {"obs": ["spotify:track:obsession"], "memory": ["spotify:track:other"]}
    mutations = []
    sp = Mock()
    sp.current_user.return_value = {"id": "owner"}
    sp.track.return_value = {"artists": [{"id": "artist"}]}

    def create(user, name, **kwargs):
        identity = "chart" + str(len(playlists))
        playlists.append(SimpleNamespace(spotify_id=identity, name=name))
        mutations.append(("create", name))
        return {"id": identity}

    sp.user_playlist_create.side_effect = create

    def post(path, payload):
        identity = path.split("/")[1]
        items = contents.setdefault(identity, [])
        position = payload.get("position", len(items))
        items[position:position] = payload["uris"]
        mutations.append(("add", identity))

    sp._post.side_effect = post

    def put(path, payload):
        if "uris" in payload:
            contents[path.split("/")[1]] = list(payload["uris"])
            mutations.append(("chart", path))
            return
        items = contents[path.split("/")[1]]
        item = items.pop(payload["range_start"])
        items.insert(payload["insert_before"], item)
        mutations.append(("reorder", path))

    sp._put.side_effect = put
    monkeypatch.setattr(new_year.blast_from_past, "parse_playlist_id", lambda x: x)
    monkeypatch.setattr(new_year.queue_3, "parse_playlist_id", lambda x: x)
    monkeypatch.setattr(
        new_year.queue_3, "load_owned_playlists", lambda *args: tuple(playlists)
    )

    def load(sp, identity, retry):
        return tuple(
            SimpleNamespace(
                uri=uri,
                primary_artist_id="other" if uri.endswith("other") else "artist",
            )
            for uri in contents.get(identity, [])
        )

    monkeypatch.setattr(new_year.new_wine, "load_playlist_tracks", load)
    history = Mock(return_value=SimpleNamespace(history=(play(), play())))
    monkeypatch.setattr(new_year.scrobble_history, "refresh_scrobble_history", history)
    monkeypatch.setattr(
        new_year.blast_from_past,
        "search_spotify_matches",
        lambda *a: (SimpleNamespace(uri="spotify:track:song", track_similarity=1.0),),
    )
    monkeypatch.setattr(
        new_year.palace_of_memory, "search_spotify_album", lambda *a: object()
    )
    monkeypatch.setattr(
        new_year.palace_of_memory,
        "load_first_track",
        lambda *a: SimpleNamespace(uri="spotify:track:first"),
    )
    monkeypatch.setattr(
        new_year.something_old,
        "resolve_spotify_artist",
        lambda *a: SimpleNamespace(spotify_id="artist"),
    )
    imports = Mock()
    monkeypatch.setattr(new_year.queue_3, "import_previous_year_discoveries", imports)
    config = SimpleNamespace(
        blast_from_the_past_playlist="blast",
        palace_of_memory_playlist="palace",
        discography_memory_lane_playlist="memory",
        the_queue_3_playlist="queue3",
        lastfm_username="listener",
    )
    return SimpleNamespace(
        sp=sp,
        config=config,
        contents=contents,
        mutations=mutations,
        history=history,
        imports=imports,
        playlists=playlists,
    )


def run(annual, **kwargs):
    return new_year.run_new_year(
        annual.sp, Mock(), annual.config, year=2025, echo=lambda _: None, **kwargs
    )


def test_dry_run_resolves_every_step_without_writes(annual):
    before = get_state_service().snapshot()
    result = run(annual)
    assert result["dry_run"]
    assert result["plan"]["artists"][0]["uri"] == "spotify:track:song"
    assert not annual.mutations
    assert get_state_service().snapshot().revision == before.revision
    assert get_state_service().snapshot().document["namespaces"] == {}
    assert annual.history.call_args.kwargs["full_rebuild"]
    assert annual.history.call_args.kwargs["dry_run"]
    assert annual.imports.call_args.kwargs["dry_run"]


def test_live_all_five_steps_and_repeated_invocation(annual):
    result = run(annual, dry_run=False)
    assert result["done"] and len(result["completed"]) == 5
    assert annual.contents["blast"] == ["spotify:track:song", "spotify:track:obsession"]
    assert annual.contents["palace"] == ["spotify:track:first"]
    assert annual.contents["memory"][0] == "spotify:track:song"
    assert annual.imports.call_args.kwargs["active_year"] == 2026
    before = list(annual.mutations)
    assert run(annual, dry_run=False)["already_completed"]
    assert annual.mutations == before
    assert annual.history.call_count == 1


def test_partial_failure_resumes_saved_plan_without_duplicate_additions(annual):
    annual.imports.side_effect = RuntimeError("interrupted")
    with pytest.raises(RuntimeError, match="interrupted"):
        run(annual, dry_run=False)
    assert annual.contents["blast"] == ["spotify:track:song"]
    annual.imports.side_effect = None
    run(annual, dry_run=False)
    assert annual.contents["blast"] == ["spotify:track:song", "spotify:track:obsession"]
    assert annual.history.call_count == 1
    assert len([p for p in annual.playlists if p.name.startswith("top")]) == 2


def test_reconciliation_handles_write_succeeded_then_response_lost(annual):
    original = annual.sp._post.side_effect

    def fail(path, payload):
        original(path, payload)
        raise RuntimeError("lost response")

    annual.sp._post.side_effect = fail
    with pytest.raises(RuntimeError):
        run(annual, dry_run=False)
    annual.sp._post.side_effect = original
    run(annual, dry_run=False)
    chart = next(p for p in annual.playlists if p.name == "top 50 2025 tracks")
    assert annual.contents[chart.spotify_id] == ["spotify:track:song"]


def test_memory_reuses_and_moves_existing_artist_marker(annual):
    annual.contents["memory"] = ["spotify:track:other", "spotify:track:existing"]
    run(annual, dry_run=False)
    assert annual.contents["memory"] == [
        "spotify:track:existing",
        "spotify:track:other",
    ]
    annual.sp.track.assert_not_called()


def test_missing_source_stops_before_rebuild(annual):
    annual.playlists.pop(0)
    with pytest.raises(new_year.NewYearError, match="Obsessions"):
        run(annual, dry_run=False)
    annual.history.assert_not_called()
    assert not annual.mutations


def test_no_history_or_album_match_stops_before_spotify_writes(annual, monkeypatch):
    annual.history.return_value = SimpleNamespace(history=())
    with pytest.raises(new_year.NewYearError, match="No scrobbles"):
        run(annual)
    annual.history.return_value = SimpleNamespace(history=(play(),))
    monkeypatch.setattr(
        new_year.palace_of_memory, "search_spotify_album", lambda *a: None
    )
    with pytest.raises(new_year.NewYearError, match="album match"):
        run(annual, dry_run=False)
    assert not annual.mutations


def test_unresolved_track_stops_before_mutations(annual, monkeypatch):
    monkeypatch.setattr(
        new_year.blast_from_past, "search_spotify_matches", lambda *a: ()
    )
    with pytest.raises(new_year.NewYearError, match="track match"):
        run(annual, dry_run=False)
    assert not annual.mutations


def test_cancellation_preserves_state(annual):
    with pytest.raises(new_year.scrobble_history.ScrobbleHistoryCancelledError):
        run(annual, dry_run=False, cancel_check=lambda: True)
    assert not annual.mutations


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"years": []},
        {"years": {"oops": {}}},
        {"years": {"2025": {"completed": 2}}},
    ],
)
def test_invalid_state_rejected(raw):
    with pytest.raises(new_year.NewYearError):
        new_year.validate_state(raw)


def test_duplicate_chart_name_rejected():
    with pytest.raises(new_year.NewYearError, match="Multiple"):
        new_year._named_playlist(
            (
                SimpleNamespace(name="chart", spotify_id="a"),
                SimpleNamespace(name="chart", spotify_id="b"),
            ),
            "chart",
        )


def test_automatic_retry_rechecks_membership_and_playlist_creation(annual):
    original_add = annual.sp._post.side_effect
    original_create = annual.sp.user_playlist_create.side_effect
    lost = set()

    def add(path, payload):
        original_add(path, payload)
        if path not in lost:
            lost.add(path)
            raise RuntimeError("response lost")

    def create(user, name, **kwargs):
        result = original_create(user, name, **kwargs)
        if name not in lost:
            lost.add(name)
            raise RuntimeError("response lost")
        return result

    def retry(operation, description):
        try:
            return operation()
        except RuntimeError:
            return operation()

    annual.sp._post.side_effect = add
    annual.sp.user_playlist_create.side_effect = create
    run(annual, dry_run=False, retry_call=retry)
    assert annual.contents["blast"] == ["spotify:track:song", "spotify:track:obsession"]
    assert len([p for p in annual.playlists if p.name.startswith("top")]) == 2


def test_existing_chart_is_synchronized_instead_of_appended(annual):
    annual.playlists.append(
        SimpleNamespace(spotify_id="oldchart", name="top 50 2025 tracks")
    )
    annual.contents["oldchart"] = ["spotify:track:outdated"]
    run(annual, dry_run=False)
    assert annual.contents["oldchart"] == ["spotify:track:song"]


def test_reorder_retries_recalculate_positions(annual):
    annual.contents["memory"] = ["spotify:track:other", "spotify:track:existing"]
    original = annual.sp._put.side_effect
    failed = False

    def put(path, payload):
        nonlocal failed
        original(path, payload)
        if "range_start" in payload and not failed:
            failed = True
            raise RuntimeError("response lost")

    def retry(operation, description):
        try:
            return operation()
        except RuntimeError:
            return operation()

    annual.sp._put.side_effect = put
    run(annual, dry_run=False, retry_call=retry)
    assert annual.contents["memory"] == [
        "spotify:track:existing",
        "spotify:track:other",
    ]
