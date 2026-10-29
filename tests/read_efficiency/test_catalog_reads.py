"""Compare bounded catalog reads against the unchanged serial implementation."""

import asyncio

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.exceptions import SpotifyException

from spotify_manager.domain.lookup_values import SpotifyLookupResponseError
from spotify_manager.infrastructure.catalog_reads import AlbumCatalogReads
from spotify_manager.infrastructure.catalog_reads import album_windows
from spotify_manager.infrastructure.lookup_catalog import primary_tracks
from tests.read_efficiency.catalog_memory import CatalogPages
from tests.read_efficiency.catalog_memory import HeldCatalogPages
from tests.read_efficiency.catalog_memory import release_ids
from tests.support.library_lookup_run import raw_track


@pytest.mark.parametrize("count", [0, 1, 19, 20, 21, 60, 80, 81, 160, 641])
async def test_independent_batches_preserve_all_results_and_request_sizes(
    count: int,
) -> None:
    """Match the original parser while bounding native overlap to four reads.

    Args:
        count: Boundary around existing endpoint and read-window sizes.
    """
    identifiers = release_ids(count)
    serial, parallel = CatalogPages(), CatalogPages()
    expected = await primary_tracks(serial, "artist", identifiers, 20)
    actual = await AlbumCatalogReads(parallel).primary_tracks("artist", identifiers, 20)
    assert actual == expected == identifiers
    assert parallel.calls == serial.calls
    assert parallel.peak == min(4, len(serial.calls))
    assert parallel.active == 0


@pytest.mark.parametrize("repetitions", [1, 2, 3])
async def test_repeated_catalog_batches_share_only_this_snapshot(
    repetitions: int,
) -> None:
    """Reuse metadata without changing the original duplicate-result semantics.

    Args:
        repetitions: Number of complete repeated catalogs in one read operation.
    """
    source = CatalogPages()
    identifiers = release_ids(80)
    reader = AlbumCatalogReads(source)
    result = await reader.primary_tracks("artist", identifiers * repetitions, 20)
    assert result == identifiers
    assert (len(source.calls), source.peak) == (4, 4)
    assert await reader.primary_tracks("artist", identifiers, 20) == identifiers
    assert len(source.calls) == 8


async def test_simultaneous_identical_batches_have_one_upstream_read() -> None:
    """Keep duplicate IDs in the endpoint call but share the identical operation."""
    source = CatalogPages()
    identifiers = ["same"] * 80
    assert await AlbumCatalogReads(source).primary_tracks(
        "artist", identifiers, 20
    ) == ["same"]
    assert source.calls == [("same",) * 20]
    assert source.peak == 1 and source.active == 0


@pytest.mark.parametrize("size", [0, -1, -20])
def test_batch_range_boundary_behavior_is_unchanged(size: int) -> None:
    """Keep the original range behavior rather than adding unrelated validation.

    Args:
        size: Original zero or negative range step.
    """
    if size:
        assert list(album_windows(["album"], size)) == []
        return
    with pytest.raises(ValueError, match="range"):
        list(album_windows(["album"], size))


@pytest.mark.parametrize("position", [0, 1, 2, 3])
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_original_http_failure_identity_and_order(
    position: int, status: int
) -> None:
    """Return the original Spotify failure after all admitted reads have drained.

    Args:
        position: Original failing batch in the bounded window.
        status: Existing HTTP classification owned by the transport/retry policy.
    """
    identifiers = release_ids(80)
    batch = tuple(identifiers[position * 20 : (position + 1) * 20])
    error = SpotifyException(status, -1, "original", headers={"Retry-After": "7"})
    source = CatalogPages(failures={batch: error})
    with pytest.raises(SpotifyException) as caught:
        await AlbumCatalogReads(source).primary_tracks("artist", identifiers, 20)
    assert caught.value is error
    assert caught.value.headers == {"Retry-After": "7"}
    assert len(source.calls) == 4 and source.active == 0


async def test_first_traversal_error_wins_over_a_later_batch_failure() -> None:
    """Validate earlier rows before exposing a later independent read's error."""
    identifiers = release_ids(40)
    first = tuple(identifiers[:20])
    second = tuple(identifiers[20:])
    source = CatalogPages(replies={first: None}, failures={second: ValueError("later")})
    with pytest.raises(SpotifyLookupResponseError, match="batched album"):
        await AlbumCatalogReads(source).primary_tracks("artist", identifiers, 20)
    assert source.active == 0


async def test_dependent_track_failure_precedes_a_later_batch_failure() -> None:
    """Keep input-order failure precedence while metadata responses overlap."""
    identifiers = release_ids(40)
    first = tuple(identifiers[:20])
    page = {"items": [raw_track("first")], "next": "next-page"}
    error = RequestsConnectionError("dependent page")
    source = CatalogPages(
        replies={first: {"albums": [{"tracks": page}]}},
        failures={tuple(identifiers[20:]): ValueError("later batch")},
        continuations=[error],
    )
    with pytest.raises(RequestsConnectionError) as caught:
        await AlbumCatalogReads(source).primary_tracks("artist", identifiers, 20)
    assert caught.value is error and source.pages == [page]
    assert source.active == 0


