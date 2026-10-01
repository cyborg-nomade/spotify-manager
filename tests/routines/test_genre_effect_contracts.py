"""Freeze Genre Reveal observation and accepted-effect order before extraction."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from typing import Self
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import genre_reveal as legacy


STAMP = datetime(2026, 9, 25, tzinfo=UTC)
URIS = ("spotify:track:one", "spotify:track:two", "spotify:track:three")
EVENTS = ["source", "destination", "follow", "append", "clock", "audit"]


class GenreEffectFailureError(RuntimeError):
    """Stop after recording a selected accepted effect."""


@dataclass
class GenreEffects:
    """Record original source and playlist effects with deterministic failures.

    Args:
        existing: Destination track identities.
        failure: Accepted effect after which execution fails.
    """

    existing: frozenset[str] = frozenset()
    failure: str | None = None
    events: list[str] = field(default_factory=list)
    audit_result: dict[str, object] | None = None
    writes: list[object] = field(default_factory=list)

    def _event(self, event: str) -> None:
        self.events.append(event)
        if self.failure == event:
            raise GenreEffectFailureError(event)

    def source(
        self, slug: str, name: str, reader: legacy.PageReader
    ) -> legacy._GenrePlaylistSource:
        """Observe original source discovery before destination reads.

        Args:
            slug: Genre route identity.
            name: Genre display name.
            reader: Original public-page reader.

        Returns:
            Original preview and ordered markers.
        """
        self._event("source")
        preview = legacy.GenreRevealSourcePreview(
            slug=slug,
            name=name,
            every_noise_url="https://everynoise.com/engenremap-genre.html",
            source_playlist_id="source",
            source_playlist_uri="spotify:playlist:source",
            source_playlist_url="https://open.spotify.com/playlist/source",
        )
        return legacy._GenrePlaylistSource(preview, URIS)

    def destination(self, spotify: object, playlist_id: str) -> PlaylistState:
        """Observe destination identities after source discovery.

        Args:
            spotify: Original caller-owned client.
            playlist_id: Original destination identity.

        Returns:
            Explicit original membership.
        """
        assert playlist_id == "destination"
        self._event("destination")
        return PlaylistState(len(self.existing), self.existing)

    def _put(self, endpoint: str, *, args: object) -> None:
        self.writes.append(["PUT", endpoint, args])
        self._event("follow")

    def _post(self, endpoint: str, *, payload: object) -> None:
        self.writes.append(["POST", endpoint, payload])
        self._event("append")

    def clock(self) -> datetime:
        """Observe the original completion clock after accepted Spotify writes.

        Returns:
            Fixed completion timestamp.
        """
        self._event("clock")
        return STAMP

    def audit(self, result: legacy.GenreRevealRunResult, path: Path) -> None:
        """Accept the completed result before a possible later audit failure.

        Args:
            result: Original serialized result.
            path: Original audit location.
        """
        self.audit_result = result.model_dump(mode="json")
        self._event("audit")


class GenreClock(datetime):
    """Observe the completion clock without real time or operator data."""

    effects: GenreEffects

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        """Return the fixed original completion time.

        Args:
            tz: Original requested timezone.

        Returns:
            Compatible fixed timestamp.
        """
        cls.effects.clock()
        return cls(2026, 9, 25, tzinfo=UTC).astimezone(tz)


def _bind(monkeypatch: pytest.MonkeyPatch, effects: GenreEffects) -> None:
    monkeypatch.setattr(legacy, "load_genre_playlist_source", effects.source)
    monkeypatch.setattr(blast_from_past, "load_playlist_state", effects.destination)
    monkeypatch.setattr(legacy, "append_genre_reveal_log", effects.audit)
    monkeypatch.setattr(GenreClock, "effects", effects, raising=False)
    monkeypatch.setattr(legacy, "datetime", GenreClock)


def _run(effects: GenreEffects, path: Path) -> legacy.GenreRevealRunResult:
    return legacy.process_next_genre(
        cast(Spotify, effects), "genre", "Genre", "destination", log_path=path
    )


@pytest.mark.parametrize(
    "existing", [frozenset(), frozenset({"two"}), frozenset({"one", "two", "three"})]
)
def test_original_genre_completion_order(
    existing: frozenset[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Save the source even when every track is present and audit after the last write.

    Args:
        existing: Original destination membership.
        monkeypatch: Explicit original external boundaries.
        tmp_path: Isolated audit location.
    """
    effects = GenreEffects(existing)
    _bind(monkeypatch, effects)
    result = _run(effects, tmp_path / "audit.jsonl")
    missing = [uri for uri in URIS if uri.rsplit(":", 1)[-1] not in existing]
    assert effects.events == (
        EVENTS if missing else [event for event in EVENTS if event != "append"]
    )
    assert result.source_track_uris == list(URIS) and result.added_track_uris == missing
    assert result.completed_at == STAMP and effects.audit_result == result.model_dump(
        mode="json"
    )
    assert effects.writes[0] == [
        "PUT",
        "me/library",
        {"uris": "spotify:playlist:source"},
    ]
    if missing:
        assert effects.writes[1] == [
            "POST",
            "playlists/destination/items",
            {"uris": missing},
        ]


@pytest.mark.parametrize("failure", EVENTS)
def test_original_genre_failure_preserves_accepted_effect_prefix(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep accepted library/playlist writes when a later clock or audit stage fails.

    Args:
        failure: Accepted effect at which to stop.
        monkeypatch: Explicit original external boundaries.
        tmp_path: Isolated audit location.
    """
    effects = GenreEffects(failure=failure)
    _bind(monkeypatch, effects)
    with pytest.raises(GenreEffectFailureError, match=failure):
        _run(effects, tmp_path / "audit.jsonl")
    index = EVENTS.index(failure)
    assert effects.events == EVENTS[: index + 1]
    assert len(effects.writes) == min(max(index - 1, 0), 2)
    assert (effects.audit_result is not None) is (failure == "audit")
