"""Freeze original raw Palace catalog qualification and first-marker parsing."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from spotipy import Spotify

from spotify_manager.routines import palace_of_memory as legacy


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/palace_catalog.json"
MAPPED = legacy.SpotifyAlbum("album", "album:album", "Artist", "Release", False, 1.0)


@dataclass(frozen=True)
class CatalogRows:
    """Supply one original catalog or first-track raw response.

    Args:
        response: Original raw payload.
    """

    response: object

    def search(self, **options: object) -> object:
        """Return original raw catalog search observations.

        Args:
            options: Original exact-artist album query options.

        Returns:
            Configured raw response.
        """
        assert options["type"] == "album"
        return self.response

    def album_tracks(self, identity: str, limit: int, offset: int) -> object:
        """Return original first-track paging observations.

        Args:
            identity: Original selected release identity.
            limit: Original fixed page size.
            offset: Original zero offset.

        Returns:
            Configured original raw response.
        """
        assert identity == "album" and limit == 50 and offset == 0
        return self.response


def _album_row(identity: object, artists: object) -> dict[str, object]:
    return {
        "id": identity,
        "uri": f"album:{identity}",
        "name": " Release ",
        "artists": artists,
    }


def inputs() -> list[dict[str, object]]:
    """Enumerate original search qualification and marker shape boundaries.

    Returns:
        Original raw input matrix.
    """
    result: list[dict[str, object]] = []
    payload: object
    for payload in (None, {}, {"albums": {}}, {"albums": {"items": []}}):
        result.append({"kind": "album", "payload": payload})
    _album_inputs(result)
    for payload in (None, {}, {"items": None}, {"items": []}):
        result.append({"kind": "track", "payload": payload})
    _track_inputs(result)
    return result


def _album_inputs(result: list[dict[str, object]]) -> None:
    artists: object
    for artists in (
        None,
        [],
        [None, {}],
        [{"name": "Other"}],
        [{"name": " ARTIST "}],
        [{"name": "Other"}, {"name": "Artist"}],
    ):
        result.append(
            {
                "kind": "album",
                "payload": {
                    "albums": {
                        "items": [
                            None,
                            {},
                            _album_row("one", artists),
                            _album_row("two", artists),
                        ]
                    }
                },
            }
        )
    for field in ("id", "uri", "name"):
        for value in (None, "", "  ", False, 5):
            row = _album_row("one", [{"name": "Artist"}])
            row[field] = value
            result.append({"kind": "album", "payload": {"albums": {"items": [row]}}})
    row = _album_row("wrong", [{"name": "Artist"}])
    row["name"] = "Unrelated Album"
    result.append({"kind": "album", "payload": {"albums": {"items": [row]}}})


def _track_inputs(result: list[dict[str, object]]) -> None:
    for field in ("id", "uri", "name"):
        for value in (None, "", "  ", False, 5):
            row: dict[str, object] = {"id": "one", "uri": "track:one", "name": " One "}
            row[field] = value
            result.append(
                {
                    "kind": "track",
                    "payload": {
                        "items": [
                            None,
                            {},
                            row,
                            {"id": "two", "uri": "track:two", "name": " Two "},
                        ]
                    },
                }
            )


def original_outcome(case: dict[str, object]) -> object:
    """Observe original catalog functions before extracting codecs and ranking.

    Args:
        case: Original raw boundary input.

    Returns:
        Complete original parsed result or translated error.
    """
    edge = CatalogRows(case["payload"])
    result: dict[str, object] = {}
    try:
        value = _selection(edge, cast(str, case["kind"]))
        result["result"] = asdict(value) if value is not None else None
    except legacy.PalaceOfMemoryDataError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    return json.loads(json.dumps(result))


def _selection(
    edge: CatalogRows, kind: str
) -> legacy.SpotifyAlbum | legacy.SpotifyFirstTrack | None:
    if kind == "album":
        return legacy.search_spotify_album(
            cast(Spotify, edge), "Artist", "Release", legacy._direct_retry
        )
    return legacy.load_first_track(cast(Spotify, edge), MAPPED, legacy._direct_retry)


def cases() -> list[dict[str, object]]:
    """Read immutable original raw catalog observations.

    Returns:
        Original raw input and complete outcome evidence.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))
