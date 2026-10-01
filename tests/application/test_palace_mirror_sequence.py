"""Protect original live-mirror refresh, publication and exact artifact contracts."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.palace_mirror import SavedAlbumPage
from spotify_manager.application.palace_mirror import SavedMirror
from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.application.palace_values import PalaceOfMemoryStateError
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines.analyse_library import album_from_saved_item
from spotify_manager.utils.sorting import album_sort_key
from tests.routines.test_palace_of_memory import saved_album
from tests.support.palace_mirror import MirrorReads
from tests.support.palace_mirror import cases
from tests.support.palace_mirror import original_outcome
from tests.support.queue_neighbors import NOW


@dataclass
class MemoryMirror:
    """Supply original parsed mirror facts and accepted publication observations.

    Args:
        edge: Original paging and publication scenario.
        audits: Original complete preflight audits accepted by the workflow.
    """

    edge: MirrorReads
    audits: list[SavedAlbumRefresh] = field(default_factory=list)

    def previous(self) -> tuple[YourLibraryAlbum, ...]:
        """Supply original usable previous facts or invalid-mirror boundary.

        Returns:
            Original previous canonical models.

        Raises:
            PalaceOfMemoryDataError: The configured original old mirror is invalid.
        """
        if self.edge.profile == "missing":
            return ()
        if self.edge.profile == "invalid-old":
            raise PalaceOfMemoryDataError("invalid old mirror")
        size = 6 if self.edge.profile == "unchanged" else 5
        return tuple(
            YourLibraryAlbum.model_validate(saved_album(index)) for index in range(size)
        )

    def progress(self, message: str) -> None:
        """Observe original page progress.

        Args:
            message: Original visible stage.
        """
        self.edge.progress(message)

    def page(self, offset: int) -> SavedAlbumPage:
        """Supply complete original parsed live rows and raw accounting facts.

        Args:
            offset: Original raw-row offset.

        Returns:
            Original parsed page facts.

        Raises:
            PalaceOfMemoryDataError: The configured original raw page is invalid.
        """
        response = self.edge.current_user_saved_albums(50, offset)
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise PalaceOfMemoryDataError(
                f"Spotify returned an invalid saved-album page at offset {offset}."
            )
        albums = []
        for raw in response["items"]:
            album = album_from_saved_item(raw)
            if album is not None:
                albums.append(album)
        return SavedAlbumPage(
            tuple(albums), len(response["items"]), bool(response.get("next"))
        )

    def canonical(self, albums: list[YourLibraryAlbum]) -> tuple[YourLibraryAlbum, ...]:
        """Supply original newest-value duplicate resolution and canonical collation.

        Args:
            albums: Original gathered complete models.

        Returns:
            Original canonical ordering.
        """
        by_id = {}
        for album in albums:
            if album.spotify_id:
                by_id[album.spotify_id] = album
        return tuple(sorted(by_id.values(), key=album_sort_key))

    def replace(self, albums: tuple[YourLibraryAlbum, ...]) -> str | None:
        """Observe original publication and preserve its translated boundary error.

        Args:
            albums: Original complete canonical replacement.

        Returns:
            Original normalized backup location when an old file exists.

        Raises:
            PalaceOfMemoryStateError: The configured original publication fails.
        """
        assert albums
        try:
            self.edge.publish(
                Path("albums.json"), source="Spotify live library refresh"
            )
        except OSError as exc:
            raise PalaceOfMemoryStateError(
                "Could not publish refreshed saved albums: ROOT/albums.json"
            ) from exc
        if self.edge.profile == "missing":
            return None
        return (
            "ROOT/backups/"
            + NOW.strftime("%Y%m%dT%H%M%S%fZ")
            + "-albums_total_new.json"
        )

    def clock(self) -> datetime:
        """Return original independent preflight completion time.

        Returns:
            Fixed original completion timestamp.
        """
        return NOW

    def audit(self, refresh: SavedAlbumRefresh) -> None:
        """Accept original preflight audit even for an unchanged mirror.

        Args:
            refresh: Original complete preflight outcome.
        """
        self.audits.append(refresh)


def _outcome(profile: str) -> object:
    edge = MirrorReads(profile)
    memory = MemoryMirror(edge)
    result: dict[str, object] = {}
    try:
        albums, refresh = SavedMirror(memory).run()
        assert memory.audits == [refresh]
        result["result"] = {
            "albums": [album.model_dump() for album in albums],
            "refresh": asdict(refresh),
        }
    except RuntimeError as exc:
        assert memory.audits == []
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("case", cases())
def test_palace_live_mirror_matches_original_bytes_and_publication(
    case: dict[str, object],
) -> None:
    """Compare original exact artifacts and independent complete refresh execution.

    Args:
        case: Original immutable live paging and publication evidence.
    """
    profile = cast(str, case["profile"])
    assert original_outcome(profile) == case["outcome"]
    expected = dict(cast(dict[str, object], case["outcome"]))
    del expected["artifacts"]
    assert _outcome(profile) == expected
