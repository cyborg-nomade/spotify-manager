"""Original ordering contracts for the two historical track playlist workflows."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from functools import partialmethod
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.bootstrap import historical_playlists as composition
from spotify_manager.infrastructure.legacy.historical_playlists import (
    LegacyHistoricalPlaylist,
)
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio


def _selection() -> blast.ScrobbleSelection:
    return blast.ScrobbleSelection(
        date(2020, 1, 1),
        0,
        1,
        1,
        1,
        "top down",
        1,
        blast.Scrobble("Song", "Artist", "Album", 1),
    )


@dataclass
class HistoricalSteps:
    """Record public integration steps before extracting their orchestration.

    Args:
        failure: Step to fail after observation.
        events: Observed steps.
        pending: Whether resolution supplies a new match.
        empty: Whether radio selection is empty.
        total: Existing playlist size.
        messages: Original progress presentation.
    """

    failure: str = ""
    events: list[str] = field(default_factory=list)
    pending: bool = True
    empty: bool = False
    total: int = 3
    messages: list[str] = field(default_factory=list)

    def _step(self, name: str) -> None:
        self.events.append(name)
        if name == self.failure:
            raise OSError(name)

    def cancel(self, check: blast.CancelCheck | None) -> None:
        """Record a cancellation boundary.

        Args:
            check: Original optional predicate.
        """
        self._step("cancel")

    def playlist(
        self,
        sp: Spotify,
        playlist_id: str,
        retry: blast.RetryCall,
        check: blast.CancelCheck | None,
    ) -> blast.PlaylistState:
        """Observe the target playlist.

        Args:
            sp: Caller-owned client.
            playlist_id: Target identifier.
            retry: Caller retry policy.
            check: Optional cancellation predicate.

        Returns:
            Existing playlist facts.
        """
        self._step("playlist")
        return blast.PlaylistState(self.total, frozenset())

    def select_blast(
        self,
        *,
        count: int,
        path: Path,
        today: date | None,
        random_index_reader: blast.RandomIndexReader,
        progress_callback: blast.ProgressCallback | None,
    ) -> blast.BlastFromPastBatch:
        """Observe historical batch selection.

        Args:
            count: Requested dates.
            path: History path.
            today: Optional effective date.
            random_index_reader: Random source.
            progress_callback: Optional presenter.

        Returns:
            One selection.
        """
        self._step("select")
        return blast.BlastFromPastBatch(
            datetime(2026, 1, 1, tzinfo=UTC), date(2021, 12, 31), 1, (_selection(),)
        )

    def select_radio(
        self,
        *,
        path: Path,
        today: date | None,
        random_timestamp_reader: radio.RandomTimestampReader,
        progress_callback: blast.ProgressCallback | None,
    ) -> radio.DailyMindRadioBatch:
        """Observe anniversary selection.

        Args:
            path: History path.
            today: Optional effective date.
            random_timestamp_reader: Random source.
            progress_callback: Optional presenter.

        Returns:
            Selected batch or the configured empty batch.
        """
        self._step("select")
        selections = () if self.empty else (_selection(),)
        return radio.DailyMindRadioBatch(None, (date(2020, 1, 1),), (), selections)

    def resolve(
        self,
        sp: Spotify,
        selections: tuple[blast.ScrobbleSelection, ...],
        playlist: blast.PlaylistState,
        progress: blast.ProgressCallback | None,
        retry: blast.RetryCall,
        check: blast.CancelCheck | None,
    ) -> blast.SpotifySelectionResolution:
        """Observe match resolution.

        Args:
            sp: Caller-owned client.
            selections: Requested plays.
            playlist: Existing playlist facts.
            progress: Optional presenter.
            retry: Caller retry policy.
            check: Optional cancellation predicate.

        Returns:
            Optional pending match.
        """
        self._step("resolve")
        match = blast.SpotifyTrackMatch(
            "match",
            "spotify:track:match",
            "Song",
            ("Artist",),
            "Album",
            1,
            1.0,
            1.0,
            50,
        )
        pending = (match,) if self.pending else ()
        result = blast.SpotifySelectionResult(
            selections[0], match, 1, "added" if self.pending else "already present"
        )
        return blast.SpotifySelectionResolution((result,), pending)

    def append(
        self,
        sp: Spotify,
        playlist_id: str,
        matches: list[blast.SpotifyTrackMatch],
        retry: blast.RetryCall,
        check: blast.CancelCheck | None,
    ) -> None:
        """Observe an accepted append.

        Args:
            sp: Caller-owned client.
            playlist_id: Target identifier.
            matches: Pending matches in selection order.
            retry: Caller retry policy.
            check: Optional cancellation predicate.
        """
        self._step("append")


def _install(steps: HistoricalSteps, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blast, "check_cancel", steps.cancel)
    monkeypatch.setattr(blast, "load_playlist_state", steps.playlist)
    monkeypatch.setattr(composition, "_blast_batch", partial(_blast, steps))
    monkeypatch.setattr(composition, "_anniversary_batch", partial(_radio, steps))
    monkeypatch.setattr(
        LegacyHistoricalPlaylist, "resolve", partialmethod(_resolve, steps)
    )
    monkeypatch.setattr(blast, "add_spotify_matches", steps.append)


def _invoke(
    kind: str, steps: HistoricalSteps, preview: bool
) -> blast.BlastFromPastSpotifySummary | radio.DailyMindRadioSpotifySummary:
    spotify = cast(Spotify, object())
    if kind == "radio":
        return radio.add_daily_mind_radio_to_spotify(
            spotify, "target", progress_callback=steps.messages.append, dry_run=preview
        )
    return blast.add_blast_from_past_to_spotify(
        spotify, "target", progress_callback=steps.messages.append, dry_run=preview
    )


def _events(kind: str) -> list[str]:
    if kind == "radio":
        return ["cancel", "select", "cancel", "playlist", "resolve", "append"]
    return ["cancel", "playlist", "select", "cancel", "resolve", "append"]


@pytest.mark.parametrize("kind", ["blast", "radio"])
@pytest.mark.parametrize("failure", ["playlist", "select", "resolve", "append"])
def test_failure_keeps_original_observation_order(
    kind: str, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop at failed observations or mutation without executing later steps.

    Args:
        kind: Historical routine.
        failure: Chosen failure boundary.
        monkeypatch: Scoped integration substitutions.
    """
    steps = HistoricalSteps(failure)
    _install(steps, monkeypatch)
    with pytest.raises(OSError, match=failure):
        _invoke(kind, steps, False)
    expected = _events(kind)
    assert steps.events == expected[: expected.index(failure) + 1]


