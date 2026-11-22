"""Exact release-group evidence, bounded public transports and shared rate limits."""

import asyncio
import gzip
import time
from dataclasses import dataclass
from dataclasses import field
from threading import Event
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL
from uuid import uuid5

import httpx
import pytest

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening import musicbrainz_gate
from spotify_manager.infrastructure.listening.cover_http import CoverHttpReads
from spotify_manager.infrastructure.listening.cover_http import _content
from spotify_manager.infrastructure.listening.cover_http import public_cover_url
from spotify_manager.infrastructure.listening.cover_image import validate_cover_image
from spotify_manager.infrastructure.listening.cover_search import parse_cover_search
from spotify_manager.infrastructure.listening.cover_source import MusicBrainzCoverSource
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    MusicBrainzRequestGate,
)
from spotify_manager.infrastructure.listening.origin_source import (
    MusicBrainzOriginSource,
)
from tests.support.listening_covers import album
from tests.support.listening_covers import cover_result
from tests.support.listening_covers import jpeg
from tests.support.listening_origins import origin_metadata


def row(
    name: str = "Record", artist: str = "Alpha", identity: str = "one"
) -> dict[str, object]:
    """Keep documented release-group and complete artist-credit fields.

    Args:
        name: Synthetic original album title.
        artist: Synthetic complete credited artist name.
        identity: Stable seed for a distinct synthetic provider UUID.

    Returns:
        One documented release-group candidate with complete artist credit.
    """
    return {
        "id": str(uuid5(NAMESPACE_URL, identity)),
        "title": name,
        "artist-credit": [{"name": artist, "artist": {"name": artist}}],
        "disambiguation": "Fixture release group",
    }


def test_exact_credit_editions_ambiguity_and_incomplete_search() -> None:
    """Scores, partial credits, accents and edition suffixes never choose identity."""
    payload = {
        "count": 4,
        "release-groups": [
            row(),
            row(identity="two"),
            row("Record Deluxe"),
            row(artist="Beta"),
        ],
    }
    data = parse_cover_search(payload, album())
    assert data.state == "ambiguous" and data.candidate_count == 2
    assert (
        parse_cover_search({"count": 101, "release-groups": [row()]}, album()).state
        == "incomplete"
    )
    assert (
        parse_cover_search({"count": 0, "release-groups": []}, album()).state
        == "unmatched"
    )
    assert (
        parse_cover_search(
            {"count": 1, "release-groups": [row("BéTa")]}, album("Be\u0301ta")
        ).state
        == "no_cover"
    )
    assert (
        parse_cover_search(
            {"count": 2, "release-groups": [row(), row()]}, album()
        ).candidate_count
        == 1
    )
    many = [row(identity=str(index)) for index in range(7)]
    bounded = parse_cover_search({"count": 7, "release-groups": many}, album())
    assert bounded.candidate_count == 7 and len(bounded.candidates) == 5


def test_complete_joined_credit_and_conflicting_duplicates() -> None:
    """A shared title/first artist cannot hide collaborators or conflicting groups."""
    credit = [
        {"name": "Alpha", "joinphrase": " & ", "artist": {"name": "Alpha"}},
        {"artist": {"name": "Béta"}},
    ]
    collaborative = {**row(), "artist-credit": credit, "disambiguation": None}
    result = parse_cover_search(
        {"count": 1, "release-groups": [collaborative]}, album(artist="Alpha & Béta")
    )
    assert (
        result.candidates[0].artist == "Alpha & Béta"
        and result.candidates[0].description == ""
    )
    assert (
        parse_cover_search(
            {"count": 1, "release-groups": [collaborative]}, album()
        ).state
        == "unmatched"
    )
    with pytest.raises(CoverSourceError):
        parse_cover_search(
            {
                "count": 2,
                "release-groups": [row(), {**row(), "disambiguation": "Conflicting"}],
            },
            album(),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"count": True, "release-groups": []},
        {"count": -1, "release-groups": []},
        {"count": 0, "release-groups": [row()]},
        {"count": 101, "release-groups": [row()] * 101},
        {"count": 1, "release-groups": [None]},
    ],
)
def test_malformed_search_bounds_fail_safely(payload: dict[str, object]) -> None:
    """Malformed responses never become absent artwork evidence.

    Args:
        payload: Controlled external metadata response.
    """
    with pytest.raises(CoverSourceError):
        parse_cover_search(payload, album())


