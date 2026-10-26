from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from functools import partialmethod
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.routines import new_year
from spotify_manager.routines.blast_from_past import Scrobble
from tests.support.history_dependencies import annual_discoveries
from tests.support.history_dependencies import annual_history
from tests.support.runtime_resources import CancellationFlag
from tests.support.runtime_resources import DiscardMessages
from tests.support.runtime_resources import RetryRuntimeOnce


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
def annual(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Build the original annual SDK, history and mutation observations.

    Args:
        monkeypatch: Scoped external-boundary substitutions.

    Returns:
        Annual inputs and accepted effect observations.
    """
    memory = AnnualMemory()
    sp = _annual_spotify(memory)
    _patch_annual_catalog(monkeypatch, memory)
    history = Mock(return_value=SimpleNamespace(history=(play(), play())))
    monkeypatch.setattr(HistoryRefresh, "run", partialmethod(annual_history, history))
    imports = Mock()
    monkeypatch.setattr(
        AnnualDiscoveries, "run", partialmethod(annual_discoveries, imports)
    )
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
        contents=memory.contents,
        mutations=memory.mutations,
        history=history,
        imports=imports,
        playlists=memory.playlists,
        memory=memory,
    )


def run(
    annual: SimpleNamespace,
    *,
    dry_run: bool = True,
    retry_call: Retry | None = None,
    cancel_check: CancellationState | None = None,
) -> dict[str, Any]:
    """Execute the original annual fixture through its public compatibility entry.

    Args:
        annual: Original playlist, history and accepted-effect observations.
        dry_run: Original preview behavior.
        retry_call: Optional named request retry policy.
        cancel_check: Optional named cancellation state.

    Returns:
        Original public JSON-compatible result.
    """
    return new_year.run_new_year(
        annual.sp,
        Mock(),
        annual.config,
        year=2025,
        echo=DiscardMessages(),
        dry_run=dry_run,
        retry_call=retry_call,
        cancel_check=cancel_check,
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


def test_cancellation_preserves_state(annual: SimpleNamespace) -> None:
    """Cancellation preserves state.

    Args:
        annual: Original annual playlist and accepted-effect fixture.
    """
    with pytest.raises(new_year.scrobble_history.ScrobbleHistoryCancelledError):
        run(annual, dry_run=False, cancel_check=CancellationFlag(True))
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


def test_automatic_retry_rechecks_membership_and_playlist_creation(
    annual: SimpleNamespace,
) -> None:
    """Automatic retry rechecks membership and playlist creation.

    Args:
        annual: Original annual playlist and accepted-effect fixture.
    """
    responses = LostAnnualResponses(annual.memory)
    annual.sp._post.side_effect = responses.post
    annual.sp.user_playlist_create.side_effect = responses.create
    run(annual, dry_run=False, retry_call=RetryRuntimeOnce())
    assert annual.contents["blast"] == ["spotify:track:song", "spotify:track:obsession"]
    assert len([p for p in annual.playlists if p.name.startswith("top")]) == 2


def test_existing_chart_is_synchronized_instead_of_appended(annual):
    annual.playlists.append(
        SimpleNamespace(spotify_id="oldchart", name="top 50 2025 tracks")
    )
    annual.contents["oldchart"] = ["spotify:track:outdated"]
    run(annual, dry_run=False)
    assert annual.contents["oldchart"] == ["spotify:track:song"]


def test_reorder_retries_recalculate_positions(annual: SimpleNamespace) -> None:
    """Reorder retries recalculate positions.

    Args:
        annual: Original annual playlist and accepted-effect fixture.
    """
    annual.contents["memory"] = ["spotify:track:other", "spotify:track:existing"]
    response = LostAnnualReorder(annual.memory)
    annual.sp._put.side_effect = response.put
    run(annual, dry_run=False, retry_call=RetryRuntimeOnce())
    assert annual.contents["memory"] == [
        "spotify:track:existing",
        "spotify:track:other",
    ]


def _annual_playlists() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(spotify_id="obs", name="Obsessions 2025"),
        SimpleNamespace(spotify_id="discoveries", name="Great Discoveries 2025"),
    ]


def _annual_contents() -> dict[str, list[str]]:
    return {"obs": ["spotify:track:obsession"], "memory": ["spotify:track:other"]}


@dataclass
class AnnualMemory:
    """Hold accepted SDK effects for annual retry tests.

    Args:
        playlists: Existing and newly created playlists.
        contents: Current ordered playlist contents.
        mutations: Accepted SDK writes in execution order.
    """

    playlists: list[SimpleNamespace] = field(default_factory=_annual_playlists)
    contents: dict[str, list[str]] = field(default_factory=_annual_contents)
    mutations: list[tuple[str, str]] = field(default_factory=list)

    def create(self, user: str, name: str, **kwargs: object) -> dict[str, str]:
        """Accept one SDK playlist creation.

        Args:
            user: Original playlist owner.
            name: Requested playlist name.
            **kwargs: Other SDK creation options.

        Returns:
            Newly assigned playlist identity.
        """
        identity = "chart" + str(len(self.playlists))
        self.playlists.append(SimpleNamespace(spotify_id=identity, name=name))
        self.mutations.append(("create", name))
        return {"id": identity}

    def post(self, path: str, payload: dict[str, Any]) -> None:
        """Accept one SDK track insertion.

        Args:
            path: SDK request path.
            payload: External SDK write payload.
        """
        identity = path.split("/")[1]
        items = self.contents.setdefault(identity, [])
        position = payload.get("position", len(items))
        items[position:position] = payload["uris"]
        self.mutations.append(("add", identity))

    def put(self, path: str, payload: dict[str, Any]) -> None:
        """Accept one SDK chart replacement or reorder.

        Args:
            path: SDK request path.
            payload: External SDK write payload.
        """
        if "uris" in payload:
            self.contents[path.split("/")[1]] = list(payload["uris"])
            self.mutations.append(("chart", path))
            return
        items = self.contents[path.split("/")[1]]
        item = items.pop(payload["range_start"])
        items.insert(payload["insert_before"], item)
        self.mutations.append(("reorder", path))

    def owned(self, *args: object) -> tuple[SimpleNamespace, ...]:
        """Read playlists including accepted creations.

        Args:
            *args: Original SDK query arguments.

        Returns:
            Current owned playlists in creation order.
        """
        return tuple(self.playlists)

    def tracks(
        self, spotify: object, identity: str, retry: Retry
    ) -> tuple[SimpleNamespace, ...]:
        """Read accepted playlist membership.

        Args:
            spotify: Original SDK client.
            identity: Requested playlist.
            retry: Original retry policy.

        Returns:
            Current ordered track observations.
        """
        tracks = []
        for uri in self.contents.get(identity, []):
            artist_id = "other" if uri.endswith("other") else "artist"
            tracks.append(SimpleNamespace(uri=uri, primary_artist_id=artist_id))
        return tuple(tracks)


def _annual_spotify(memory: AnnualMemory) -> Mock:
    sp = Mock()
    sp.current_user.return_value = {"id": "owner"}
    sp.track.return_value = {"artists": [{"id": "artist"}]}
    sp.user_playlist_create.side_effect = memory.create
    sp._post.side_effect = memory.post
    sp._put.side_effect = memory.put
    return sp


def _playlist_identity(value: str) -> str:
    return value


def _patch_annual_catalog(
    monkeypatch: pytest.MonkeyPatch, memory: AnnualMemory
) -> None:
    monkeypatch.setattr(
        new_year.blast_from_past, "parse_playlist_id", _playlist_identity
    )
    monkeypatch.setattr(new_year.queue_3, "parse_playlist_id", _playlist_identity)
    monkeypatch.setattr(new_year.queue_3, "load_owned_playlists", memory.owned)
    monkeypatch.setattr(new_year.new_wine, "load_playlist_tracks", memory.tracks)
    monkeypatch.setattr(
        new_year.blast_from_past,
        "search_spotify_matches",
        Mock(
            return_value=(
                SimpleNamespace(uri="spotify:track:song", track_similarity=1.0),
            )
        ),
    )
    monkeypatch.setattr(
        new_year.palace_of_memory, "search_spotify_album", Mock(return_value=object())
    )
    monkeypatch.setattr(
        new_year.palace_of_memory,
        "load_first_track",
        Mock(return_value=SimpleNamespace(uri="spotify:track:first")),
    )
    monkeypatch.setattr(
        new_year.something_old,
        "resolve_spotify_artist",
        Mock(return_value=SimpleNamespace(spotify_id="artist")),
    )


@dataclass
class LostAnnualResponses:
    """Lose the first response after accepting each add or creation.

    Args:
        memory: Accepted SDK effects.
        lost: Request paths and playlist names whose responses were lost.
    """

    memory: AnnualMemory
    lost: set[str] = field(default_factory=set)

    def post(self, path: str, payload: dict[str, Any]) -> None:
        """Accept an add before losing its first response.

        Args:
            path: SDK request path.
            payload: External SDK write payload.

        Raises:
            RuntimeError: After the first accepted write at each path.
        """
        self.memory.post(path, payload)
        if path not in self.lost:
            self.lost.add(path)
            raise RuntimeError("response lost")

    def create(self, user: str, name: str, **kwargs: object) -> dict[str, str]:
        """Accept a creation before losing its first response.

        Args:
            user: Original playlist owner.
            name: Requested playlist name.
            **kwargs: Other SDK creation options.

        Returns:
            Created playlist identity on a repeated request.

        Raises:
            RuntimeError: After the first accepted creation for each name.
        """
        result = self.memory.create(user, name, **kwargs)
        if name not in self.lost:
            self.lost.add(name)
            raise RuntimeError("response lost")
        return result


@dataclass
class LostAnnualReorder:
    """Lose the first response after accepting a reorder.

    Args:
        memory: Accepted SDK effects.
        failed: Whether the one lost response has occurred.
    """

    memory: AnnualMemory
    failed: bool = False

    def put(self, path: str, payload: dict[str, Any]) -> None:
        """Accept an update before losing the first reorder response.

        Args:
            path: SDK request path.
            payload: External SDK write payload.

        Raises:
            RuntimeError: After the first accepted reorder only.
        """
        self.memory.put(path, payload)
        if "range_start" in payload and not self.failed:
            self.failed = True
            raise RuntimeError("response lost")
