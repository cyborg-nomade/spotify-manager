"""Read complete raw membership for conservative interrupted-selection recovery."""

from typing import cast

from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.infrastructure.history_playlist_pages import SpotifyHistoryPages


def _page(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise SomethingOldError(
            "Spotify returned invalid choice-recovery playlist data."
        )
    total = raw.get("total")
    if "total" in raw and (type(total) is not int or total < 0):
        raise SomethingOldError("Spotify returned invalid recovery playlist totals.")
    if "next" not in raw and "total" not in raw:
        raise SomethingOldError("Spotify omitted recovery playlist paging evidence.")
    return cast(dict[str, object], raw)


def _track_id(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    track = raw.get("item") or raw.get("track")
    if not isinstance(track, dict):
        return None
    identity = track.get("id")
    return identity if isinstance(identity, str) and identity else None


def _has_more(page: dict[str, object], offset: int) -> bool:
    if "next" in page:
        if page["next"] is not None and not isinstance(page["next"], str):
            raise SomethingOldError("Spotify returned invalid recovery continuation.")
        return bool(page["next"])
    total = page.get("total")
    return type(total) is int and offset < total


def _check_next(
    page: dict[str, object], rows: list[object], seen: set[str], offset: int
) -> None:
    if not rows:
        raise SomethingOldError(
            "Spotify returned an empty choice-recovery playlist page."
        )
    total = page.get("total")
    if type(total) is int and offset >= total:
        raise SomethingOldError("Spotify continued beyond the recovery playlist total.")
    token = page.get("next")
    if isinstance(token, str):
        if token in seen:
            raise SomethingOldError("Spotify repeated a choice-recovery playlist page.")
        seen.add(token)


def _complete(
    page: dict[str, object], result: list[str | None]
) -> tuple[str | None, ...]:
    total = page.get("total")
    if type(total) is int and total != len(result):
        raise SomethingOldError(
            "Spotify returned incomplete choice-recovery membership."
        )
    return tuple(result)


async def read_choice_playlist(pages: SpotifyHistoryPages) -> tuple[str | None, ...]:
    """Retain duplicates and unsupported rows instead of inferring a complete append.

    Args:
        pages: Existing named Spotify paging/retry resource.

    Returns:
        Complete raw membership; unreadable items remain explicit missing identities.

    Raises:
        SomethingOldError: Paging, totals or response containers are inconsistent.
    """
    result: list[str | None] = []
    seen: set[str] = set()
    while True:
        page = _page(await pages.read(len(result)))
        rows = cast(list[object], page["items"])
        result.extend(_track_id(row) for row in rows)
        if not _has_more(page, len(result)):
            return _complete(page, result)
        _check_next(page, rows, seen, len(result))
