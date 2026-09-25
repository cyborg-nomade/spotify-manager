"""Differential contracts for the temporary synchronous integration adapters."""

import gzip
import json
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.album_review import AlbumReview
from spotify_manager.application.album_review import review_album
from spotify_manager.application.music import Track
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.bootstrap.listening import album_review_ports
from spotify_manager.bootstrap.listening import listening_history
from spotify_manager.bootstrap.listening import requeue_audit
from spotify_manager.bootstrap.listening import requeue_playlist
from spotify_manager.processors import library_lookups
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import requeue_for_a_dream


ALBUM = {"id": "album", "name": " Album ", "artists": [{"name": " Artist "}]}


def _track(identifier: object) -> dict[str, object]:
    return {"id": identifier, "name": " Track ", "uri": " spotify:track:track "}


def _client(tracks: list[object], statuses: object) -> Mock:
    client = Mock(spec=Spotify)
    client.album.return_value = ALBUM
    client.album_tracks.return_value = {"items": tracks, "next": None}
    client.current_user_saved_tracks_contains.return_value = statuses
    return client


def _payload(result: AlbumReview) -> dict[str, object]:
    tracks = []
    for track, liked in zip(result.tracks, result.liked, strict=True):
        tracks.append(
            {
                "name": track.name,
                "uri": track.uri,
                "liked": liked,
                "spotify_id": track.spotify_id,
            }
        )
    return {
        "album_name": result.album.name,
        "album_id": result.album.spotify_id,
        "artist_name": result.album.artist,
        "total_tracks": len(result.tracks),
        "liked_tracks": sum(result.liked),
        "threshold": result.threshold,
        "required_liked_tracks": result.assessment.required_liked_tracks,
        "liked_ratio": result.assessment.liked_ratio,
        "decision": result.assessment.decision,
        "tracks": tracks,
        "source": "spotify-live",
        "from_cache": False,
    }


@pytest.mark.parametrize(
    ("identifiers", "statuses"),
    [
        ([], []),
        ([None], []),
        (["x"], [True]),
        (["x", "x"], [True, False]),
        ([None, "x", "x"], [0, "truthy"]),
        ([123, "123"], [True, False]),
        ([False, "False"], [True]),
        ([0, "0"], [True]),
        ([None, "None"], [True]),
        (["", "x"], [True]),
    ],
)
def test_album_ports_match_legacy_values_and_calls(
    identifiers: list[object], statuses: list[object]
) -> None:
    """Compare typed results and complete SDK call traces to the legacy evaluator.

    Args:
        identifiers: Raw identifiers, including malformed values.
        statuses: Scripted membership observations.
    """
    tracks: list[object] = [_track(identifier) for identifier in identifiers]
    original = _client(tracks, statuses)
    adapted = _client(tracks, statuses)
    expected = library_lookups.evaluate_album_live(original, album_id="album")
    actual = review_album(*album_review_ports(adapted), album_id="album")
    assert _payload(actual) == expected.model_dump()
    assert adapted.mock_calls == original.mock_calls


@pytest.mark.parametrize("count", [0, 1, 19, 20, 21, 40, 41])
def test_membership_keeps_original_batch_boundaries(count: int) -> None:
    """Retain twenty-item batches, input ordering, and the empty-input shortcut.

    Args:
        count: Number of ordered identifiers.
    """
    tracks: list[object] = [_track(str(index)) for index in range(count)]
    client = _client(tracks, [])
    batches = []
    for start in range(0, count, 20):
        batches.append([True] * min(20, count - start))
    client.current_user_saved_tracks_contains.side_effect = batches
    result = review_album(*album_review_ports(client), album_id="album")
    expected = []
    for start in range(0, count, 20):
        expected.append([str(index) for index in range(start, min(start + 20, count))])
    calls = client.current_user_saved_tracks_contains.call_args_list
    assert [call.args[0] for call in calls] == expected
    assert sum(result.liked) == count


