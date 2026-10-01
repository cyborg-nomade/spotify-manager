"""Exercise independent Genre Reveal sequencing and accepted-effect failure prefixes."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

import pytest

from spotify_manager.application.genre_run import GenreReveal
from spotify_manager.application.genre_values import GenreOutcome
from spotify_manager.domain.genres import GenrePlaylistSource
from spotify_manager.domain.genres import GenreSource


STAMP = datetime(2026, 9, 25, tzinfo=UTC)
SOURCE = GenrePlaylistSource(
    GenreSource(
        "genre",
        "Genre",
        "https://everynoise.com/engenremap-genre.html",
        "source",
        "spotify:playlist:source",
        "https://open.spotify.com/playlist/source",
    ),
    ("spotify:track:one", "spotify:track:two", "spotify:track:three"),
)
EVENTS = ["source", "destination", "follow", "append", "clock", "audit"]


class GenreBoundaryError(RuntimeError):
    """Stop after recording the configured original accepted effect."""


@dataclass
class Effects:
    """Provide explicit source facts, live membership and accepted effect observations.

    Args:
        existing: Original live destination identities.
        failure: Accepted effect after which to fail.
    """

    existing: frozenset[str] = frozenset()
    failure: str | None = None
    events: list[str] = field(default_factory=list)
    writes: list[object] = field(default_factory=list)
    result: GenreOutcome | None = None

    def _event(self, event: str) -> None:
        self.events.append(event)
        if self.failure == event:
            raise GenreBoundaryError(event)

    def source(self, slug: str, name: str) -> GenrePlaylistSource:
        """Observe validated source metadata before destination reads.

        Args:
            slug: Original genre identity.
            name: Original display name.

        Returns:
            Original source metadata and ordered markers.
        """
        assert slug == "genre" and name == "Genre"
        self._event("source")
        return SOURCE

    def destination(self, playlist_id: str) -> frozenset[str]:
        """Observe original live membership.

        Args:
            playlist_id: Original destination identity.

        Returns:
            Original represented track identities.
        """
        assert playlist_id == "destination"
        self._event("destination")
        return self.existing

    def follow(self, source: GenrePlaylistSource) -> None:
        """Accept the original unconditional source-playlist save.

        Args:
            source: Original discovered source.
        """
        self.writes.append(
            ["PUT", "me/library", {"uris": source.preview.source_playlist_uri}]
        )
        self._event("follow")

    def append(self, destination: str, missing: tuple[str, ...]) -> None:
        """Accept the original ordered missing-marker append.

        Args:
            destination: Original target identity.
            missing: Original missing markers.
        """
        self.writes.append(
            ["POST", "playlists/" + destination + "/items", {"uris": list(missing)}]
        )
        self._event("append")

    def clock(self) -> datetime:
        """Observe the completion clock after accepted writes.

        Returns:
            Fixed original completion timestamp.
        """
        self._event("clock")
        return STAMP

    def audit(self, outcome: GenreOutcome) -> None:
        """Accept the original completion audit before a possible later failure.

        Args:
            outcome: Original completed business outcome.
        """
        self.result = outcome
        self._event("audit")


@pytest.mark.parametrize(
    "existing", [frozenset(), frozenset({"two"}), frozenset({"one", "two", "three"})]
)
def test_independent_genre_matches_original_completion_order(
    existing: frozenset[str],
) -> None:
    """Retain original ordered effects and unconditional source save.

    Args:
        existing: Original destination membership.
    """
    effects = Effects(existing)
    result = GenreReveal(effects).run("genre", "Genre", "destination")
    missing = tuple(
        uri for uri in SOURCE.track_uris if uri.rsplit(":", 1)[-1] not in existing
    )
    assert effects.events == (
        EVENTS if missing else [event for event in EVENTS if event != "append"]
    )
    assert (
        result.source_track_uris == SOURCE.track_uris
        and result.added_track_uris == missing
    )
    assert result.completed_at == STAMP and effects.result is result
    assert effects.writes[0] == [
        "PUT",
        "me/library",
        {"uris": "spotify:playlist:source"},
    ]
    if missing:
        assert effects.writes[1] == [
            "POST",
            "playlists/destination/items",
            {"uris": list(missing)},
        ]


@pytest.mark.parametrize("failure", EVENTS)
def test_independent_genre_matches_original_accepted_failure_prefix(
    failure: str,
) -> None:
    """Retain accepted writes when a subsequent stage fails.

    Args:
        failure: Accepted effect at which to stop.
    """
    effects = Effects(failure=failure)
    with pytest.raises(GenreBoundaryError, match=failure):
        GenreReveal(effects).run("genre", "Genre", "destination")
    index = EVENTS.index(failure)
    assert effects.events == EVENTS[: index + 1]
    assert len(effects.writes) == min(max(index - 1, 0), 2)
    assert (effects.result is not None) is (failure == "audit")
