"""Freeze original exact-artist and popular-marker selection at raw boundaries."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from spotipy import Spotify

from spotify_manager.routines import something_old as legacy
from tests.support.something_old_run import ARTIST


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/golden_selection.json"
)


@dataclass(frozen=True)
class CatalogResponse:
    """Return one original raw response without an SDK or network.

    Args:
        response: Configured original catalog payload.
        choice: Configured ambiguity choice.
    """

    response: object
    choice: str

    def search(self, **options: object) -> object:
        """Return the configured original artist payload.

        Args:
            options: Original query options.

        Returns:
            Configured raw response.
        """
        assert options["type"] == "artist"
        return self.response

    def artist_top_tracks(self, artist: str) -> object:
        """Return the configured original popular-track payload.

        Args:
            artist: Original mapped artist identity.

        Returns:
            Configured raw response.
        """
        assert artist == ARTIST.spotify_id
        return self.response

    def choose(
        self, name: str, candidates: tuple[legacy.SpotifyArtistCandidate, ...]
    ) -> str:
        """Supply the original ambiguity choice.

        Args:
            name: Original expected spelling.
            candidates: Original exact matches in search order.

        Returns:
            Configured choice.
        """
        assert name and candidates
        return self.choice


def artist_row(identity: object, name: object = "Artist") -> dict[str, object]:
    """Build original raw artist facts with tolerant integer fields.

    Args:
        identity: Original raw identifier.
        name: Original raw display name.

    Returns:
        Complete original artist row.
    """
    return {
        "id": identity,
        "name": name,
        "uri": f"artist:{identity}",
        "popularity": True,
        "followers": {"total": -1},
    }


def track_row(identity: object, artist_rows: object) -> dict[str, object]:
    """Build original raw popular-track facts.

    Args:
        identity: Original raw track identity.
        artist_rows: Original ordered raw artist_rows.

    Returns:
        Complete raw track row.
    """
    return {
        "id": identity,
        "uri": f"track:{identity}",
        "name": " Track ",
        "album": {"name": " Album "},
        "artists": artist_rows,
    }


def inputs() -> list[dict[str, object]]:
    """Enumerate original malformed, ambiguity, credit and capacity boundaries.

    Returns:
        Complete original raw selection inputs.
    """
    rows: list[dict[str, object]] = []
    payload: object
    for payload in (None, {}, {"artists": {}}, {"artists": {"items": ()}}):
        rows.append({"kind": "artist", "payload": payload, "choice": "absent"})
    _artist_inputs(rows)
    for payload in (None, {}, {"tracks": ()}, {"tracks": []}):
        rows.append({"kind": "tracks", "payload": payload, "choice": ""})
    _track_inputs(rows)
    return rows


def _artist_inputs(rows: list[dict[str, object]]) -> None:
    for size in (0, 1, 2, 12):
        items: list[object] = [None, {}, artist_row("wrong", "Different")]
        for index in range(size):
            items.append(artist_row(str(index), " ARTIST " if index % 2 else "Artist"))
        for choice in ("absent", "quit", "0", "missing"):
            rows.append(
                {
                    "kind": "artist",
                    "payload": {"artists": {"items": items}},
                    "choice": choice,
                }
            )
    for value in (False, -1, 0, 1, "5", None):
        row = artist_row("one")
        row.update(popularity=value, followers={"total": value})
        rows.append(
            {
                "kind": "artist",
                "payload": {"artists": {"items": [row]}},
                "choice": "absent",
            }
        )


def _track_inputs(rows: list[dict[str, object]]) -> None:
    artist_rows: object
    for artist_rows in (
        None,
        [],
        [None, {}],
        [{"id": "other", "name": "Other"}],
        [{"id": "artist", "name": " Artist "}],
        [{"id": "other", "name": "Other"}, {"id": "artist", "name": "Artist"}],
    ):
        row = track_row("one", artist_rows)
        rows.append({"kind": "tracks", "payload": {"tracks": [row]}, "choice": ""})
    for size in (1, 9, 10, 11, 25):
        items: list[object] = [None, {}, track_row("wrong", [])]
        for index in range(size):
            row = track_row(str(index), [{"id": "artist", "name": "Artist"}])
            items.extend((row, row))
        rows.append({"kind": "tracks", "payload": {"tracks": items}, "choice": ""})


def original_outcome(case: dict[str, object]) -> object:
    """Observe the original facade before extracting selection rules.

    Args:
        case: Original raw input and optional ambiguity choice.

    Returns:
        JSON-compatible original values or translated error.
    """
    edge = CatalogResponse(case["payload"], cast(str, case["choice"]))
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _selection(edge, cast(str, case["kind"]))
    except legacy.SomethingOldSpotifyError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    return json.loads(json.dumps(outcome))


def _selection(edge: CatalogResponse, kind: str) -> object:
    if kind == "artist":
        chooser = None if edge.choice == "absent" else edge.choose
        artist = legacy.resolve_spotify_artist(
            cast(Spotify, edge), "Artist", chooser, legacy._direct_retry
        )
        return asdict(artist) if artist is not None else None
    tracks = legacy.select_spotify_top_tracks(
        cast(Spotify, edge), ARTIST, legacy._direct_retry
    )
    return [asdict(track) for track in tracks]


def cases() -> list[dict[str, object]]:
    """Read immutable original raw selection observations.

    Returns:
        Original inputs and observed outcomes.
    """
    records = cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))
    for record, original in zip(records, inputs(), strict=True):
        assert record["payload"] == json.loads(json.dumps(original["payload"]))
        record["payload"] = original["payload"]
    return records