@pytest.mark.parametrize("response", [None, {}, [True, False], []])
def test_bad_membership_response_retains_exception(response: object) -> None:
    """Preserve status-response validation and its exception text.

    Args:
        response: Malformed membership response.
    """
    original = _client([_track("x")], response)
    adapted = _client([_track("x")], response)
    with pytest.raises(library_lookups.SpotifyLookupResponseError) as old:
        library_lookups.evaluate_album_live(original, album_id="album")
    with pytest.raises(type(old.value), match=str(old.value)):
        review_album(*album_review_ports(adapted), album_id="album")
    assert adapted.mock_calls == original.mock_calls


def test_album_pagination_preserves_filtered_items_and_page_order() -> None:
    """Retain page ordering and the original filtering of non-object entries."""
    client = _client([None, _track("a")], [True, False])
    client.album_tracks.return_value["next"] = "next"
    client.next.return_value = {"items": [_track("b")], "next": None}
    result = review_album(*album_review_ports(client), album_id="album")
    assert [track.spotify_id for track in result.tracks] == ["a", "b"]
    client.album_tracks.assert_called_once_with("album", limit=50)
    client.next.assert_called_once()


@pytest.mark.parametrize(
    "page",
    [None, {}, {"items": [], "next": "next"}, {"items": [{"id": "x"}], "next": None}],
)
def test_malformed_track_pages_keep_legacy_errors(page: object) -> None:
    """Reject malformed or incomplete track pages before reading membership.

    Args:
        page: Scripted malformed track page.
    """
    client = _client([], [])
    client.album_tracks.return_value = page
    with pytest.raises(library_lookups.SpotifyLookupResponseError):
        review_album(*album_review_ports(client), album_id="album")
    client.current_user_saved_tracks_contains.assert_not_called()


@pytest.mark.parametrize("status", [404, 429, 500])
def test_catalog_preserves_sdk_error_translation(status: int) -> None:
    """Keep missing-album translation and all other SDK exceptions unchanged.

    Args:
        status: Scripted Spotify HTTP status.
    """
    client = _client([], [])
    error = SpotifyException(status, -1, "scripted failure")
    client.album.side_effect = error
    expected = library_lookups.AlbumNotFoundError if status == 404 else SpotifyException
    with pytest.raises(expected) as caught:
        review_album(*album_review_ports(client), album_id="missing")
    assert caught.value is error or caught.value.__cause__ is error
    client.album_tracks.assert_not_called()


def test_catalog_search_uses_existing_exact_match_and_query() -> None:
    """Retain exact name matching and the existing search parameters."""
    client = _client([_track("x")], [True])
    client.search.return_value = {"albums": {"items": [ALBUM]}}
    result = review_album(*album_review_ports(client), name="Album", artist="Artist")
    assert result.album.spotify_id == "album"
    client.search.assert_called_once_with(
        q='album:"Album" artist:"Artist"', type="album", limit=10, offset=0
    )


@dataclass
class RetryRecorder:
    """Record retry boundaries while executing each operation exactly once.

    Args:
        descriptions: Ordered descriptions supplied by the existing adapter.
    """

    descriptions: list[str] = field(default_factory=list)

    def __call__(self, operation: Callable[[], object], description: str) -> object:
        """Execute one callable after recording its description.

        Args:
            operation: Existing transport operation.
            description: Human-readable retry boundary.

        Returns:
            The unmodified operation result; exceptions propagate unchanged.
        """
        self.descriptions.append(description)
        return operation()


def test_playlist_writes_keep_order_payloads_and_retry_descriptions() -> None:
    """Keep append-before-remove effects and their original retry messages."""
    client = Mock(spec=Spotify)
    recorder = RetryRecorder()
    retry: RetryCall = recorder
    playlists = requeue_playlist(client, retry)
    playlists.append("p", Track("next", "Next", "spotify:track:next"))
    playlists.remove("p", Track("old", "Old", "spotify:track:old"))
    assert [call[0] for call in client.mock_calls] == ["_post", "_delete"]
    client._post.assert_called_once_with(
        "playlists/p/items", payload={"uris": ["spotify:track:next"]}
    )
    client._delete.assert_called_once_with(
        "playlists/p/items", payload={"items": [{"uri": "spotify:track:old"}]}
    )
    assert recorder.descriptions == [
        "adding Next to Requeue for a Dream",
        "removing Old from Requeue for a Dream",
    ]


