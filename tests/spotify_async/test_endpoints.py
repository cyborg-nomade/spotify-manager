"""Compare actual prepared native HTTP against the installed synchronous SDK."""

import asyncio
import json
import warnings
from pathlib import Path

import pytest
from spotipy import Spotify

from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from tests.spotify_async.cases import CASES
from tests.spotify_async.cases import EndpointCase
from tests.spotify_async.memory import ResponseSpec
from tests.spotify_async.memory import SynchronousRecorder
from tests.spotify_async.memory import transport_memory


@pytest.mark.parametrize("case", CASES)
def test_endpoint_wire_contract_matches_installed_sdk(case: EndpointCase) -> None:
    """Compare paths, query ordering, bodies and explicit headers.

    Args:
        case: Original SDK invocation values.
    """
    asyncio.run(_compare(case))


async def _compare(case: EndpointCase) -> None:
    memory = transport_memory([ResponseSpec(payload={"contract": True})])
    session = SynchronousRecorder()
    baseline = Spotify(auth="primary-token", requests_session=session)
    native = AsyncSpotify(memory.transport)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            expected = getattr(baseline, case.name)(*case.args, **case.keywords)
            result = await getattr(native, case.name)(*case.args, **case.keywords)
        assert result == expected == {"contract": True}
        _assert_requests(session, memory.http.requests[-1])
    finally:
        await memory.transport.aclose()
        session.close()


def _assert_requests(session: SynchronousRecorder, actual: object) -> None:
    import httpx

    assert isinstance(actual, httpx.Request)
    expected = session.observed
    assert expected is not None
    assert actual.method == expected.method
    assert str(actual.url) == expected.url
    body = expected.body
    if isinstance(body, str):
        body = body.encode()
    assert actual.content == (body or b"")
    for name in ("Authorization", "Content-Type"):
        assert actual.headers[name] == expected.headers[name]


def test_endpoint_subset_matches_frozen_inventory() -> None:
    """Require explicit native coverage for every frozen SDK method."""
    path = Path(__file__).parents[2] / "docs/refactor/baseline/spotify-endpoints.json"
    expected = set(json.loads(path.read_text())["sdk_methods"])
    assert {case.name for case in CASES} == expected


def test_recorded_synchronous_requests_remain_frozen() -> None:
    """Keep durable request recordings tied to the locked SDK behavior."""
    from importlib.metadata import version

    path = Path(__file__).parent / "fixtures/requests.json"
    recording = json.loads(path.read_text())
    assert recording["sdk_version"] == version("spotipy")
    for case, expected in zip(CASES, recording["requests"], strict=True):
        _assert_recorded(case, expected)


def _assert_recorded(case: EndpointCase, expected: dict[str, object]) -> None:
    session = SynchronousRecorder()
    client = Spotify(auth="primary-token", requests_session=session)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            getattr(client, case.name)(*case.args, **case.keywords)
        request = session.observed
        assert request is not None
        assert request.method == expected["method"]
        assert request.url == expected["url"]
        assert (request.body or None) == expected["body"]
        assert request.headers["Content-Type"] == expected["content_type"]
    finally:
        session.close()
