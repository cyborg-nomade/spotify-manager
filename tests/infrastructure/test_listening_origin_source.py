"""Exact-name geographic evidence, incomplete searches and rate-limited reads."""

import asyncio
import json
import time
from dataclasses import dataclass
from dataclasses import field
from threading import Event
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL
from uuid import uuid5

import pytest

from spotify_manager.application.listening_origin_ports import OriginSourceError
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening import origin_source
from spotify_manager.infrastructure.listening.origin_source import (
    MusicBrainzOriginSource,
)
from spotify_manager.infrastructure.listening.origin_source import parse_artist_origins
from tests.infrastructure.test_listening_tag_source import OfflineProbe
from tests.infrastructure.test_listening_tag_source import ProviderProbe
from tests.infrastructure.test_listening_tag_source import artist
from tests.support.listening_origins import origin_metadata


def row(name: str = "Alpha", identity: str = "one") -> dict[str, object]:
    """Return one documented search candidate with distinct associated/begin areas."""
    return {
        "id": str(uuid5(NAMESPACE_URL, identity)),
        "name": name,
        "country": "BR",
        "type": "Group",
        "disambiguation": "Fixture band",
        "area": {"name": "Brazil", "iso-3166-1-codes": ["BR"]},
        "begin-area": {"name": "Formation town"},
    }


def test_exact_names_country_fields_and_ambiguous_search_bounds() -> None:
    """Fuzzy scores, aliases and provider ordering never choose an artist for us."""
    payload = {
        "count": 3,
        "artists": [row(" ALPHA "), row("Alpha", "two"), row("Alpha Beta", "other")],
    }
    result = parse_artist_origins(payload, artist())
    assert result.state == "ambiguous" and result.candidate_count == 2
    assert all(
        item.area == "Brazil" and item.begin_area == "Formation town"
        for item in result.candidates
    )
    partial = parse_artist_origins({"count": 101, "artists": [row()]}, artist())
    assert partial.state == "incomplete" and partial.candidate_count == 1
    unmatched = parse_artist_origins({"count": 1, "artists": [row("Beta")]}, artist())
    assert unmatched.state == "unmatched" and not unmatched.candidates
    unique = parse_artist_origins({"count": 2, "artists": [row(), row()]}, artist())
    assert unique.state == "matched" and unique.candidate_count == 1
    missing = row()
    missing.pop("area")
    missing.pop("country")
    missing["begin-area"] = None
    assert (
        parse_artist_origins({"count": 1, "artists": [missing]}, artist())
        .candidates[0]
        .countries
        == ()
    )
    accented = parse_artist_origins(
        {"count": 1, "artists": [row("Be\u0301ta")]}, artist("Béta")
    )
    assert accented.state == "matched"
    many = [row(identity=str(index)) for index in range(8)]
    bounded = parse_artist_origins({"count": 8, "artists": many}, artist())
    assert bounded.candidate_count == 8 and len(bounded.candidates) == 5


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"count": True, "artists": []},
        {"count": -1, "artists": []},
        {"count": 0, "artists": [row()]},
        {"count": 101, "artists": [row()] * 101},
        {"count": 1, "artists": [None]},
        {"count": 1, "artists": [{"name": 4}]},
        {"count": 1, "artists": [{**row(), "id": "bad"}]},
        {
            "count": 1,
            "artists": [{**row(), "id": "AAAA0000-0000-0000-0000-000000000000"}],
        },
        {"count": 1, "artists": [{**row(), "country": "Brazil"}]},
        {"count": 1, "artists": [{**row(), "area": []}]},
        {"count": 1, "artists": [{**row(), "area": {"iso-3166-1-codes": "BR"}}]},
    ],
)
def test_malformed_provider_never_erases_cached_evidence(
    payload: dict[str, object],
) -> None:
    """Bad source shapes fail safely instead of claiming geographic absence."""
    with pytest.raises(OriginSourceError):
        parse_artist_origins(payload, artist())


@pytest.mark.parametrize("content", [b"[]", b"bad-json", b"\xff", b"x" * (1048576 + 1)])
def test_raw_response_is_bounded(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    """Transport parsing and size limits apply before candidate interpretation."""
    monkeypatch.setattr(origin_source, "urlopen", ProviderProbe(content).open)
    with pytest.raises(OriginSourceError):
        MusicBrainzOriginSource().read(artist())


def test_request_escapes_query_syntax_and_sends_no_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixed read contains only the selected artist phrase and public options."""
    name = 'A "Band" + (B): C\\D'
    probe = ProviderProbe(json.dumps({"count": 1, "artists": [row(name)]}).encode())
    monkeypatch.setattr(origin_source, "urlopen", probe.open)
    source = MusicBrainzOriginSource()
    result = source.read(artist(name))
    assert source.configured and probe.request is not None and result.state == "matched"
    params = parse_qs(urlsplit(probe.request.full_url).query)
    assert set(params) == {"query", "fmt", "limit"} and params["limit"] == ["100"]
    assert params["query"] == ['artistaccent:"A \\"Band\\" \\+ \\(B\\)\\: C\\\\D"']
    assert "spotify-manager" in probe.request.get_header("User-agent")
    monkeypatch.setattr(origin_source, "urlopen", OfflineProbe().open)
    with pytest.raises(OriginSourceError) as raised:
        source.read(artist())
    assert "test-only-secret" not in str(raised.value)


@dataclass
class TimedSource(MusicBrainzOriginSource):
    """Use the real async limiter around a network-free concrete read."""

    times: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    def read(self, artist: RankedEntity) -> ArtistOriginMetadata:
        self.times.append(time.monotonic())
        return origin_metadata(artist.name)


@pytest.mark.asyncio
async def test_request_spacing_survives_independent_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One provider resource enforces spacing even when callers start fresh batches."""
    monkeypatch.setattr(origin_source, "REQUEST_INTERVAL", 0.025)
    source = TimedSource()
    await source.fetch(artist())
    await asyncio.gather(source.fetch(artist("Beta")), source.fetch(artist("Gamma")))
    assert len(source.times) == 3
    assert all(
        b - a >= 0.02 for a, b in zip(source.times, source.times[1:], strict=False)
    )


class HeldSource(MusicBrainzOriginSource):
    """Hold the concrete read to verify cancellation ownership."""

    def __init__(self, started: Event, release: Event) -> None:
        super().__init__()
        self.started = started
        self.release = release

    def read(self, artist: RankedEntity) -> ArtistOriginMetadata:
        self.started.set()
        assert self.release.wait(5)
        return origin_metadata(artist.name)


@pytest.mark.asyncio
async def test_cancelled_public_read_drains_before_releasing_provider_ownership() -> (
    None
):
    """A cancelled lookup cannot leak an active thread beyond resource shutdown."""
    started, release = Event(), Event()
    source = HeldSource(started, release)
    task = asyncio.create_task(source.fetch(artist()))
    while not started.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
