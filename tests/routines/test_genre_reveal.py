"""Tests for file-backed Genre Reveal progress."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from spotify_manager.routines import genre_reveal


SOURCE_PLAYLIST_ID = "6f8oAWcmpEcXrbnbOpnfqT"
PRIMARY_PAGE = f"""
<html>
  <a href="https://open.spotify.com/playlist/intro123"
     title="listen to a shorter introduction to this genre">intro</a>
  <a href="https://open.spotify.com/playlist/{SOURCE_PLAYLIST_ID}"
     title="listen to The Sound of Kerkkoor on Spotify">playlist</a>
  <a href="https://open.spotify.com/playlist/pulse123"
     title="listen to this genre's fans' current favorites">pulse</a>
</html>
"""
TRACK_URIS = tuple(f"spotify:track:{index:022d}" for index in range(12))


class FakeSpotify:
    """Small Spotify stand-in for library and playlist writes."""

    def __init__(self, existing_track_ids: tuple[str, ...] = ()) -> None:
        self.existing_track_ids = existing_track_ids
        self.puts: list[tuple[str, object]] = []
        self.posts: list[tuple[str, object]] = []

    def _get(
        self,
        path: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        assert path == "playlists/destination/items"
        ids = self.existing_track_ids[offset : offset + limit]
        return {
            "items": [{"item": {"id": spotify_id}} for spotify_id in ids],
            "total": len(self.existing_track_ids),
            "next": None,
        }

    def _put(self, path: str, *, args: object) -> None:
        self.puts.append((path, args))

    def _post(self, path: str, *, payload: object) -> None:
        self.posts.append((path, payload))


def page_reader(url: str) -> str:
    """Return deterministic Every Noise and Spotify embed fixtures."""
    if "everynoise.com" in url:
        return PRIMARY_PAGE
    if "open.spotify.com/embed/playlist" in url:
        return " ".join((*TRACK_URIS, TRACK_URIS[0]))
    raise AssertionError(f"Unexpected URL: {url}")


def test_missing_state_file_returns_empty_progress(tmp_path: Path) -> None:
    state = genre_reveal.load_genre_reveal_state(tmp_path / "missing.json")

    assert state.completed == []
    assert state.hide_done is False
    assert state.updated_at is None


def test_state_round_trip_is_timestamped_and_deduplicated(tmp_path: Path) -> None:
    path = tmp_path / "genre-state.json"
    update = genre_reveal.GenreRevealStateUpdate(
        completed=["ambient", "jazz", "ambient"],
        hide_done=True,
    )

    saved = genre_reveal.save_genre_reveal_state(update, path)
    loaded = genre_reveal.load_genre_reveal_state(path)

    assert saved.completed == ["ambient", "jazz"]
    assert saved.updated_at is not None
    assert loaded == saved
    assert not path.with_suffix(".json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_state_replacement_keeps_a_restorable_backup(tmp_path: Path) -> None:
    path = tmp_path / "genre-state.json"
    first = genre_reveal.save_genre_reveal_state(
        genre_reveal.GenreRevealStateUpdate(completed=["ambient"]),
        path,
    )

    second = genre_reveal.save_genre_reveal_state(
        genre_reveal.GenreRevealStateUpdate(completed=["ambient", "jazz"]),
        path,
    )

    backups = list((tmp_path / "genre-state_backups").glob("*.json"))
    assert second.completed == ["ambient", "jazz"]
    assert len(backups) == 1
    assert genre_reveal.GenreRevealState.model_validate_json(
        backups[0].read_text(encoding="utf-8")
    ) == first


def test_identical_state_does_not_replace_or_back_up(tmp_path: Path) -> None:
    path = tmp_path / "genre-state.json"
    update = genre_reveal.GenreRevealStateUpdate(completed=["ambient"])
    first = genre_reveal.save_genre_reveal_state(update, path)

    second = genre_reveal.save_genre_reveal_state(update, path)

    assert second == first
    assert not (tmp_path / "genre-state_backups").exists()


@pytest.mark.parametrize("slug", ["", "two words", " padded", "x" * 257])
def test_invalid_completed_slug_is_rejected(slug: str) -> None:
    with pytest.raises(ValidationError):
        genre_reveal.GenreRevealStateUpdate(completed=[slug])


def test_invalid_persisted_state_has_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "genre-state.json"
    path.write_text('{"completed": ["two words"]}', encoding="utf-8")

    with pytest.raises(
        genre_reveal.GenreRevealStateError,
        match="Genre-reveal state is invalid",
    ):
        genre_reveal.load_genre_reveal_state(path)


def test_preserved_route_can_select_first_incomplete_genre() -> None:
    route = genre_reveal.load_genre_route()
    state = genre_reveal.GenreRevealState(completed=["kerkkoor"])

    selected = genre_reveal.first_incomplete_genre(state)

    assert len(route) == 6_132
    assert route[0].slug == "kerkkoor"
    assert route[-1].slug == "rominimal"
    assert selected == genre_reveal.GenreRouteEntry(
        name="cathedral choir",
        slug="cathedralchoir",
        position=2,
    )


def test_discovers_primary_playlist_instead_of_intro_or_pulse() -> None:
    preview = genre_reveal.discover_genre_source(
        "kerkkoor",
        "kerkkoor",
        page_reader,
    )

    assert preview.source_playlist_id == SOURCE_PLAYLIST_ID
    assert preview.source_playlist_uri == f"spotify:playlist:{SOURCE_PLAYLIST_ID}"
    assert preview.every_noise_url.endswith("engenremap-kerkkoor.html")


def test_source_requires_ten_public_embed_tracks() -> None:
    def short_page_reader(url: str) -> str:
        if "everynoise.com" in url:
            return PRIMARY_PAGE
        return " ".join(TRACK_URIS[:9])

    with pytest.raises(
        genre_reveal.GenreRevealSourceError,
        match="did not expose the first 10 tracks",
    ):
        genre_reveal.load_genre_playlist_source(
            "kerkkoor",
            "kerkkoor",
            short_page_reader,
        )


def test_process_saves_source_adds_only_missing_tracks_and_logs(
    tmp_path: Path,
) -> None:
    existing_id = TRACK_URIS[1].rsplit(":", maxsplit=1)[-1]
    spotify = FakeSpotify(existing_track_ids=(existing_id,))
    log_path = tmp_path / "genre-reveal.jsonl"

    result = genre_reveal.process_next_genre(
        spotify,  # type: ignore[arg-type]
        "kerkkoor",
        "kerkkoor",
        "destination",
        log_path=log_path,
        page_reader=page_reader,
    )

    assert result.source_track_uris == list(TRACK_URIS[:10])
    assert result.already_present_track_uris == [TRACK_URIS[1]]
    assert result.added_track_uris == [
        uri for uri in TRACK_URIS[:10] if uri != TRACK_URIS[1]
    ]
    assert spotify.puts == [
        (
            "me/library",
            {"uris": f"spotify:playlist:{SOURCE_PLAYLIST_ID}"},
        )
    ]
    assert spotify.posts == [
        (
            "playlists/destination/items",
            {"uris": result.added_track_uris},
        )
    ]
    log_record = json.loads(log_path.read_text(encoding="utf-8"))
    assert log_record["slug"] == "kerkkoor"
    assert log_record["added_track_uris"] == result.added_track_uris