@pytest.mark.parametrize(
    "change",
    [
        {"id": "bad"},
        {"id": "AAAA0000-0000-0000-0000-000000000000"},
        {"title": False},
        {"title": None},
        {"title": "\ud800"},
        {"title": "x" * 1001},
        {"artist-credit": []},
        {"artist-credit": [{"name": False, "artist": {"name": "Alpha"}}]},
        {"artist-credit": [{}]},
        {"artist-credit": [{"artist": {}, "name": 7}]},
        {"artist-credit": [{"artist": {"name": "Alpha"}, "joinphrase": None}]},
        {"artist-credit": [{"artist": {"name": "x" * 1001}}]},
    ],
)
def test_invalid_candidate_fields_are_not_cached(change: dict[str, object]) -> None:
    """IDs, complete credit shapes and bounded text are verified before matching.

    Args:
        change: Invalid fields applied to the documented candidate fixture.
    """
    with pytest.raises(CoverSourceError):
        parse_cover_search(
            {"count": 1, "release-groups": [{**row(), **change}]}, album()
        )


@dataclass
class PublicReads(CoverHttpReads):
    """Serve a fixed sequence of already-decoded public fixture responses.

    Args:
        responses: Ordered synthetic metadata and image responses.
        urls: Public request URLs observed by this offline resource.
    """

    responses: list[dict[str, object] | bytes | None]
    urls: list[str] = field(default_factory=list)

    def read_json(self, url: str) -> dict[str, object] | None:
        """Read json.

        Args:
            url: Public provider destination under validation.

        Returns:
            Queued JSON metadata, or explicit provider absence.
        """
        self.urls.append(url)
        value = self.responses.pop(0)
        assert value is None or isinstance(value, dict)
        return value

    def read_bytes(self, url: str, limit: int) -> bytes | None:
        """Read bytes.

        Args:
            url: Public provider destination under validation.
            limit: Maximum bytes retained at the concrete HTTP boundary.

        Returns:
            Queued complete bytes, or explicit provider absence.
        """
        self.urls.append(url)
        value = self.responses.pop(0)
        assert value is None or isinstance(value, bytes)
        return value


def artwork(front: bool = True, approved: bool = True) -> dict[str, object]:
    """Construct a representative release with a front image and unsafe unused URL.

    Args:
        front: Whether the synthetic archive entry is a main front cover.
        approved: Whether the synthetic archive entry is approved.

    Returns:
        Representative-release metadata with a controlled archive entry.
    """
    release = str(uuid5(NAMESPACE_URL, "release"))
    return {
        "release": "http://musicbrainz.org/release/" + release,
        "images": [
            {
                "id": "12345",
                "front": front,
                "approved": approved,
                "image": "https://untrusted.invalid/ignored",
            }
        ],
    }


def test_unique_complete_search_fetches_validated_representative_art_only() -> None:
    """Only escaped public names and validated IDs reach fixed provider URLs."""
    name = 'A "Record" + (Deluxe): C\\D'
    reads = PublicReads(
        [{"count": 1, "release-groups": [row(name)]}, artwork(), jpeg()]
    )
    source = MusicBrainzCoverSource(MusicBrainzRequestGate(), reads)
    result = source.read(album(name))
    assert (
        source.configured
        and result.metadata.state == "ready"
        and result.image is not None
    )
    params = parse_qs(urlsplit(reads.urls[0]).query)
    assert set(params) == {"query", "fmt", "limit"} and params["limit"] == ["100"]
    assert '\\"Record\\"' in params["query"][0] and "artist:" in params["query"][0]
    assert len(reads.urls) == 3 and reads.urls[2].endswith("/12345-250.jpg")
    assert "untrusted" not in reads.urls[2] and result.metadata.artwork is not None
    assert result.image.sha256 == result.metadata.artwork.sha256