def test_playlist_write_failure_does_not_add_adapter_retries() -> None:
    """Propagate an ambiguous write failure without replaying the operation."""
    client = Mock(spec=Spotify)
    error = SpotifyException(500, -1, "accepted then disconnected")
    client._post.side_effect = error
    playlists = requeue_playlist(client, RetryRecorder())
    with pytest.raises(SpotifyException) as caught:
        playlists.append("p", Track("x", "X", "x"))
    assert caught.value is error
    client._post.assert_called_once()
    client._delete.assert_not_called()


def _playlist_track(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "name": identifier,
        "uri": f"spotify:track:{identifier}",
        "artists": [{"id": "artist", "name": "Artist"}],
        "album": {
            "id": "album",
            "name": "Album",
            "uri": "spotify:album:album",
            "album_type": "album",
            "release_date": "2020",
            "total_tracks": 2,
            "artists": [{"id": "artist", "name": "Artist"}],
        },
    }


def test_playlist_reads_use_original_parser_and_pagination() -> None:
    """Retain parsed duplicate markers and sequential page offsets."""
    client = Mock(spec=Spotify)
    client._get.side_effect = [
        {"items": [{"item": _playlist_track("x")}], "next": "next"},
        {"items": [{"item": _playlist_track("x")}], "next": None},
    ]
    tracks = requeue_playlist(client, RetryRecorder()).tracks("p")
    assert tracks == (Track("x", "x", "spotify:track:x"),) * 2
    assert client._get.call_args_list[0].kwargs == {"limit": 50, "offset": 0}
    assert client._get.call_args_list[1].kwargs == {"limit": 50, "offset": 1}


@pytest.mark.parametrize("compressed", [False, True])
def test_history_adapter_keeps_timezone_and_compressed_fallback(
    tmp_path: Path, compressed: bool
) -> None:
    """Preserve Berlin-local grouping and compressed export fallback behavior.

    Args:
        tmp_path: Isolated working directory.
        compressed: Whether only the gzip fallback is available.
    """
    path = tmp_path / "history.json"
    payload = json.dumps(
        {
            "scrobbles": [
                {"date": 1577919600000, "track": "First", "artist": "A", "album": "B"},
                {"date": 1577923200000, "track": "Second", "artist": "A", "album": "B"},
            ]
        }
    ).encode()
    if compressed:
        Path(f"{path}.gz").write_bytes(gzip.compress(payload))
    else:
        path.write_bytes(payload)
    actual = listening_history(path).by_date()
    expected = blast_from_past.load_scrobbles_by_date(path)
    assert actual == {day: tuple(events) for day, events in expected.items()}
    assert date(2020, 1, 2) in actual


def test_audit_adapter_keeps_existing_jsonl_bytes(tmp_path: Path) -> None:
    """Delay audit writes until invoked and retain their exact JSONL representation.

    Args:
        tmp_path: Isolated working directory.
    """
    summary = requeue_for_a_dream.RequeueForADreamSummary(
        datetime(2026, 9, 25, tzinfo=UTC), "p", False, "drop", 1, 0, artist="Ártist"
    )
    original, adapted = tmp_path / "original.jsonl", tmp_path / "adapted.jsonl"
    requeue_for_a_dream._append_log(summary, original)
    writer = requeue_audit(adapted)
    assert not adapted.exists()
    writer(summary)
    assert adapted.read_bytes() == original.read_bytes()


def test_audit_failure_keeps_original_error(tmp_path: Path) -> None:
    """Retain the original error when the audit destination cannot be written.

    Args:
        tmp_path: Isolated working directory.
    """
    parent = tmp_path / "file"
    parent.write_text("not a directory")
    summary = requeue_for_a_dream.RequeueForADreamSummary(
        datetime(2026, 9, 25, tzinfo=UTC), "p", False, "drop", 1, 0
    )
    with pytest.raises(requeue_for_a_dream.RequeueForADreamLogError):
        requeue_audit(parent / "log.jsonl")(summary)