async def test_dependent_pages_keep_original_order_and_first_encounters() -> None:
    """Traverse an album's pages before the next album and retain first credits."""
    first_page = {"items": [raw_track("first")], "next": "first-next"}
    guest = raw_track("guest")
    guest["artists"] = [{"id": "guest"}]
    source = CatalogPages(
        replies={
            ("a", "b"): {
                "albums": [
                    None,
                    {"tracks": first_page},
                    {"tracks": {"items": [raw_track("second"), guest], "next": None}},
                ]
            }
        },
        continuations=[
            {"items": [raw_track("first"), raw_track("continuation")], "next": None}
        ],
    )
    result = await AlbumCatalogReads(source).primary_tracks("artist", ["a", "b"], 20)
    assert result == ["first", "continuation", "second"]
    assert source.pages == [first_page] and source.calls == [("a", "b")]


@pytest.mark.parametrize(
    "error", [KeyboardInterrupt("original"), SystemExit("original")]
)
async def test_process_control_returns_to_the_original_caller(
    error: BaseException,
) -> None:
    """Prevent a child read task from stopping the event loop before its caller.

    Args:
        error: Original caller-owned process-control failure.
    """
    source = CatalogPages(failures={("album",): error})
    with pytest.raises(type(error)) as caught:
        await AlbumCatalogReads(source).primary_tracks("artist", ["album"], 20)
    assert caught.value is error and source.active == 0


async def test_failed_snapshot_does_not_poison_the_next_read() -> None:
    """Discard failed and successful batch entries at every read-operation exit."""
    error = ValueError("first attempt")
    source = CatalogPages(failures={("album",): error})
    reader = AlbumCatalogReads(source)
    with pytest.raises(ValueError) as caught:
        await reader.primary_tracks("artist", ["album"], 20)
    assert caught.value is error
    source.failures.clear()
    assert await reader.primary_tracks("artist", ["album"], 20) == ["album"]
    assert source.calls == [("album",), ("album",)]


async def test_bounded_cache_evicts_completed_metadata() -> None:
    """Limit retained raw responses without changing the final catalog sequence."""
    identifiers = release_ids(660)
    source = CatalogPages()
    result = await AlbumCatalogReads(source).primary_tracks(
        "artist", identifiers + identifiers[:20], 20
    )
    assert result == identifiers
    assert len(source.calls) == 34 and source.peak == 4


async def test_response_order_cannot_change_the_catalog_order() -> None:
    """Complete the last request first while keeping all original result positions."""
    source = HeldCatalogPages()
    identifiers = release_ids(80)
    operation = asyncio.create_task(
        AlbumCatalogReads(source).primary_tracks("artist", identifiers, 20)
    )
    await source.entered.wait()
    order = list(reversed(source.calls))
    for key in order:
        source.releases[key].set()
        await asyncio.sleep(0)
    assert await operation == identifiers
    assert source.completed == order and source.active == 0


async def test_cancelled_window_drains_every_admitted_read() -> None:
    """Cancel a read-only window without leaving tasks or retaining its snapshot."""
    source = HeldCatalogPages()
    identifiers = release_ids(80)
    reader = AlbumCatalogReads(source)
    operation = asyncio.create_task(reader.primary_tracks("artist", identifiers, 20))
    await source.entered.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert len(source.completed) == 4 and source.active == 0
    for release in source.releases.values():
        release.set()
    assert await reader.primary_tracks("artist", identifiers, 20) == identifiers
    assert len(source.calls) == 8


@pytest.mark.parametrize(
    "value",
    [None, [], "bad", ValueError("returned data"), KeyboardInterrupt("returned data")],
)
async def test_malformed_return_values_are_not_treated_as_raised_failures(
    value: object,
) -> None:
    """Retain parser errors even when an invalid override returns an exception value.

    Args:
        value: Original malformed successful return, distinct from a raised error.
    """
    source = CatalogPages(replies={("album",): value})
    with pytest.raises(SpotifyLookupResponseError, match="batched album"):
        await AlbumCatalogReads(source).primary_tracks("artist", ["album"], 20)


async def test_failed_window_waits_for_every_admitted_sibling() -> None:
    """Keep read ownership until slower siblings have settled after an early error."""
    identifiers = release_ids(80)
    error = ValueError("first batch")
    source = HeldCatalogPages(failures={tuple(identifiers[:20]): error})
    operation = asyncio.create_task(
        AlbumCatalogReads(source).primary_tracks("artist", identifiers, 20)
    )
    await source.entered.wait()
    assert not operation.done() and source.active == 3
    for release in source.releases.values():
        release.set()
    with pytest.raises(ValueError) as caught:
        await operation
    assert caught.value is error and source.active == 0
    assert len(source.completed) == 4
