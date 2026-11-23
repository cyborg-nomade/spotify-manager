"""Exercise provider retries with controlled HTTP responses and real ownership."""

import asyncio
import json
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from email.message import Message
from email.utils import format_datetime
from urllib.error import HTTPError
from urllib.request import Request

import httpx
import pytest

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_origin_ports import OriginSourceError
from spotify_manager.infrastructure.listening import musicbrainz_gate
from spotify_manager.infrastructure.listening import origin_source
from spotify_manager.infrastructure.listening.cover_http import CoverHttpReads
from spotify_manager.infrastructure.listening.cover_source import MusicBrainzCoverSource
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    MusicBrainzRequestGate,
)
from spotify_manager.infrastructure.listening.provider_retry import retry_after_seconds
from tests.infrastructure.test_listening_cover_source import HttpProbe
from tests.infrastructure.test_listening_cover_source import album
from tests.infrastructure.test_listening_origin_source import row
from tests.infrastructure.test_listening_tag_source import ProviderProbe
from tests.infrastructure.test_listening_tag_source import artist


class ArtistReplies:
    """Feed the real urllib boundary failures, then a valid public response."""

    def __init__(self, failures: list[int], retry_after: str = "0") -> None:
        """Capture the ordered response statuses and optional server delay."""
        self.failures = failures
        self.retry_after = retry_after
        self.calls = 0

    def open(self, request: Request, timeout: int) -> object:
        """Return one synthetic urllib response or raise a documented HTTP error."""
        self.calls += 1
        if self.failures:
            headers = Message()
            headers["Retry-After"] = self.retry_after
            raise HTTPError(
                request.full_url, self.failures.pop(0), "test", headers, None
            )
        content = json.dumps({"count": 1, "artists": [row()]}).encode()
        return ProviderProbe(content).open(request, timeout=timeout)


class AlbumReplies(CoverHttpReads):
    """Send the actual HTTP reader through a deterministic response sequence."""

    def __init__(self, probe: HttpProbe) -> None:
        """Retain the public request recorder and its queued synthetic replies."""
        self.probe = probe

    def _read(self, client: httpx.Client, target: str, limit: int) -> bytes | None:
        with httpx.Client(transport=httpx.MockTransport(self.probe.handle)) as fake:
            return super()._read(fake, target, limit)


@pytest.fixture
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove elapsed waits while preserving real retry and lock decisions."""
    monkeypatch.setattr(musicbrainz_gate, "REQUEST_INTERVAL", 0)
    monkeypatch.setattr(musicbrainz_gate, "RETRY_BASE_SECONDS", 0)


@pytest.mark.usefixtures("fast_retry")
async def test_artist_recovers_from_consecutive_busy_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit artist lookup saves valid evidence after 503 and 429 replies."""
    replies = ArtistReplies([503, 429])
    monkeypatch.setattr(origin_source, "urlopen", replies.open)
    result = await origin_source.MusicBrainzOriginSource().fetch(artist())
    assert result.state == "matched"
    assert replies.calls == 3


@pytest.mark.parametrize("status,attempts", [(503, 3), (403, 1)])
@pytest.mark.usefixtures("fast_retry")
async def test_artist_retries_are_bounded_and_exclude_denied_requests(
    monkeypatch: pytest.MonkeyPatch, status: int, attempts: int
) -> None:
    """Only temporary failures receive automatic resubmission."""
    replies = ArtistReplies([status] * 4)
    monkeypatch.setattr(origin_source, "urlopen", replies.open)
    with pytest.raises(OriginSourceError, match="unavailable"):
        await origin_source.MusicBrainzOriginSource().fetch(artist())
    assert replies.calls == attempts


@pytest.mark.usefixtures("fast_retry")
async def test_album_retries_busy_reply_but_not_invalid_metadata() -> None:
    """A 502 can recover; a malformed completed response stops after one read."""
    recovered = HttpProbe(
        [
            httpx.Response(502),
            httpx.Response(200, json={"count": 0, "release-groups": []}),
        ]
    )
    source = MusicBrainzCoverSource(MusicBrainzRequestGate(), AlbumReplies(recovered))
    result = await source.fetch(album())
    assert result.metadata.state == "unmatched" and len(recovered.urls) == 2
    malformed = HttpProbe([httpx.Response(200, json=[])])
    source = MusicBrainzCoverSource(MusicBrainzRequestGate(), AlbumReplies(malformed))
    with pytest.raises(CoverSourceError, match="not an object"):
        await source.fetch(album())
    assert len(malformed.urls) == 1


async def test_long_provider_cooldown_defers_both_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual clicks and parallel views cannot bypass a shared server cooldown."""
    gate = MusicBrainzRequestGate()
    replies = ArtistReplies([429], "60")
    monkeypatch.setattr(origin_source, "urlopen", replies.open)
    origins = origin_source.MusicBrainzOriginSource(gate)
    with pytest.raises(OriginSourceError):
        await origins.fetch(artist())
    album_replies = HttpProbe([])
    covers = MusicBrainzCoverSource(gate, AlbumReplies(album_replies))
    with pytest.raises(CoverSourceError, match="longer pause"):
        await covers.fetch(album())
    assert replies.calls == 1 and not album_replies.urls


async def test_cancellation_during_retry_wait_sends_no_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled batch never submits the next provider attempt."""
    replies = ArtistReplies([503], "10")
    monkeypatch.setattr(origin_source, "urlopen", replies.open)
    task = asyncio.create_task(origin_source.MusicBrainzOriginSource().fetch(artist()))
    async with asyncio.timeout(2):
        while not replies.calls:
            await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert replies.calls == 1


@pytest.mark.parametrize(
    "value,expected", [(None, 0), ("9", 9), ("-2", 0), ("a" * 81, 0)]
)
def test_retry_after_accepts_only_valid_delays(
    value: str | None, expected: int
) -> None:
    """An invalid provider hint cannot turn local backoff into an invalid delay."""
    assert retry_after_seconds(value) == expected


def test_retry_after_accepts_http_dates() -> None:
    """Date-form hints use UTC and past dates add no cooldown."""
    now = datetime.now(UTC)
    assert 58 < retry_after_seconds(format_datetime(now + timedelta(minutes=1))) <= 60
    assert retry_after_seconds(format_datetime(now - timedelta(minutes=1))) == 0
