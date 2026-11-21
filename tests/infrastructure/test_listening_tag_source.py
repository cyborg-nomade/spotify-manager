"""Public tag reads validate identity and never expose API credentials."""

import json
from dataclasses import dataclass
from types import TracebackType
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from spotify_manager.application.listening_tag_ports import TagSourceError
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening import tag_source
from spotify_manager.infrastructure.listening.tag_source import LastFmTagSource
from spotify_manager.infrastructure.listening.tag_source import parse_artist_tags


def artist(name: str = "Alpha") -> RankedEntity:
    """Return a stable selected artist identity for provider-boundary tests."""
    return RankedEntity(listening_identity((name,)), name, "", 1, 1.0)


def payload(name: str = "Alpha", tags: object = None) -> dict[str, object]:
    """Return an explicit provider response including its reported artist."""
    rows = [{"name": "Rock", "count": "100"}] if tags is None else tags
    return {"toptags": {"@attr": {"artist": name}, "tag": rows}}


@dataclass
class Response:
    """Represent bounded response bytes without performing network I/O."""

    content: bytes

    def __enter__(self) -> Response:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, amount: int) -> bytes:
        return self.content[:amount]


@dataclass
class ProviderProbe:
    """Record the fixed public request through urllib's framework seam."""

    content: bytes
    request: Request | None = None

    def open(self, request: Request, *, timeout: int) -> Response:
        self.request = request
        assert timeout == 15
        return Response(self.content)


def test_read_uses_only_the_named_artist_and_never_caches_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the documented public method and artist name leave the boundary."""
    probe = ProviderProbe(json.dumps(payload()).encode())
    monkeypatch.setattr(tag_source, "urlopen", probe.open)
    source = LastFmTagSource("test-only-secret")
    result = source.read(artist())
    assert source.configured and probe.request is not None
    assert "artist.getTopTags" in probe.request.full_url
    assert "autocorrect=0" in probe.request.full_url
    assert "username=" not in probe.request.full_url
    assert "scrobbles" not in probe.request.full_url
    assert result.state == "tagged" and result.tags[0].name == "Rock"
    assert "test-only-secret" not in repr(result)
    assert result.source_url == "https://www.last.fm/music/Alpha/+tags"


def test_ranked_tags_deduplicate_preserve_accents_and_bound_candidates() -> None:
    """Provider order is evidence; labels are not inferred genre probabilities."""
    rows = [{"name": " Récord "}, {"name": "Re\u0301cord"}, {"name": "Record"}]
    rows.extend({"name": f"Tag {index}"} for index in range(20))
    result = parse_artist_tags(payload(" ALPHA ", rows), artist())
    assert [item.name for item in result.tags[:2]] == ["Récord", "Record"]
    assert len(result.tags) == 10


def test_unresolved_identity_and_empty_tags_are_distinct_completed_results() -> None:
    """A different provider artist never silently inherits the requested identity."""
    mismatch = parse_artist_tags(payload("Beta"), artist())
    assert mismatch.state == "unresolved" and mismatch.tags == ()
    missing = parse_artist_tags({"error": 6}, artist())
    assert missing.state == "unresolved"
    empty = parse_artist_tags(payload(tags=[]), artist())
    assert empty.state == "empty" and empty.tags == ()


@pytest.mark.parametrize(
    "raw",
    [
        {"error": 29, "message": "test-only-secret"},
        {},
        {"toptags": {}},
        payload(tags={}),
        payload(tags=[None]),
        payload(tags=[{"name": ""}]),
        payload(tags=[{"name": 7}]),
    ],
)
def test_malformed_or_unavailable_provider_is_a_safe_failure(
    raw: dict[str, object],
) -> None:
    """Invalid provider payloads never erase previously cached metadata."""
    with pytest.raises(TagSourceError) as raised:
        parse_artist_tags(raw, artist())
    assert "test-only-secret" not in str(raised.value)


@pytest.mark.parametrize("content", [b"[]", b"not-json", b"\xff", b"x" * (1048576 + 1)])
def test_invalid_or_oversized_raw_response_is_bounded(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    """The concrete HTTP edge rejects unbounded or structurally invalid input."""
    monkeypatch.setattr(tag_source, "urlopen", ProviderProbe(content).open)
    with pytest.raises(TagSourceError):
        LastFmTagSource("test-only-secret").read(artist())


def test_unconfigured_source_never_attempts_a_request() -> None:
    """Cached viewing does not require a configured public provider key."""
    source = LastFmTagSource(None)
    assert not source.configured
    with pytest.raises(TagSourceError):
        source.read(artist())


@dataclass
class OfflineProbe:
    """Raise one urllib transport failure without exposing its secret URL."""

    def open(self, request: Request, *, timeout: int) -> Response:
        raise HTTPError(request.full_url, 429, "test-only-secret", None, None)


def test_transport_failure_redacts_secret_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even an exception containing an API URL stays outside public messages."""
    monkeypatch.setattr(tag_source, "urlopen", OfflineProbe().open)
    with pytest.raises(TagSourceError) as raised:
        LastFmTagSource("test-only-secret").read(artist())
    assert "test-only-secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_async_provider_boundary_returns_complete_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The concrete thread bridge finishes before exposing provider observations."""
    monkeypatch.setattr(
        tag_source, "urlopen", ProviderProbe(json.dumps(payload()).encode()).open
    )
    result = await LastFmTagSource("test-only-secret").fetch(artist())
    assert result.state == "tagged"