@pytest.mark.parametrize(
    "response",
    [None, artwork(False), artwork(approved=False), {**artwork(), "images": []}],
)
def test_provider_absent_or_no_front_art_is_explicit(
    response: dict[str, object] | None,
) -> None:
    """A documented 404 or no approved front produces a dated no-cover outcome.

    Args:
        response: Controlled HTTP response at the streaming boundary.
    """
    reads = PublicReads([{"count": 1, "release-groups": [row()]}, response])
    result = MusicBrainzCoverSource(MusicBrainzRequestGate(), reads).read(album())
    assert result.metadata.state == "no_cover" and result.image is None
    assert len(reads.urls) == 2


def test_thumbnail_absence_and_unresolved_search_do_not_fetch_other_images() -> None:
    """No hidden fallback follows a missing thumbnail or ambiguous album search."""
    reads = PublicReads([{"count": 1, "release-groups": [row()]}, artwork(), None])
    assert (
        MusicBrainzCoverSource(MusicBrainzRequestGate(), reads)
        .read(album())
        .metadata.state
        == "no_cover"
    )
    unresolved = PublicReads(
        [{"count": 2, "release-groups": [row(), row(identity="two")]}]
    )
    assert (
        MusicBrainzCoverSource(MusicBrainzRequestGate(), unresolved)
        .read(album())
        .metadata.state
        == "ambiguous"
    )
    assert len(unresolved.urls) == 1
    with pytest.raises(CoverSourceError):
        MusicBrainzCoverSource(MusicBrainzRequestGate(), PublicReads([None])).read(
            album()
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"release": "https://[invalid/release/id", "images": []},
        {"release": "https://evil.invalid/release/id", "images": []},
        {**artwork(), "images": {}},
        {**artwork(), "images": [None]},
        {**artwork(), "images": [{"front": True, "approved": True, "id": "bad"}]},
        {**artwork(), "images": [{}] * 101},
    ],
)
def test_invalid_artwork_never_becomes_cached_image(payload: dict[str, object]) -> None:
    """Source release identity, approved fronts and image identifiers are bounded.

    Args:
        payload: Controlled external metadata response.
    """
    reads = PublicReads([{"count": 1, "release-groups": [row()]}, payload])
    with pytest.raises(CoverSourceError):
        MusicBrainzCoverSource(MusicBrainzRequestGate(), reads).read(album())


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"<html>not an image</html>",
        b"x" * 131073,
        jpeg(size=(1001, 1)),
        jpeg()[:-100],
    ],
)
def test_image_decoder_rejects_html_oversize_dimensions_and_truncation(
    content: bytes,
) -> None:
    """Only bounded decodable JPEG thumbnails can reach the protected image route.

    Args:
        content: Controlled external response bytes.
    """
    with pytest.raises(CoverSourceError):
        validate_cover_image(content)