@pytest.mark.parametrize("kind", ["blast", "radio"])
@pytest.mark.parametrize(
    "preview,pending", [(True, True), (False, False), (False, True)]
)
def test_append_and_projected_length_follow_original_preview_rules(
    kind: str, preview: bool, pending: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep resolved added actions in previews while projecting actual playlist size.

    Args:
        kind: Historical routine.
        preview: Suppress remote mutation.
        pending: Whether resolution supplies a new track.
        monkeypatch: Scoped integration substitutions.
    """
    steps = HistoricalSteps(pending=pending)
    _install(steps, monkeypatch)
    result = _invoke(kind, steps, preview)
    appended = pending and not preview
    assert result.playlist_length_after == 3 + int(appended)
    assert result.added == int(pending)
    assert steps.events == (_events(kind) if appended else _events(kind)[:-1])
    assert ("Adding 1 tracks to Spotify" in steps.messages) is appended


def test_empty_radio_selection_skips_every_spotify_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty radio batch still checks cancellation after selection.

    Args:
        monkeypatch: Scoped integration substitutions.
    """
    steps = HistoricalSteps(empty=True)
    _install(steps, monkeypatch)
    result = _invoke("radio", steps, False)
    assert steps.events == ["cancel", "select", "cancel"]
    assert (
        result.playlist_length_before is None and result.playlist_length_after is None
    )


def test_full_blast_destination_skips_history_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capacity is observed before historical files or randomness are requested.

    Args:
        monkeypatch: Scoped integration substitutions.
    """
    steps = HistoricalSteps()
    _install(steps, monkeypatch)
    result = blast.add_blast_from_past_to_spotify(
        cast(Spotify, object()), "target", count=None, max_playlist_length=3
    )
    assert steps.events == ["cancel", "playlist"]
    assert result.batch is None and result.requested_count == 0


def _blast(
    steps: HistoricalSteps,
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    count: int,
) -> blast.BlastFromPastBatch:
    return steps.select_blast(
        count=count,
        path=path,
        today=today,
        random_index_reader=random,
        progress_callback=progress,
    )


def _radio(
    steps: HistoricalSteps,
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
) -> radio.DailyMindRadioBatch:
    return steps.select_radio(
        path=path,
        today=today,
        random_timestamp_reader=random,
        progress_callback=progress,
    )


def _resolve(
    resources: LegacyHistoricalPlaylist,
    steps: HistoricalSteps,
    selections: tuple[blast.ScrobbleSelection, ...],
    playlist: blast.PlaylistState,
) -> blast.SpotifySelectionResolution:
    return steps.resolve(
        resources.client,
        selections,
        playlist,
        resources.progress,
        resources.retry,
        resources.cancel,
    )
