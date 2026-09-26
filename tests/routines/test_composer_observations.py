"""Freeze owner discovery and paging before moving the integration boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines.composer_playlists import ComposerPlaylistError
from spotify_manager.routines.composer_playlists import OwnedPlaylist
from spotify_manager.routines.composer_playlists import load_owned_playlists


def _raw(
    spotify_id: str, owner: object = "owner", total: object = 3
) -> dict[str, object]:
    return {
        "id": spotify_id,
        "name": f" {spotify_id} ",
        "owner": {"id": owner},
        "tracks": {"total": total},
    }


def _retry(operation: Callable[[], object], description: str) -> object:
    return operation()


@dataclass
class PlaylistPages:
    """Serve scripted pages and retain each requested page boundary.

    Args:
        pages: Responses in request order.
        calls: Observed limit and offset pairs.
    """

    pages: list[object]
    calls: list[tuple[int, int]] = field(default_factory=list)

    def current_user_playlists(self, limit: int, offset: int) -> object:
        """Read the next page.

        Args:
            limit: Requested page size.
            offset: Requested starting offset.

        Returns:
            The next scripted payload.
        """
        self.calls.append((limit, offset))
        return self.pages.pop(0)


def test_paging_retains_duplicates_and_anchor_owner_selection() -> None:
    """The first usable anchor controls ownership, with next OR total paging."""
    pages = PlaylistPages(
        [
            {"items": [None, _raw("anchor", ""), _raw("other", "foreign")], "total": 5},
            {"items": [_raw("anchor"), _raw("same")], "next": "next"},
            {"items": [_raw("same", total=True), _raw("text", total="7")], "total": 1},
        ]
    )
    result = load_owned_playlists(cast(Spotify, pages), _retry, frozenset({"anchor"}))
    assert result == (
        OwnedPlaylist("anchor", "anchor", 3),
        OwnedPlaylist("same", "same", 3),
        OwnedPlaylist("same", "same", 1),
        OwnedPlaylist("text", "text", 0),
    )
    assert pages.calls == [(50, 0), (50, 3), (50, 5)]


@pytest.mark.parametrize("payload", [None, [], {}, {"items": None}, {"items": ()}])
def test_invalid_page_fails_before_another_read(payload: object) -> None:
    """Malformed pages retain the boundary error.

    Args:
        payload: Invalid Spotify response.
    """
    pages = PlaylistPages([payload])
    with pytest.raises(ComposerPlaylistError, match="invalid user playlist data"):
        load_owned_playlists(cast(Spotify, pages), _retry, frozenset({"anchor"}))
    assert pages.calls == [(50, 0)]


@pytest.mark.parametrize("paging", [{"next": "more"}, {"total": 1}])
def test_empty_page_with_more_results_fails(paging: dict[str, object]) -> None:
    """An empty nonfinal page must not spin forever.

    Args:
        paging: Either legacy indicator that more results remain.
    """
    pages = PlaylistPages([{"items": [], **paging}])
    with pytest.raises(ComposerPlaylistError, match="empty user-playlist page"):
        load_owned_playlists(cast(Spotify, pages), _retry, frozenset({"anchor"}))


@pytest.mark.parametrize(
    "items",
    [
        [],
        [None],
        [_raw("anchor", " ")],
        [_raw("other")],
        [{"id": "anchor", "owner": []}],
    ],
)
def test_missing_owner_anchor_fails(items: list[object]) -> None:
    """A name match cannot establish which playlists the account owns.

    Args:
        items: Responses without a usable configured owner anchor.
    """
    pages = PlaylistPages([{"items": items}])
    with pytest.raises(
        ComposerPlaylistError, match="Could not establish playlist ownership"
    ):
        load_owned_playlists(cast(Spotify, pages), _retry, frozenset({"anchor"}))


def test_malformed_and_foreign_playlists_are_filtered_tolerantly() -> None:
    """Only complete owned records survive, without normalizing owner whitespace."""
    pages = PlaylistPages(
        [
            {
                "items": [
                    _raw("anchor"),
                    None,
                    {},
                    _raw("foreign", "foreign"),
                    _raw("padded", "owner "),
                    {**_raw("blank"), "name": " "},
                    _raw(" "),
                    {**_raw("missing-tracks"), "tracks": None},
                    _raw("negative", total=-2),
                ]
            }
        ]
    )
    result = load_owned_playlists(cast(Spotify, pages), _retry, frozenset({"anchor"}))
    assert result == (
        OwnedPlaylist("anchor", "anchor", 3),
        OwnedPlaylist("missing-tracks", "missing-tracks", 0),
        OwnedPlaylist("negative", "negative", -2),
    )