@dataclass
class HttpProbe:
    """Supply HTTPX's required MockTransport request handler with fixed responses.

    Args:
        responses: Controlled HTTP responses in request order.
        urls: Request destinations observed without external network access.
    """

    responses: list[httpx.Response]
    urls: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Handle.

        Args:
            request: HTTPX request required by the external mock transport API.

        Returns:
            Next queued HTTP response without external network access.
        """
        self.urls.append(str(request.url))
        assert request.headers["User-Agent"].startswith("spotify-manager/")
        assert (
            "X-App-Password" not in request.headers
            and "Authorization" not in request.headers
        )
        return self.responses.pop(0)


def test_transport_redirects_are_validated_and_decompressed_bytes_are_bounded() -> None:
    """HTTPX MockTransport requires its bound handler; it performs no network I/O."""
    probe = HttpProbe(
        [
            httpx.Response(
                307, headers={"Location": "http://archive.org/covers/test.jpg"}
            ),
            httpx.Response(200, content=b"data"),
        ]
    )
    with httpx.Client(transport=httpx.MockTransport(probe.handle)) as client:
        assert (
            CoverHttpReads()._read(
                client, "https://coverartarchive.org/release/test/front-250", 4
            )
            == b"data"
        )
    assert probe.urls[-1] == "https://archive.org/covers/test.jpg"
    oversized = HttpProbe(
        [
            httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                content=gzip.compress(b"x" * 100),
            )
        ]
    )
    with (
        httpx.Client(transport=httpx.MockTransport(oversized.handle)) as client,
        pytest.raises(CoverSourceError),
    ):
        CoverHttpReads()._read(client, "https://archive.org/test", 99)


@pytest.mark.parametrize(
    "url",
    [
        "https://archive.org.evil.invalid/image",
        "https://127.0.0.1/image",
        "file:///etc/passwd",
        "https://user:secret@archive.org/image",
        "https://archive.org:444/image",
        "https://[invalid/image",
    ],
)
def test_redirect_destinations_reject_arbitrary_hosts_credentials_and_ports(
    url: str,
) -> None:
    """Redirects cannot turn the protected public-provider reader into a URL proxy.

    Args:
        url: Public provider destination under validation.
    """
    with pytest.raises(CoverSourceError):
        public_cover_url(url)
    assert (
        public_cover_url("http://ia800000.us.archive.org/image")
        == "https://ia800000.us.archive.org/image"
    )


@pytest.mark.parametrize(
    "responses",
    [
        [httpx.Response(404)],
        [httpx.Response(503)],
        [httpx.Response(307)],
        [httpx.Response(302, headers={"Location": "https://archive.org/loop"})] * 5,
    ],
)
def test_transport_absence_errors_and_redirect_budget(
    responses: list[httpx.Response],
) -> None:
    """Provider absence is distinct from rate-limit, malformed redirect or loops.

    Args:
        responses: Ordered HTTP responses consumed by the offline transport.
    """
    probe = HttpProbe(responses.copy())
    with httpx.Client(transport=httpx.MockTransport(probe.handle)) as client:
        if responses[0].status_code == 404:
            assert (
                CoverHttpReads()._read(client, "https://coverartarchive.org/test", 100)
                is None
            )
        else:
            with pytest.raises(CoverSourceError):
                CoverHttpReads()._read(client, "https://coverartarchive.org/test", 100)


class BytesReads(CoverHttpReads):
    """Return one controlled raw response at the concrete bytes boundary."""

    def __init__(self, content: bytes | None) -> None:
        """Bind controlled test resources without starting work.

        Args:
            content: Controlled external response bytes.
        """
        self.content = content

    def read_bytes(self, url: str, limit: int) -> bytes | None:
        """Read bytes.

        Args:
            url: Public provider destination under validation.
            limit: Maximum bytes retained at the concrete HTTP boundary.

        Returns:
            Queued complete bytes, or explicit provider absence.
        """
        return self.content


@pytest.mark.parametrize("content", [b"[]", b"bad-json", b"\xff"])
def test_raw_json_must_be_a_complete_object(content: bytes) -> None:
    """Raw json must be a complete object.

    Args:
        content: Controlled external response bytes.
    """
    with pytest.raises(CoverSourceError):
        BytesReads(content).read_json("https://musicbrainz.org/ws/2/release-group/")
    assert BytesReads(None).read_json("https://coverartarchive.org/test") is None
    assert BytesReads(b"{}").read_json("https://coverartarchive.org/test") == {}


class BrokenReads(CoverHttpReads):
    """Fail before any remote request to exercise sanitized transport errors."""

    def _read(self, client: httpx.Client, target: str, limit: int) -> bytes | None:
        raise httpx.ConnectError("test-only-secret")


def test_transport_error_is_sanitized() -> None:
    """Transport error is sanitized."""
    with pytest.raises(CoverSourceError) as error:
        BrokenReads().read_bytes("https://coverartarchive.org/test", 100)
    assert "test-only-secret" not in str(error.value)


class TimedCoverSource(MusicBrainzCoverSource):
    """Observe the real shared gate around a no-network cover read."""

    def __init__(self, gate: MusicBrainzRequestGate, times: list[float]) -> None:
        """Bind controlled test resources without starting work.

        Args:
            gate: Shared MusicBrainz request-start resource.
            times: Observed request-start times for cross-view spacing assertions.
        """
        super().__init__(gate, PublicReads([]))
        self.times = times

    def read(self, selected: RankedEntity) -> CoverFetchResult:
        """Read.

        Args:
            selected: Captured synthetic album and artist identity.

        Returns:
            Complete controlled provider observation.
        """
        self.times.append(time.monotonic())
        return cover_result(selected.name, selected.artist)


class TimedOriginSource(MusicBrainzOriginSource):
    """Observe the same shared gate from the independent country resource."""

    def __init__(self, gate: MusicBrainzRequestGate, times: list[float]) -> None:
        """Bind controlled test resources without starting work.

        Args:
            gate: Shared MusicBrainz request-start resource.
            times: Observed request-start times for cross-view spacing assertions.
        """
        super().__init__(gate)
        self.times = times

    def read(self, artist: RankedEntity) -> ArtistOriginMetadata:
        """Read.

        Args:
            artist: Synthetic complete credited artist name.

        Returns:
            Complete controlled provider observation.
        """
        self.times.append(time.monotonic())
        return origin_metadata(artist.name)


async def test_two_features_share_spacing_and_wait_cancellation_releases_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Country and cover requests cannot collectively exceed the provider budget.

    Args:
        monkeypatch: Scoped replacements for timing and concrete integration boundaries.
    """
    monkeypatch.setattr(musicbrainz_gate, "REQUEST_INTERVAL", 0.025)
    gate = MusicBrainzRequestGate()
    times: list[float] = []
    covers, origins = TimedCoverSource(gate, times), TimedOriginSource(gate, times)
    await asyncio.gather(covers.fetch(album()), origins.fetch(album()))
    assert times[1] - times[0] >= 0.02
    waiting = asyncio.create_task(covers.fetch(album()))
    await asyncio.sleep(0.001)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await covers.fetch(album())
    assert len(times) == 3


class HeldCoverSource(MusicBrainzCoverSource):
    """Hold one active blocking read through cancellation."""

    def __init__(self, started: Event, release: Event) -> None:
        """Bind controlled test resources without starting work.

        Args:
            started: Event marking an active blocking operation.
            release: Event allowing the controlled blocking operation to finish.
        """
        super().__init__(MusicBrainzRequestGate(), PublicReads([]))
        self.started, self.release = started, release

    def read(self, selected: RankedEntity) -> CoverFetchResult:
        """Read.

        Args:
            selected: Captured synthetic album and artist identity.

        Returns:
            Complete controlled provider observation.
        """
        self.started.set()
        assert self.release.wait(5)
        return cover_result(selected.name, selected.artist)


async def test_active_cover_read_drains_before_releasing_gate() -> None:
    """Active cover read drains before releasing gate."""
    started, release = Event(), Event()
    source = HeldCoverSource(started, release)
    task = asyncio.create_task(source.fetch(album()))
    while not started.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_streamed_byte_and_time_limits_apply_before_retaining_content() -> None:
    """A slow or oversized plain response cannot accumulate an unbounded body."""
    response = httpx.Response(200, content=b"x" * 100)
    with pytest.raises(CoverSourceError, match="size limit"):
        _content(response, 99, time.monotonic() + 30)
    with pytest.raises(CoverSourceError, match="time budget"):
        _content(response, 100, time.monotonic() - 1)


class InvalidUrlReads(CoverHttpReads):
    """Simulate an invalid provider redirect without opening a connection."""

    def _read(self, client: httpx.Client, target: str, limit: int) -> bytes | None:
        raise httpx.InvalidURL("test-only-secret")


def test_invalid_provider_redirect_becomes_a_safe_stopped_batch_error() -> None:
    """A malformed URL must not escape the stage's documented provider failures."""
    with pytest.raises(CoverSourceError) as error:
        InvalidUrlReads().read_bytes("https://coverartarchive.org/test", 100)
    assert "test-only-secret" not in str(error.value)


async def test_worker_capacity_wait_cannot_consume_the_shared_spacing_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed request still leaves the required interval before the next view.

    Args:
        monkeypatch: Scoped replacement of the provider spacing interval.
    """
    monkeypatch.setattr(musicbrainz_gate, "REQUEST_INTERVAL", 0.025)
    gate = MusicBrainzRequestGate()
    starts: list[float] = []
    async with gate:
        await asyncio.sleep(0.04)
        starts.append(time.monotonic())
    async with gate:
        starts.append(time.monotonic())
    assert starts[1] - starts[0] >= 0.02
